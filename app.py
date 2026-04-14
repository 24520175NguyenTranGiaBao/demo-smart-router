import logging
import ipaddress
import os
import re
import shutil
import time
import subprocess
from flask import Flask, jsonify, request, render_template

from config import Config
from core import database, firewall, scanner

last_net_stats = {"rx": 0, "tx": 0, "time": time.time()}

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

        raise RuntimeError(
            "Cannot find executable iptables binary. Checked IPTABLES_BIN, PATH, /usr/sbin/iptables, /sbin/iptables"
        )

    def _run_iptables(args, check=True):
        binary = _iptables_binary()
        command = [binary, "-w", *args]
        result = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
            env=_build_subprocess_env(),
        )

        stderr_text = (result.stderr or "").strip()
        stdout_text = (result.stdout or "").strip()
        command_text = " ".join(command)

        if result.returncode != 0:
            app.logger.error(
                "iptables command failed (rc=%s): %s | stderr=%s | stdout=%s",
                result.returncode,
                command_text,
                stderr_text or "<empty>",
                stdout_text or "<empty>",
            )
            if check:
                raise RuntimeError(stderr_text or "iptables execution failed")
        elif stderr_text:
            app.logger.warning("iptables stderr for %s: %s", command_text, stderr_text)

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

    @app.route("/api/devices", methods=["GET"])
    def get_devices():
        device_list = scanner.scan_and_update_devices()
        return jsonify({"status": "success", "data": device_list})

    @app.route("/api/block", methods=["POST"])
    def block_device():
        data = request.get_json(silent=True) or {}
        mac_to_block = str(data.get("mac", "")).strip().lower()

        if not mac_to_block:
            return jsonify({"status": "error", "message": "Missing MAC address"}), 400
        if not firewall.is_valid_mac(mac_to_block):
            return jsonify({"status": "error", "message": "Invalid MAC address"}), 400

        firewall.block_mac(mac_to_block)
        return jsonify({"status": "success", "message": f"Blocked MAC {mac_to_block}"})

    @app.route("/api/unblock", methods=["POST"])
    def unblock_device():
        data = request.get_json(silent=True) or {}
        mac_to_unblock = str(data.get("mac", "")).strip().lower()

        if not mac_to_unblock:
            return jsonify({"status": "error", "message": "Missing MAC address"}), 400
        if not firewall.is_valid_mac(mac_to_unblock):
            return jsonify({"status": "error", "message": "Invalid MAC address"}), 400

        firewall.unblock_mac(mac_to_unblock)
        return jsonify({"status": "success", "message": f"Unblocked {mac_to_unblock}"})

    @app.errorhandler(404)
    def not_found(_):
        return jsonify({"status": "error", "message": "Endpoint not found"}), 404

    @app.errorhandler(500)
    def internal_error(_):
        return jsonify({"status": "error", "message": "Internal server error"}), 500

    @app.route('/api/custom_rule', methods=['POST'])
    def api_custom_rule():
        data = request.json
        try:
            # Extract data from JSON payload
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



    node_stats = {}
    def ensure_accounting_rules(ip):
        try:
            normalized_ip = str(ipaddress.ip_address(str(ip).strip()))

            for direction_flag, direction_label in (("-s", "upload"), ("-d", "download")):
                check_result = _run_iptables(
                    ["-C", "FORWARD", direction_flag, normalized_ip, "-j", "ACCEPT"],
                    check=False,
                )

                if check_result.returncode == 0:
                    app.logger.debug(
                        "Accounting rule already exists for %s (%s)",
                        direction_label,
                        normalized_ip,
                    )
                    continue

                if check_result.returncode != 1:
                    raise RuntimeError(
                        f"iptables check failed for {direction_label} {normalized_ip}: "
                        f"{(check_result.stderr or '').strip() or 'unknown error'}"
                    )

                app.logger.info(
                    "Adding accounting rule for %s (%s)",
                    direction_label,
                    normalized_ip,
                )
                _run_iptables(["-I", "FORWARD", "1", direction_flag, normalized_ip, "-j", "ACCEPT"], check=True)

        except Exception as e:
            app.logger.exception("Failed to ensure accounting rules for %s: %s", ip, e)
            raise

    @app.route('/api/stats')
    def get_node_stats():
        target_ip = str(request.args.get('ip', '')).strip()

        if not target_ip:
            return jsonify({"status": "error", "message": "Missing IP parameter"}), 400

        try:
            target_ip = str(ipaddress.ip_address(target_ip))
        except ValueError:
            return jsonify({"status": "error", "message": f"Invalid IP parameter: {target_ip}"}), 400

        try:
            ensure_accounting_rules(target_ip)

            result = _run_iptables(["-xnvL", "FORWARD"], check=True)

            current_rx = 0
            current_tx = 0

            for line in result.stdout.splitlines():
                match = iptables_row_pattern.match(line)
                if not match:
                    continue

                bytes_count = int(match.group("bytes"))
                src_ip = _normalize_rule_address(match.group("source"))
                dst_ip = _normalize_rule_address(match.group("destination"))

                if src_ip == target_ip:
                    current_rx += bytes_count
                if dst_ip == target_ip:
                    current_tx += bytes_count

            current_time = time.time()

            if target_ip not in node_stats:
                node_stats[target_ip] = {"rx": current_rx, "tx": current_tx, "time": current_time}
                app.logger.info(
                    "Initialized bandwidth baseline for %s (upload_bytes=%s, download_bytes=%s)",
                    target_ip,
                    current_rx,
                    current_tx,
                )
                return jsonify({
                    "status": "success",
                    "client_upload_kbps": 0.0,
                    "client_download_kbps": 0.0,
                    "timestamp": time.strftime('%H:%M:%S')
                })

            last = node_stats[target_ip]
            time_diff = current_time - last["time"]

            if time_diff > 0:
                rx_delta = max(0, current_rx - last["rx"])
                tx_delta = max(0, current_tx - last["tx"])
                rx_speed = rx_delta / 1024 / time_diff
                tx_speed = tx_delta / 1024 / time_diff
            else:
                rx_speed = tx_speed = 0

            node_stats[target_ip] = {"rx": current_rx, "tx": current_tx, "time": current_time}

            app.logger.info(
                "Bandwidth %s | Up: %.2f KB/s | Down: %.2f KB/s",
                target_ip,
                rx_speed,
                tx_speed,
            )

            return jsonify({
                "status": "success",
                "client_upload_kbps": round(rx_speed, 2),
                "client_download_kbps": round(tx_speed, 2),
                "timestamp": time.strftime('%H:%M:%S')
            })

        except Exception as e:
            app.logger.exception("Failed to fetch node stats for %s: %s", target_ip, e)
            return jsonify({"status": "error", "message": str(e)}), 500


    return app


app = create_app()


if __name__ == "__main__":
    print("Smart router backend is running")
    app.run(host=app.config["APP_HOST"], port=app.config["APP_PORT"], debug=app.config["DEBUG"])