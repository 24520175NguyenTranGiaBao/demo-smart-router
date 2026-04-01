import subprocess

from core import database

LEASE_FILE = "/var/lib/misc/dnsmasq.leases"

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
                state = parts[-1]
                
                if state in ['REACHABLE', 'DELAY']:
                    active_macs.add(mac)
    except Exception as e:
        print("Error while scanning ARP:", e)
        
    return active_macs

def scan_and_update_devices():
    """Update DB state and refresh LastSeen only for currently reachable devices."""
    active_macs = get_active_macs_from_arp()
    
    try:
        with open(LEASE_FILE, 'r') as f:
            lines = f.readlines()
            for line in lines:
                parts = line.split()
                if len(parts) >= 4:
                    mac = parts[1].lower()
                    ip = parts[2]
                    hostname = parts[3]
                    is_online = mac in active_macs
                    update_device_in_db(mac, ip, hostname, is_online)
    except FileNotFoundError:
        print("Leases file not found yet.")
        
    return get_all_devices_from_db()

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
        # Update LastSeen only when device is currently online (present in ARP table).
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

def get_all_devices_from_db():
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM Devices ORDER BY LastSeen DESC")
    devices = [dict(row) for row in cursor.fetchall()]
    conn.close()

    # Re-scan network to provide the most up-to-date online state.
    active_macs = get_active_macs_from_arp()
    
    # Inject IsOnline flag before returning devices to the web layer.
    for device in devices:
        device['IsOnline'] = device['MacAddress'] in active_macs
        
    return devices