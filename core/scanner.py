import subprocess

from core import database

LEASE_FILE = "/var/lib/misc/dnsmasq.leases"

def get_active_macs_from_arp():
    """Dùng công cụ ip neigh để bắt chính xác trạng thái REACHABLE"""
    active_macs = set()
    try:
        # Gọi lệnh Linux 'ip neigh' và lấy kết quả trả về
        result = subprocess.check_output(['ip', 'neigh'], text=True)
        
        # Phân tích từng dòng kết quả
        for line in result.split('\n'):
            parts = line.split()
            # Một dòng chuẩn sẽ có dạng: 192.168.10.68 dev wlan0 lladdr c0:a5... REACHABLE
            if len(parts) >= 5 and 'lladdr' in line:
                mac = parts[4].lower()
                state = parts[-1] # Lấy từ khóa cuối cùng (REACHABLE, STALE, FAILED...)
                
                # CHỈ CẬP NHẬT LastSeen NẾU THIẾT BỊ ĐANG THỰC SỰ SỐNG (REACHABLE hoặc DELAY)
                if state in ['REACHABLE', 'DELAY']:
                    active_macs.add(mac)
    except Exception as e:
        print("[-] Lỗi khi quét ARP:", e)
        
    return active_macs

def scan_and_update_devices():
    """Cập nhật DB với logic mới: Chỉ update LastSeen nếu thực sự có mặt"""
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
                    
                    # Truyền thêm trạng thái online vào hàm update
                    is_online = mac in active_macs
                    update_device_in_db(mac, ip, hostname, is_online)
    except FileNotFoundError:
        print("[-] Chưa tìm thấy file leases.")
        
    return get_all_devices_from_db()

def update_device_in_db(mac, ip, hostname, is_online):
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM Devices WHERE MacAddress = ?", (mac,))
    device = cursor.fetchone()
    
    if device is None:
        # Máy mới hoàn toàn
        cursor.execute('''
            INSERT INTO Devices (MacAddress, IpAddress, OriginalName, CustomName, IsBlocked)
            VALUES (?, ?, ?, ?, 0)
        ''', (mac, ip, hostname, hostname))
    else:
        # Nếu thiết bị ĐANG ONLINE (nằm trong ARP), thì mới cập nhật LastSeen
        if is_online:
            cursor.execute('''
                UPDATE Devices 
                SET IpAddress = ?, OriginalName = ?, LastSeen = datetime('now', 'localtime')
                WHERE MacAddress = ?
            ''', (ip, hostname, mac))
        else:
            # Nếu thiết bị KHÔNG ONLINE, chỉ cập nhật lại IP/Tên lỡ có đổi, GIỮ NGUYÊN LastSeen cũ
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

    # --- PHẦN NÂNG CẤP ---
    # Quét lại mạng lần nữa để biết chính xác ai đang online ngay lúc này
    active_macs = get_active_macs_from_arp()
    
    # Bơm thêm cờ IsOnline vào từng thiết bị trước khi gửi lên Web
    for device in devices:
        device['IsOnline'] = device['MacAddress'] in active_macs
        
    return devices