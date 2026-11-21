#!/usr/bin/env bash
set -euo pipefail

systemctl stop 15m-runtime.service 2>/dev/null || true
systemctl stop 15m-network-server.service 2>/dev/null || true
/opt/15m-lab/toolbox/network_server.sh teardown
/opt/15m-lab/toolbox/network_client.sh teardown
pkill -x webserver_libc 2>/dev/null || true
pkill -x bound_server 2>/dev/null || true
pkill -x server 2>/dev/null || true
ip -6 route del local 2001:db8:1234:5678::/64 dev lo 2>/dev/null || true
sysctl -q -w net.ipv6.ip_nonlocal_bind=0 2>/dev/null || true

for group in /sys/fs/cgroup/15m-lab-*; do
  [[ -d "$group" ]] || continue
  if [[ -f "$group/cgroup.kill" ]]; then echo 1 > "$group/cgroup.kill"; fi
  for _ in $(seq 1 20); do
    rmdir "$group" 2>/dev/null && break
    sleep 0.05
  done
done
while read -r name _; do
  [[ "$name" == 15m-ports || "$name" == 15m-ports-* || "$name" == 15m-anyip-* ]] || continue
  ip netns del "$name" 2>/dev/null || true
done < <(ip netns list)

if [[ -d /var/lib/15m-lab/runs ]] && [[ -n "$(ls -A /var/lib/15m-lab/runs)" ]]; then
  mkdir -p /var/lib/15m-lab/archive
  mv /var/lib/15m-lab/runs "/var/lib/15m-lab/archive/reset-$(date +%s)"
fi
mkdir -p /var/lib/15m-lab/runs
rm -rf /var/lib/15m-lab/hints
printf 'LISTENERS=1000\n' > /etc/15m-lab/runtime.env
rm -f /tmp/15m-baseline.port
rm -f /tmp/15m-port.json
echo "Lab services and network state reset; prior reports are in /var/lib/15m-lab/archive."
