import ipaddress
import re
import subprocess

from core import database

LEASE_FILE = "/var/lib/misc/dnsmasq.leases"
ONLINE_ARP_STATES = {"REACHABLE", "DELAY", "PROBE", "STALE"}
ARPING_TIMEOUT_SECONDS = 1
HOSTAPD_TIMEOUT_SECONDS = 1
MAC_LINE_PATTERN = re.compile(r"^(?:STA\s+)?([0-9a-f]{2}(?::[0-9a-f]{2}){5})\\b", re.IGNORECASE)

def get_active_macs_from_arp():
    """Use ip neigh to identify MAC addresses currently reachable on the network."""
    active_macs = set()
    try:
        result = subprocess.check_output(['ip', 'neigh'], text=True)
        
        for line in result.split('\n'):
            parts = line.split()
            # Typical line format: 192.168.10.68 dev wlan0 lladdr c0:a5... REACHABLE
            if len(parts) >= 5 and 'lladdr' in line:
                mac = parts[4].lower()
                state = parts[-1].upper()
                
                if state in ONLINE_ARP_STATES:
                    active_macs.add(mac)
    except Exception as e:
        print("Error while scanning ARP:", e)
        
    return active_macs

def _get_wireless_interfaces():
    """Discover wireless interfaces that can be queried via hostapd_cli."""
    interfaces = set()
    try:
        result = subprocess.run(
            ["iwconfig"],
            check=False,
            capture_output=True,
            text=True,
            timeout=HOSTAPD_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return interfaces

        for raw_line in result.stdout.splitlines():
            if not raw_line or raw_line.startswith(" "):
                continue

            line = raw_line.strip()
            if "no wireless extensions" in line.lower():
                continue

            iface = line.split()[0]
            if iface:
                interfaces.add(iface)
    except Exception:
        pass

    return interfaces

def get_associated_wifi_macs():
    """Read currently associated Wi-Fi clients from hostapd.

    Returns:
        tuple[set[str], bool]: (associated_macs, has_hostapd_data)
    """
    associated_macs = set()
    has_hostapd_data = False
    for interface in _get_wireless_interfaces():
        try:
            result = subprocess.run(
                ["hostapd_cli", "-i", interface, "all_sta"],
                check=False,
                capture_output=True,
                text=True,
                timeout=HOSTAPD_TIMEOUT_SECONDS,
            )
            if result.returncode != 0:
                continue

            has_hostapd_data = True

            for line in result.stdout.splitlines():
                match = MAC_LINE_PATTERN.match(line.strip())
                if match:
                    associated_macs.add(match.group(1).lower())
        except Exception:
            continue

    return associated_macs, has_hostapd_data

def _resolve_interface_for_ip(ip):
    """Resolve outgoing interface for an IP so arping probes the correct LAN adapter."""
    try:
        result = subprocess.run(
            ["ip", "route", "get", ip],
            check=False,
            capture_output=True,
            text=True,
            timeout=ARPING_TIMEOUT_SECONDS,
        )
        if result.returncode != 0:
            return None

        tokens = result.stdout.split()
        if "dev" in tokens:
            dev_index = tokens.index("dev")
            if dev_index + 1 < len(tokens):
                return tokens[dev_index + 1]
    except Exception:
        pass

    return None

def _arping_is_online(ip):
    """Actively verify host presence to reduce delay when a device disconnects."""
    try:
        ipaddress.ip_address(str(ip).strip())
    except ValueError:
        return None

    interface = _resolve_interface_for_ip(ip)
    command = ["arping", "-c", "1", "-w", str(ARPING_TIMEOUT_SECONDS)]
    if interface:
        command.extend(["-I", interface])
    command.append(ip)

    try:
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            timeout=ARPING_TIMEOUT_SECONDS + 0.5,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        return False
    except Exception:
        return None

def scan_and_update_devices():
    """Update DB state and refresh LastSeen only for currently reachable devices."""
    active_macs = get_active_macs_from_arp()
    associated_wifi_macs, has_hostapd_data = get_associated_wifi_macs()
    wireless_interfaces = _get_wireless_interfaces()
    connected_macs = active_macs | associated_wifi_macs
    online_state_by_mac = {}
    
    try:
        with open(LEASE_FILE, 'r') as f:
            lines = f.readlines()
            for line in lines:
                parts = line.split()
                if len(parts) >= 4:
                    mac = parts[1].lower()
                    ip = parts[2]
                    hostname = parts[3]

                    route_interface = _resolve_interface_for_ip(ip)
                    is_wireless_client = bool(route_interface and route_interface in wireless_interfaces)

                    if is_wireless_client and has_hostapd_data:
                        # AP association is the most reliable signal for Wi-Fi idle clients.
                        is_online = mac in associated_wifi_macs
                    else:
                        is_online = mac in connected_macs

                    # For non-Wi-Fi candidates coming from ARP cache only, probe to avoid stale-online.
                    if is_online and mac in active_macs and mac not in associated_wifi_macs and not is_wireless_client:
                        # ARP cache can lag on disconnect; probe live to confirm online state.
                        probed_online = _arping_is_online(ip)
                        if probed_online is not None:
                            is_online = probed_online

                    online_state_by_mac[mac] = is_online
                    update_device_in_db(mac, ip, hostname, is_online)
    except FileNotFoundError:
        print("Leases file not found yet.")
        
    return get_all_devices_from_db(online_state_by_mac)

def update_device_in_db(mac, ip, hostname, is_online):
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM Devices WHERE MacAddress = ?", (mac,))
    device = cursor.fetchone()
    
    if device is None:
        cursor.execute('''
            INSERT INTO Devices (MacAddress, IpAddress, OriginalName, CustomName, IsBlocked)
            VALUES (?, ?, ?, ?, 0)
        ''', (mac, ip, hostname, hostname))
    else:
        # Update LastSeen only when device is currently confirmed online.
        if is_online:
            cursor.execute('''
                UPDATE Devices 
                SET IpAddress = ?, OriginalName = ?, LastSeen = datetime('now', 'localtime')
                WHERE MacAddress = ?
            ''', (ip, hostname, mac))
        else:
            # Keep LastSeen unchanged for offline devices; only update mutable fields.
            cursor.execute('''
                UPDATE Devices 
                SET IpAddress = ?, OriginalName = ?
                WHERE MacAddress = ?
            ''', (ip, hostname, mac))
            
    conn.commit()
    conn.close()

def get_all_devices_from_db(online_state_by_mac=None):
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Devices ORDER BY LastSeen DESC")
    devices = [dict(row) for row in cursor.fetchall()]
    conn.close()

    if online_state_by_mac is None:
        active_macs = get_active_macs_from_arp()
        associated_wifi_macs, _ = get_associated_wifi_macs()
        connected_macs = active_macs | associated_wifi_macs
        for device in devices:
            device['IsOnline'] = device['MacAddress'] in connected_macs
        return devices

    for device in devices:
        device['IsOnline'] = bool(online_state_by_mac.get(device['MacAddress'], False))
        
    return devices