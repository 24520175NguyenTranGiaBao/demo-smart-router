#!/bin/bash
# Wired LAN Router Script - Stable Setup
fuser -k 5000/tcp 2>/dev/null
WAN_INTERFACE="ens33"
# Replace "ens38" with your LAN network interface name
LAN_INTERFACE="ens37" 
ROUTER_IP="192.168.99.1"
PROJECT_DIR="/home/nguyentrangiabao-24520175/demo-smart-router"

echo "1. Configure IP for LAN interface..."
ip addr flush dev $LAN_INTERFACE
ip link set $LAN_INTERFACE up
ip addr add $ROUTER_IP/24 dev $LAN_INTERFACE

echo "2. Enable firewall forwarding and internet sharing (NAT)..."
sysctl -w net.ipv4.ip_forward=1
iptables -t nat -A POSTROUTING -o $WAN_INTERFACE -j MASQUERADE
iptables -P FORWARD ACCEPT

echo "3. Restart DHCP server to assign IPs to clients..."
systemctl restart dnsmasq

echo "4. Start Web Dashboard..."
cd $PROJECT_DIR
python3 app.py