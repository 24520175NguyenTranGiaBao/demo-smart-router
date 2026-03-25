import logging
import re
import shutil
import subprocess

from core import database


LOGGER = logging.getLogger(__name__)
MAC_PATTERN = re.compile(r"^[0-9a-f]{2}(:[0-9a-f]{2}){5}$")


def is_valid_mac(mac_address):
    return bool(MAC_PATTERN.match(str(mac_address).strip().lower()))


def _iptables_binary():
    return shutil.which("iptables") or "/sbin/iptables"


def _run_iptables(args, allow_fail=False):
    try:
        result = subprocess.run(
            [_iptables_binary(), *args],
            check=not allow_fail,
            capture_output=True,
            text=True,
        )
        if result.stderr:
            LOGGER.debug("iptables stderr: %s", result.stderr.strip())
    except subprocess.CalledProcessError as exc:
        LOGGER.error("iptables command failed: %s", " ".join(args))
        raise RuntimeError(exc.stderr.strip() or "iptables execution failed") from exc


def _update_block_status(mac_address, is_blocked):
    conn = database.get_db_connection()
    cursor = conn.cursor()
    cursor.execute("UPDATE Devices SET IsBlocked = ? WHERE MacAddress = ?", (1 if is_blocked else 0, mac_address))
    conn.commit()
    conn.close()

def block_mac(mac_address):
    """Đẩy luật chặn xuống Iptables và ghi vào Database"""
    mac_address = str(mac_address).strip().lower()
    if not is_valid_mac(mac_address):
        raise ValueError("Invalid MAC address")

    LOGGER.info("Blocking MAC: %s", mac_address)

    # Xoa rule trung lap neu da ton tai roi them lai de dam bao trang thai.
    _run_iptables(["-D", "FORWARD", "-m", "mac", "--mac-source", mac_address, "-j", "DROP"], allow_fail=True)
    _run_iptables(["-I", "FORWARD", "-m", "mac", "--mac-source", mac_address, "-j", "DROP"])
    _update_block_status(mac_address, True)

def unblock_mac(mac_address):
    """Xóa luật chặn trong Iptables và cập nhật Database"""
    mac_address = str(mac_address).strip().lower()
    if not is_valid_mac(mac_address):
        raise ValueError("Invalid MAC address")

    LOGGER.info("Unblocking MAC: %s", mac_address)

    _run_iptables(["-D", "FORWARD", "-m", "mac", "--mac-source", mac_address, "-j", "DROP"], allow_fail=True)
    _update_block_status(mac_address, False)

def restore_firewall_rules():
    """Hàm chạy 1 lần lúc bật Router để khôi phục luật chặn bị mất do cúp điện"""
    LOGGER.info("Restoring firewall rules from database")
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
    # Tìm tất cả các máy đang có án phạt (IsBlocked = 1)
    cursor.execute("SELECT MacAddress FROM Devices WHERE IsBlocked = 1")
    blocked_devices = cursor.fetchall()
    conn.close()
    
    for row in blocked_devices:
        mac = row["MacAddress"]
        if not is_valid_mac(mac):
            LOGGER.warning("Skip invalid MAC in DB: %s", mac)
            continue

        _run_iptables(["-D", "FORWARD", "-m", "mac", "--mac-source", mac, "-j", "DROP"], allow_fail=True)
        _run_iptables(["-I", "FORWARD", "-m", "mac", "--mac-source", mac, "-j", "DROP"])
        LOGGER.info("Restored block rule for MAC: %s", mac)