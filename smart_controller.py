import os
import re
import subprocess

LEASE_FILE = "/var/lib/misc/dnsmasq.leases"
MAC_PATTERN = re.compile(r"^[0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5}$")


def is_valid_mac(mac_address):
    return bool(MAC_PATTERN.match(str(mac_address).strip()))

def get_connected_devices():
    devices = []
    try:
        with open(LEASE_FILE, 'r') as f:
            lines = f.readlines()
            for line in lines:
                parts = line.split()
                if len(parts) >= 4:
                    devices.append({
                        "mac": parts[1],
                        "ip": parts[2],
                        "name": parts[3]
                    })
    except FileNotFoundError:
        print("[-] Không tìm thấy file leases. Hệ thống chưa cấp IP cho máy nào.")
    return devices

def show_devices(devices):
    """Hàm này in danh sách ra màn hình cho đẹp"""
    print("\n" + "="*60)
    print(f"{'STT':<5} | {'IP ADDRESS':<15} | {'MAC ADDRESS':<17} | {'HOSTNAME'}")
    print("-" * 60)
    if not devices:
        print("Chưa có thiết bị nào đang kết nối.")
    else:
        for i, dev in enumerate(devices):
            print(f"{i+1:<5} | {dev['ip']:<15} | {dev['mac']:<17} | {dev['name']}")
    print("="*60 + "\n")

def block_mac(mac_address):
    if not is_valid_mac(mac_address):
        print("[-] MAC không hợp lệ, không thể chặn.")
        return
    print(f"\n[*] Đang khóa mõm MAC: {mac_address}...")
    subprocess.run(["sudo", "iptables", "-I", "FORWARD", "-m", "mac", "--mac-source", mac_address, "-j", "DROP"], check=False)
    print("[+] Đã khóa thành công! Thiết bị đã rớt Internet.")

def unblock_mac(mac_address):
    if not is_valid_mac(mac_address):
        print("[-] MAC không hợp lệ, không thể mở khóa.")
        return
    print(f"\n[*] Đang mở khóa cho MAC: {mac_address}...")
    subprocess.run(["sudo", "iptables", "-D", "FORWARD", "-m", "mac", "--mac-source", mac_address, "-j", "DROP"], check=False)
    print("[+] Đã mở khóa! Mạng đã thông suốt.")

def main():
    while True:
        print("1. Xem danh sách thiết bị đang kết nối")
        print("2. CHẶN thiết bị (Click đúp để chặn)")
        print("3. MỞ KHÓA thiết bị")
        print("4. Xem danh sách các máy đang bị giam")
        print("5. Thoát")

        choice = input("Chọn chức năng (1-5): ")

        if choice == '1':
            devs = get_connected_devices()
            show_devices(devs)

        elif choice == '2':
            devs = get_connected_devices()
            show_devices(devs)
            if devs:
                try:
                    # Chỉ cần gõ Số Thứ Tự, không cần gõ MAC
                    idx = int(input("Nhập Số Thứ Tự (STT) của thiết bị muốn CHẶN (gõ 0 để hủy): "))
                    if 1 <= idx <= len(devs):
                        target_mac = devs[idx-1]['mac']
                        block_mac(target_mac)
                    elif idx != 0:
                        print("Số STT không hợp lệ!")
                except ValueError:
                    print("Lỗi: Vui lòng nhập một con số!")

        elif choice == '3':
            print("\n--- DANH SÁCH CÁC THIẾT BỊ ĐANG BỊ KHÓA ---")
            result = subprocess.run(['sudo', 'iptables', '-L', 'FORWARD', '-n', '-v', '--line-numbers'], capture_output=True, text=True, check=False)

            blocked_macs = []
            lines = result.stdout.split('\n')
            for line in lines:
                if 'MAC' in line:
                    # Bóc tách dòng để lấy Số thứ tự và Địa chỉ MAC
                    parts = line.split()
                    line_num = parts[0]
                    mac_match = re.search(r'([0-9a-fA-F]{2}(:[0-9a-fA-F]{2}){5})', line)
                    if mac_match:
                        mac_addr = mac_match.group(1)
                        blocked_macs.append({'line': line_num, 'mac': mac_addr})
                        print(f"[{len(blocked_macs)}] Đang khóa MAC: {mac_addr} (Luật số {line_num})")

            if not blocked_macs:
                print("Hiện tại không có thiết bị nào bị khóa!")
                continue

            try:
                idx = int(input("⚠️ Nhập Số thứ tự [ ] ở trên để MỞ KHÓA (hoặc gõ 0 để hủy): "))
                if 1 <= idx <= len(blocked_macs):
                    target_mac = blocked_macs[idx-1]['mac']
                    unblock_mac(target_mac)
                elif idx != 0:
                    print("Số không hợp lệ!")
            except ValueError:
                print("Vui lòng nhập số!")

        elif choice == '4':
            print("\nDANH SÁCH ĐANG BỊ CHẶN TRONG TƯỜNG LỬA")
            os.system("sudo iptables -L FORWARD -v -n --line-numbers")

        elif choice == '5':
            print("Đã tắt hệ thống điều khiển.")
            break
        else:
            print("Lựa chọn không hợp lệ, vui lòng chọn từ 1 đến 5!")


if __name__ == "__main__":
    main()
