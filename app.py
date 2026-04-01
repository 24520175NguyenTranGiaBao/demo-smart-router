import logging

from flask import Flask, jsonify, request, render_template

from config import Config
from core import database, firewall, scanner


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    logging.basicConfig(
        level=getattr(logging, app.config["LOG_LEVEL"], logging.INFO),
        format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    )

    database.init_db()
    firewall.restore_firewall_rules()

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

    return app


app = create_app()


if __name__ == "__main__":
    print("Smart router backend is running")
    app.run(host=app.config["APP_HOST"], port=app.config["APP_PORT"], debug=app.config["DEBUG"])