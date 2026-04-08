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
    mac_address = str(mac_address).strip().lower()
    if not is_valid_mac(mac_address):
        raise ValueError("Invalid MAC address")

    LOGGER.info("Blocking MAC: %s", mac_address)

    # Remove duplicate rule if it already exists, then add it back for consistent state.
    _run_iptables(["-D", "FORWARD", "-m", "mac", "--mac-source", mac_address, "-j", "DROP"], allow_fail=True)
    _run_iptables(["-I", "FORWARD", "-m", "mac", "--mac-source", mac_address, "-j", "DROP"])
    _update_block_status(mac_address, True)

def unblock_mac(mac_address):
    """Remove the block rule in iptables and update database state."""
    mac_address = str(mac_address).strip().lower()
    if not is_valid_mac(mac_address):
        raise ValueError("Invalid MAC address")

    LOGGER.info("Unblocking MAC: %s", mac_address)

    _run_iptables(["-D", "FORWARD", "-m", "mac", "--mac-source", mac_address, "-j", "DROP"], allow_fail=True)
    _update_block_status(mac_address, False)

def restore_firewall_rules():
    """Run once on startup to restore firewall rules from persisted blocked devices."""
    LOGGER.info("Restoring firewall rules from database")
    conn = database.get_db_connection()
    cursor = conn.cursor()
    
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


IP_PATTERN = re.compile(r"^(\d{1,3}\.){3}\d{1,3}(/\d{1,2})?$")
VALID_ACTIONS = ["-I", "-A", "-D"]
VALID_CHAINS = ["INPUT", "OUTPUT", "FORWARD"]
VALID_PROTOCOLS = ["tcp", "udp", "icmp", "all"]
VALID_TARGETS = ["DROP", "ACCEPT", "REJECT"]


def _is_valid_ip(ip):
    """Validate IP address format (supports CIDR notation)."""
    if not ip:
        return True
    return bool(IP_PATTERN.match(str(ip).strip()))


def _is_valid_port(port):
    """Validate port number (1-65535)."""
    if not port:
        return True
    try:
        p = int(port)
        return 1 <= p <= 65535
    except (ValueError, TypeError):
        return False


def apply_custom_rule(action="-I", chain="FORWARD", protocol=None, src_ip=None, dst_ip=None, sport=None, dport=None, target="DROP"):
    """
    Build a dynamic iptables command based on optional parameters.
    Includes validation to prevent command injection.
    """
    # Validate action
    if action not in VALID_ACTIONS:
        raise ValueError(f"Invalid action: {action}. Must be one of {VALID_ACTIONS}")
    
    # Validate chain
    if chain not in VALID_CHAINS:
        raise ValueError(f"Invalid chain: {chain}. Must be one of {VALID_CHAINS}")
    
    # Validate protocol
    if protocol and protocol.lower() not in VALID_PROTOCOLS:
        raise ValueError(f"Invalid protocol: {protocol}. Must be one of {VALID_PROTOCOLS}")
    
    # Validate target
    if target not in VALID_TARGETS:
        raise ValueError(f"Invalid target: {target}. Must be one of {VALID_TARGETS}")
    
    # Validate IP addresses
    if src_ip and not _is_valid_ip(src_ip):
        raise ValueError(f"Invalid source IP: {src_ip}")
    if dst_ip and not _is_valid_ip(dst_ip):
        raise ValueError(f"Invalid destination IP: {dst_ip}")
    
    # Validate ports
    if sport and not _is_valid_port(sport):
        raise ValueError(f"Invalid source port: {sport}")
    if dport and not _is_valid_port(dport):
        raise ValueError(f"Invalid destination port: {dport}")

    # Initialize base command: iptables -I FORWARD
    args = [action, chain]

    # If protocol is specified (tcp, udp, icmp)
    if protocol and protocol.lower() != 'all':
        args.extend(["-p", protocol.lower()])
        
        # Ports can only be used when protocol is tcp or udp
        if protocol.lower() in ['tcp', 'udp']:
            if sport: 
                args.extend(["--sport", str(int(sport))])
            if dport: 
                args.extend(["--dport", str(int(dport))])

    # Source and destination
    if src_ip:
        args.extend(["-s", src_ip.strip()])
    if dst_ip:
        args.extend(["-d", dst_ip.strip()])

    # Final action (DROP, ACCEPT, REJECT)
    args.extend(["-j", target])

    LOGGER.info("Executing Custom Rule: iptables %s", " ".join(args))
    
    # Call the existing iptables executor helper
    _run_iptables(args)