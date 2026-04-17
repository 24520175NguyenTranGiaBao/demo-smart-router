import logging
import ipaddress
import os
import re
import shutil
import time
import subprocess
import threading
from flask import Flask, jsonify, request, render_template

from config import Config
from core import database, firewall, scanner

import firebase_admin
from firebase_admin import credentials
from firebase_admin import db

# ==========================================
# 1. KHỞI TẠO FIREBASE
# ==========================================
cred = credentials.Certificate("firebase-key.json")
firebase_admin.initialize_app(cred, {
    'databaseURL': 'https://nhom12-router-default-rtdb.firebaseio.com/'
})

print("[*] Đã kết nối thành công tới Firebase Cloud!")

# ==========================================
# 2. BIẾN TOÀN CỤC LƯU TRỮ BĂNG THÔNG
# ==========================================
node_stats = {} 
last_net_stats = {"rx": 0, "tx": 0, "time": time.time()}
SYNC_INTERVAL_SECONDS = 3
SYNC_ERROR_RETRY_SECONDS = 3
sync_now_event = threading.Event()

# ==========================================
# 3. CÁC HÀM XỬ LÝ FIREBASE NGẦM
# ==========================================
def sync_devices_to_firebase(devices_list):
    try:
        ref = db.reference('router_status/connected_devices')
        ref.set(devices_list)
    except Exception as e:
        print(f"[-] Lỗi đồng bộ Firebase: {e}")

def background_sync():
    print("[*] Luồng đồng bộ ngầm Firebase đã bắt đầu...")
    while True:
        wait_timeout = SYNC_INTERVAL_SECONDS
        try:
            device_list = scanner.scan_and_update_devices()
            sync_devices_to_firebase(device_list)
        except Exception as e:
            print(f"[!] Lỗi trong luồng đồng bộ ngầm: {e}")
            wait_timeout = SYNC_ERROR_RETRY_SECONDS

        # Wait for either next interval or a forced sync signal from state-changing APIs.
        sync_now_event.wait(timeout=wait_timeout)
        sync_now_event.clear()

