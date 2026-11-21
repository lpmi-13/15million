#!/usr/bin/env bash
set -euo pipefail

systemctl stop 15m-runtime.service 2>/dev/null || true
systemctl stop 15m-network-server.service 2>/dev/null || true
/opt/15m-lab/toolbox/network_server.sh teardown
/opt/15m-lab/toolbox/network_client.sh teardown
pkill -x webserver_libc 2>/dev/null || true

for group in /sys/fs/cgroup/15m-lab-*; do
  [[ -d "$group" ]] || continue
  if [[ -f "$group/cgroup.kill" ]]; then echo 1 > "$group/cgroup.kill"; fi
  for _ in $(seq 1 20); do
    rmdir "$group" 2>/dev/null && break
    sleep 0.05
  done
done
while read -r name _; do
  [[ "$name" == 15m-ports-* || "$name" == 15m-anyip-* ]] || continue
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
echo "Lab services and network state reset; prior reports are in /var/lib/15m-lab/archive."
