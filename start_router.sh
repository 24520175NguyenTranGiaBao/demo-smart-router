#!/bin/bash

WAN_INTERFACE="wlan0"
LAN_INTERFACE="wlxc4e98405fe84"
ROUTER_IP="192.168.99.1"
PROJECT_DIR="/home/nhom12/demo-smart-router"

echo "[1] Configuring IP for Wi-Fi Access Point (LAN)"
ip addr flush dev $LAN_INTERFACE
ip link set $LAN_INTERFACE up
ip addr add $ROUTER_IP/24 dev $LAN_INTERFACE

echo "[2] Enabling routing and NAT"
sysctl -w net.ipv4.ip_forward=1
iptables -t nat -F
iptables -F
iptables -t nat -A POSTROUTING -o $WAN_INTERFACE -j MASQUERADE
iptables -A FORWARD -i $WAN_INTERFACE -o $LAN_INTERFACE -m state --state RELATED,ESTABLISHED -j ACCEPT
iptables -A FORWARD -i $LAN_INTERFACE -o $WAN_INTERFACE -j ACCEPT

echo "[3] Restarting Hostapd and Dnsmasq services"
systemctl restart hostapd
systemctl restart dnsmasq

echo "[4] Starting Web Dashboard"
systemctl restart sdn-dashboard
cd $PROJECT_DIR
python3 app.py