# ==========================================
# 4. KHỞI TẠO ỨNG DỤNG FLASK
# ==========================================
def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    logging.basicConfig(
        level=getattr(logging, app.config["LOG_LEVEL"], logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    database.init_db()
    firewall.restore_firewall_rules()

    iptables_row_pattern = re.compile(
        r"^\s*(?P<packets>\d+)\s+(?P<bytes>\d+)\s+\S+\s+\S+\s+\S+\s+\S+\s+\S+\s+(?P<source>\S+)\s+(?P<destination>\S+)(?:\s+.*)?$"
    )

    def _build_subprocess_env():
        env = os.environ.copy()
        base_paths = ["/usr/sbin", "/sbin", "/usr/bin", "/bin"]
        current_path = env.get("PATH", "")
        env["PATH"] = ":".join(base_paths + ([current_path] if current_path else []))
        return env

    def _iptables_binary():
        candidates = [
            os.getenv("IPTABLES_BIN"),
            shutil.which("iptables"),
            "/usr/sbin/iptables",
            "/sbin/iptables",
        ]
        for candidate in candidates:
            if candidate and os.path.isfile(candidate) and os.access(candidate, os.X_OK):
                return candidate
        raise RuntimeError("Cannot find executable iptables binary.")

    def _run_iptables(args, check=True):
        binary = _iptables_binary()
        command = [binary, "-w", *args]
        result = subprocess.run(
            command, check=False, capture_output=True, text=True, env=_build_subprocess_env()
        )
        stderr_text = (result.stderr or "").strip()
        if result.returncode != 0 and check:
            raise RuntimeError(stderr_text or "iptables execution failed")
        return result

    def _normalize_rule_address(address):
        value = str(address).strip()
        try:
            if "/" in value:
                network = ipaddress.ip_network(value, strict=False)
                if network.num_addresses == 1:
                    return str(network.network_address)
                return value
            return str(ipaddress.ip_address(value))
        except ValueError:
            return value

    @app.route("/", methods=["GET"])
    def index():
        return render_template("index.html")
        
    @app.route("/api/health", methods=["GET"])
    def health_check():
        return jsonify({"status": "success", "message": "Smart router backend is healthy"})

    def request_immediate_firebase_sync():
        """Ask the background worker to run an immediate full scan + sync."""
        sync_now_event.set()

    @app.route("/api/block", methods=["POST"])
    def block_device():
        data = request.get_json(silent=True) or {}
        mac_to_block = str(data.get("mac", "")).strip().lower()
        if not mac_to_block or not firewall.is_valid_mac(mac_to_block):
            return jsonify({"status": "error", "message": "Invalid MAC address"}), 400
        firewall.block_mac(mac_to_block)
        request_immediate_firebase_sync()
        return jsonify({"status": "success", "message": f"Blocked MAC {mac_to_block}"})

    @app.route("/api/unblock", methods=["POST"])
    def unblock_device():
        data = request.get_json(silent=True) or {}
        mac_to_unblock = str(data.get("mac", "")).strip().lower()
        if not mac_to_unblock or not firewall.is_valid_mac(mac_to_unblock):
            return jsonify({"status": "error", "message": "Invalid MAC address"}), 400
        firewall.unblock_mac(mac_to_unblock)
        request_immediate_firebase_sync()
        return jsonify({"status": "success", "message": f"Unblocked {mac_to_unblock}"})

    @app.route('/api/custom_rule', methods=['POST'])
    def api_custom_rule():
        data = request.json
        try:
            firewall.apply_custom_rule(
                action=data.get('action', '-I'),
                chain=data.get('chain', 'FORWARD'),
                protocol=data.get('protocol'),
                src_ip=data.get('src_ip'),
                dst_ip=data.get('dst_ip'),
                sport=data.get('sport'),
                dport=data.get('dport'),
                target=data.get('target', 'DROP')
            )
            return jsonify({"status": "success", "message": "Firewall rule applied successfully!"})
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    def ensure_accounting_rules(ip):
        try:
            normalized_ip = str(ipaddress.ip_address(str(ip).strip()))
            for direction_flag, direction_label in (("-s", "upload"), ("-d", "download")):
                check_result = _run_iptables(["-C", "FORWARD", direction_flag, normalized_ip, "-j", "ACCEPT"], check=False)
                if check_result.returncode == 0:
                    continue
                _run_iptables(["-I", "FORWARD", "1", direction_flag, normalized_ip, "-j", "ACCEPT"], check=True)
        except Exception as e:
            app.logger.exception("Failed to ensure accounting rules for %s: %s", ip, e)
            raise

    @app.route('/api/stats')
    def get_node_stats():
        global node_stats
        target_ip = str(request.args.get('ip', '')).strip()

        if not target_ip:
            return jsonify({"status": "error", "message": "Missing IP parameter"}), 400

        try:
            target_ip = str(ipaddress.ip_address(target_ip))
            ensure_accounting_rules(target_ip)
            result = _run_iptables(["-xnvL", "FORWARD"], check=True)
            
            current_rx = 0
            current_tx = 0
            for line in result.stdout.splitlines():
                match = iptables_row_pattern.match(line)
                if not match: continue
                
                bytes_count = int(match.group("bytes"))
                src_ip = _normalize_rule_address(match.group("source"))
                dst_ip = _normalize_rule_address(match.group("destination"))

                if src_ip == target_ip: current_rx += bytes_count
                if dst_ip == target_ip: current_tx += bytes_count

            current_time = time.time()
            if target_ip not in node_stats:
                node_stats[target_ip] = {"rx": current_rx, "tx": current_tx, "time": current_time}
                return jsonify({
                    "status": "success", "client_upload_kbps": 0.0,
                    "client_download_kbps": 0.0, "timestamp": time.strftime('%H:%M:%S')
                })

            last = node_stats[target_ip]
            time_diff = current_time - last["time"]

            if time_diff > 0:
                rx_speed = max(0, current_rx - last["rx"]) / 1024 / time_diff
                tx_speed = max(0, current_tx - last["tx"]) / 1024 / time_diff
            else:
                rx_speed = tx_speed = 0

            node_stats[target_ip] = {"rx": current_rx, "tx": current_tx, "time": current_time}
            
            return jsonify({
                "status": "success",
                "client_upload_kbps": round(rx_speed, 2),
                "client_download_kbps": round(tx_speed, 2),
                "timestamp": time.strftime('%H:%M:%S')
            })
        except Exception as e:
            return jsonify({"status": "error", "message": str(e)}), 500

    return app

app = create_app()

if __name__ == "__main__":
    print("Smart router backend is running")
    
    # 5. KHỞI ĐỘNG LUỒNG CHẠY NGẦM ĐỒNG BỘ
    sync_thread = threading.Thread(target=background_sync, daemon=True)
    sync_thread.start()
    
    # 6. KHỞI ĐỘNG FLASK (Tắt Debug để không lỗi luồng ngầm)
    app.run(host=app.config["APP_HOST"], port=app.config["APP_PORT"], debug=False)