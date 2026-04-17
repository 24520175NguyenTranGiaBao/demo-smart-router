# Smart Router Dashboard

A Flask-based dashboard for monitoring and controlling devices on a LAN/Wi-Fi router setup (designed for Linux/Raspberry Pi environments).

The project combines:

- Real-time device scanning from `dnsmasq` leases + ARP/hostapd signals
- Firewall control via `iptables` (block/unblock by MAC and custom rules)
- Realtime sync to Firebase Realtime Database
- Web dashboard (Bootstrap + Chart.js + Firebase client)

## Features

- Device inventory with online/offline state
- MAC-based blocking/unblocking
- Custom `iptables` rule editor from UI
- Per-client realtime traffic graph (`KB/s`)
- Automatic restoration of blocked devices on startup
- Background sync of connected device list to Firebase

## Tech Stack

- Backend: Python, Flask
- Database: SQLite (`router_data.db`)
- Firewall: Linux `iptables`
- Device scan signals: `ip neigh`, `arping`, `hostapd_cli`, `dnsmasq` leases
- Frontend: HTML, Bootstrap, JavaScript, Chart.js
- Cloud sync: Firebase Realtime Database (`firebase_admin` + Firebase JS SDK)

## Project Structure

```text
.
|-- app.py
|-- config.py
|-- requirements.txt
|-- start_router.sh
|-- wsgi.py
|-- core/
|   |-- database.py
|   |-- firewall.py
|   `-- scanner.py
|-- static/
|   |-- css/dashboard.css
|   `-- js/dashboard.js
`-- templates/
    `-- index.html
```

## Prerequisites

This project is intended for Linux hosts (especially Raspberry Pi acting as a router/AP).

Required system tools/services:

- `iptables`
- `ip` (iproute2)
- `arping`
- `iwconfig`
- `hostapd_cli`
- `dnsmasq` (leases file at `/var/lib/misc/dnsmasq.leases`)

Python:

- Python 3.10+ recommended

## Installation

1. Clone and enter the project directory.
2. Create and activate a virtual environment.
3. Install dependencies.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -U pip
pip install -r requirements.txt
pip install firebase-admin
```

Note: `firebase-admin` is required by `app.py` and should be installed even if not yet listed in `requirements.txt`.

## Configuration

### 1. Environment variables

Copy `.env.example` to `.env` and adjust values:

```env
APP_HOST=0.0.0.0
APP_PORT=5000
FLASK_DEBUG=false
LOG_LEVEL=INFO
```

### 2. Firebase service account

Place your Firebase service account key at:

```text
firebase-key.json
```

The app initializes Firebase Admin using this file and writes device data to:

```text
router_status/connected_devices
```

## Running the App

### Option A: Run Flask app directly

```bash
python3 app.py
```

Open:

```text
http://<APP_HOST>:<APP_PORT>/
```

### Option B: WSGI entrypoint

Use `wsgi.py` with your preferred WSGI server.

### Option C: Router bootstrap script (Linux router mode)

`start_router.sh` can:

- Configure LAN interface IP
- Enable IPv4 forwarding and NAT
- Restart `hostapd` and `dnsmasq`
- Start dashboard service/app

Run with root privileges:

```bash
sudo bash start_router.sh
```

Before running, review and update these variables in `start_router.sh`:

- `WAN_INTERFACE`
- `LAN_INTERFACE`
- `ROUTER_IP`
- `PROJECT_DIR`

## API Endpoints

### `GET /api/health`

Health check endpoint.

Response:

```json
{
  "status": "success",
  "message": "Smart router backend is healthy"
}
```

### `POST /api/block`

Block a device by MAC address.

Request body:

```json
{
  "mac": "aa:bb:cc:dd:ee:ff"
}
```

### `POST /api/unblock`

Unblock a device by MAC address.

Request body:

```json
{
  "mac": "aa:bb:cc:dd:ee:ff"
}
```

### `POST /api/custom_rule`

Apply a custom iptables rule.

Example request body:

```json
{
  "action": "-I",
  "chain": "FORWARD",
  "protocol": "tcp_udp",
  "src_ip": "192.168.99.10",
  "dst_ip": "8.8.8.8",
  "sport": null,
  "dport": "443",
  "target": "DROP"
}
```

Supported values:

- `action`: `-I`, `-A`, `-D`
- `chain`: `INPUT`, `OUTPUT`, `FORWARD`
- `protocol`: `tcp`, `udp`, `icmp`, `all`, `tcp_udp`
- `target`: `DROP`, `ACCEPT`, `REJECT`

### `GET /api/stats?ip=<client_ip>`

Returns realtime upload/download throughput (`KB/s`) for a selected client IP.

## Data Model

SQLite table: `Devices`

- `MacAddress` (PK)
- `IpAddress`
- `OriginalName`
- `CustomName`
- `IsBlocked`
- `LastSeen`

The DB is initialized automatically on app startup.

## How Device Online State Is Determined

The scanner combines multiple signals:

- ARP neighbor states (`ip neigh`)
- Wi-Fi association state (`hostapd_cli all_sta`)
- Active probe verification (`arping`)
- `dnsmasq` leases file entries

This reduces false positives and updates `LastSeen` only when a device is confirmed online.

## Security Notes

- Keep `firebase-key.json` private (already ignored by `.gitignore`).
- Running firewall/NAT operations usually requires root privileges.
- Validate custom rule inputs carefully in production deployments.

## Troubleshooting

- `Import "firebase_admin" could not be resolved`
  - Install with: `pip install firebase-admin`

- `Cannot find executable iptables binary`
  - Ensure `iptables` is installed and in PATH, or set `IPTABLES_BIN`.

- No devices appear on dashboard
  - Check `dnsmasq` leases path, ARP visibility, and AP interface status.

- Traffic chart remains zero
  - Verify `FORWARD` accounting rules can be inserted and traffic passes through router.

## Development Notes

- Main app entry: `app.py`
- WSGI entry: `wsgi.py`
- Frontend logic: `static/js/dashboard.js`
- Firewall engine: `core/firewall.py`
- Scanner engine: `core/scanner.py`

## License

No license file is currently provided in this repository.