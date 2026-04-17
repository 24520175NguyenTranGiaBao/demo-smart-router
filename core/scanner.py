import ipaddress
import re
import subprocess

from core import database

LEASE_FILE = "/var/lib/misc/dnsmasq.leases"
ONLINE_ARP_STATES = {"REACHABLE", "DELAY", "PROBE", "STALE"}
ARPING_TIMEOUT_SECONDS = 1
HOSTAPD_TIMEOUT_SECONDS = 1
PROBE_FAILURE_THRESHOLD = 2
MAC_LINE_PATTERN = re.compile(r"^(?:STA\s+)?([0-9a-f]{2}(?::[0-9a-f]{2}){5})\\b", re.IGNORECASE)
probe_failure_counts = {}

def get_active_macs_from_arp():
    """Read ARP neighbor table and collect currently reachable MAC addresses.

    Returns:
        set[str]: MAC addresses with ARP states considered online.
    """
    active_macs = set()
    try:
        result = subprocess.check_output(['ip', 'neigh'], text=True)
        
        for line in result.split('\n'):
            parts = line.split()
            if len(parts) >= 5 and 'lladdr' in line:
                mac = parts[4].lower()
                state = parts[-1].upper()
                
                if state in ONLINE_ARP_STATES:
                    active_macs.add(mac)
    except Exception as e:
        print("Error while scanning ARP:", e)
        
    return active_macs

def _get_wireless_interfaces():
    """Discover wireless interfaces available on the host.

    Returns:
        set[str]: Interface names that support wireless operations.
    """
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
    """Resolve outgoing interface for an IP address.

    Args:
        ip: IPv4/IPv6 address string.

    Returns:
        str | None: Interface name if resolved, otherwise None.
    """
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
    """Probe host liveness with arping.

    Args:
        ip: Target IP address to probe.

    Returns:
        bool | None: True if online, False if unreachable, None if undetermined.
    """
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
    """Scan leases/network state, update DB records, and return device list.

    Returns:
        list[dict]: Device records enriched with calculated online state.
    """
    active_macs = get_active_macs_from_arp()
    associated_wifi_macs, has_hostapd_data = get_associated_wifi_macs()
    wireless_interfaces = _get_wireless_interfaces()
    connected_macs = active_macs | associated_wifi_macs
    online_state_by_mac = {}
    seen_macs = set()
    
    try:
        with open(LEASE_FILE, 'r') as f:
            lines = f.readlines()
            for line in lines:
                parts = line.split()
                if len(parts) >= 4:
                    mac = parts[1].lower()
                    ip = parts[2]
                    hostname = parts[3]
                    seen_macs.add(mac)

                    route_interface = _resolve_interface_for_ip(ip)
                    is_wireless_client = bool(route_interface and route_interface in wireless_interfaces)

                    if is_wireless_client and has_hostapd_data:
                        is_online = mac in associated_wifi_macs
                    else:
                        is_online = mac in connected_macs

                    should_probe = is_online and (
                        is_wireless_client
                        or (mac in active_macs and mac not in associated_wifi_macs)
                    )

                    if should_probe:
                        probed_online = _arping_is_online(ip)
                        if probed_online is True:
                            probe_failure_counts.pop(mac, None)
                            is_online = True
                        elif probed_online is False:
                            failures = probe_failure_counts.get(mac, 0) + 1
                            probe_failure_counts[mac] = failures
                            if failures >= PROBE_FAILURE_THRESHOLD:
                                is_online = False
                        else:
                            probe_failure_counts.pop(mac, None)
                    else:
                        probe_failure_counts.pop(mac, None)

                    online_state_by_mac[mac] = is_online
                    update_device_in_db(mac, ip, hostname, is_online)
    except FileNotFoundError:
        print("Leases file not found yet.")

    stale_probe_macs = [mac for mac in probe_failure_counts if mac not in seen_macs]
    for mac in stale_probe_macs:
        probe_failure_counts.pop(mac, None)
        
    return get_all_devices_from_db(online_state_by_mac)

def update_device_in_db(mac, ip, hostname, is_online):
    """Insert or update one device row based on scan results.

    Args:
        mac: Device MAC address.
        ip: Current device IP address.
        hostname: Observed hostname from lease data.
        is_online: Confirmed online state for this scan cycle.
    """
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
        if is_online:
            cursor.execute('''
                UPDATE Devices 
                SET IpAddress = ?, OriginalName = ?, LastSeen = datetime('now', 'localtime')
                WHERE MacAddress = ?
            ''', (ip, hostname, mac))
        else:
            cursor.execute('''
                UPDATE Devices 
                SET IpAddress = ?, OriginalName = ?
                WHERE MacAddress = ?
            ''', (ip, hostname, mac))
            
    conn.commit()
    conn.close()

def get_all_devices_from_db(online_state_by_mac=None):
    """Fetch all known devices and attach online status.

    Args:
        online_state_by_mac: Optional precomputed online-state map by MAC.

    Returns:
        list[dict]: Device rows sorted by most recent LastSeen.
    """
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