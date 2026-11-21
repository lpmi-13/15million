#!/usr/bin/env bash
set -euo pipefail

role="${1:-server}"
[[ "$(uname -m)" == x86_64 ]] || { echo "This lab needs x86_64." >&2; exit 1; }
[[ "$(stat -fc %T /sys/fs/cgroup)" == cgroup2fs ]] || { echo "cgroup v2 is required." >&2; exit 1; }
[[ -c /dev/net/tun ]] || { echo "/dev/net/tun is unavailable." >&2; exit 1; }
ip addr show dev eth0 | grep -q '172\.16\.0\.' || { echo "Private lab NIC is missing." >&2; exit 1; }

if [[ "$role" == server ]]; then
  [[ -x /opt/15m-lab/bin/million-listeners ]] || { echo "Runtime binary is missing." >&2; exit 1; }
  [[ -x /opt/15m-lab/baseline/bin/webserver_libc ]] || { echo "C baseline is missing." >&2; exit 1; }
  for _ in $(seq 1 30); do
    systemctl is-active --quiet 15m-status-bridge.service && break
    sleep 1
  done
  systemctl is-active --quiet 15m-status-bridge.service || { echo "Status bridge is down." >&2; exit 1; }
elif [[ "$role" == client ]]; then
  /opt/15m-lab/toolbox/network_client.sh setup
  ip route get 10.0.0.1 | grep -q 'via 172\.16\.0\.2' || { echo "Client route is missing." >&2; exit 1; }
else
  echo "unknown role: $role" >&2
  exit 2
fi
echo "$role ready: x86_64, cgroup v2, TUN, private link"
