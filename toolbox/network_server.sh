#!/usr/bin/env bash
set -euo pipefail

state=/run/15m-network
device=smolbench
route=10.0.0.0/8

setup() {
  mkdir -p "$state"
  existing="$(ip route show exact "$route")"
  if [[ -n "$existing" && "$existing" != *"dev $device"* ]]; then
    echo "$route already has a different route: $existing" >&2
    exit 1
  fi
  if ip link show dev "$device" >/dev/null 2>&1; then
    test -f "$state/tun-created" || { echo "$device already exists outside this lab" >&2; exit 1; }
  else
    ip tuntap add dev "$device" mode tun
    touch "$state/tun-created"
  fi
  ip link set dev "$device" up
  if [[ -z "$existing" ]]; then
    ip route add "$route" dev "$device"
    touch "$state/route-created"
  fi
  if [[ ! -f "$state/ip-forward-old" ]]; then
    cat /proc/sys/net/ipv4/ip_forward > "$state/ip-forward-old"
  fi
  if [[ ! -f "$state/rp-filter-old" ]]; then
    cat "/proc/sys/net/ipv4/conf/$device/rp_filter" > "$state/rp-filter-old"
  fi
  sysctl -q -w net.ipv4.ip_forward=1
  sysctl -q -w "net.ipv4.conf.$device.rp_filter=0"
}

teardown() {
  if [[ -f "$state/route-created" ]]; then
    ip route del "$route" dev "$device" 2>/dev/null || true
    rm -f "$state/route-created"
  fi
  if [[ -f "$state/ip-forward-old" ]]; then
    sysctl -q -w "net.ipv4.ip_forward=$(cat "$state/ip-forward-old")"
    rm -f "$state/ip-forward-old"
  fi
  if [[ -f "$state/rp-filter-old" ]]; then
    sysctl -q -w "net.ipv4.conf.$device.rp_filter=$(cat "$state/rp-filter-old")" 2>/dev/null || true
    rm -f "$state/rp-filter-old"
  fi
  if [[ -f "$state/tun-created" ]]; then
    ip tuntap del dev "$device" mode tun 2>/dev/null || true
    rm -f "$state/tun-created"
  fi
}

case "${1:-}" in
  setup) setup ;;
  teardown) teardown ;;
  *) echo "usage: network_server.sh setup|teardown" >&2; exit 2 ;;
esac
