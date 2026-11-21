#!/usr/bin/env bash
# Follow the tutorial's learner commands in a running tutorial session, then wait
# for every examiner task. Usage: tutorial_walkthrough.sh PLAY_ID
# Start a fresh session first: labctl tutorial start <name> --no-open --no-ssh --skip-wait-init
set -euo pipefail

play="${1:?usage: tutorial_walkthrough.sh PLAY_ID}"
# One labctl ssh call at a time, in the foreground (tunnel pool discipline).
server() { labctl ssh "$play" -m dev-01 -- "$@"; }
client() { labctl ssh "$play" -m client-01 -- "$@"; }
server_root() { labctl ssh "$play" -m dev-01 -u root -- "$@"; }

labctl playground tasks "$play" --kind init --wait --fail-fast --timeout 5m >/dev/null
echo "init tasks completed"

# Step 1. A backgrounded process keeps a labctl ssh session open, so the walkthrough
# starts the baseline as a transient unit owned by the learner user instead.
server_root systemd-run --unit 15m-walkthrough-baseline --uid laborant \
  --setenv PORT_FILE=/tmp/15m-baseline.port /opt/15m-lab/baseline/bin/webserver_libc
server 'for _ in $(seq 1 20); do [ -s /tmp/15m-baseline.port ] && break; sleep 0.5; done
  curl -fsS --noproxy "*" "http://127.0.0.1:$(cat /tmp/15m-baseline.port)/"; echo'

# Steps 2-5 use the same commands shown to the learner. The two AnyIP servers
# are transient units because a background process holds a labctl SSH tunnel.
server 'cd ~/15m-lab/baseline/bin; ./port_exhaust | tee /tmp/15m-port.json'
server sudo ip -6 route add local 2001:db8:1234:5678::/64 dev lo
server sudo sysctl -w net.ipv6.ip_nonlocal_bind=1
server_root systemd-run --unit 15m-walkthrough-alpha --uid laborant \
  /opt/15m-lab/baseline/bin/bound_server 2001:db8:1234:5678::1 8081 alpha
server_root systemd-run --unit 15m-walkthrough-beta --uid laborant \
  /opt/15m-lab/baseline/bin/bound_server 2001:db8:1234:5678::2 8081 beta
server 'curl -fsS -g -6 --noproxy "*" "http://[2001:db8:1234:5678::1]:8081/"'
server 'curl -fsS -g -6 --noproxy "*" "http://[2001:db8:1234:5678::2]:8081/"'
server "cd ~/15m-lab/baseline/bin; sudo /opt/15m-lab/toolbox/bounded.sh process 'for i in \$(seq 1 350); do echo \"\$i\"; ./server \"\$i\" & done; wait'"
server "cd ~/15m-lab/baseline/bin; sudo /opt/15m-lab/toolbox/bounded.sh socket './socket_cost 200000'"

# Step 6.
for count in 1000 100000 1000000 15000000; do
  server "sudo /opt/15m-lab/toolbox/runtime.sh start $count >/dev/null
    for _ in \$(seq 1 120); do
      sudo /opt/15m-lab/toolbox/runtime.sh status 2>/dev/null | grep -q '\"ready\": true' && exit 0
      systemctl is-active --quiet 15m-runtime.service || break
      sleep 1
    done
    journalctl -u 15m-runtime.service -n 20 --no-pager
    exit 1"
  case "$count" in
    1000) last=10.0.3.232 ;;
    100000) last=10.1.134.160 ;;
    1000000) last=10.15.66.64 ;;
    15000000) last=10.228.225.192 ;;
  esac
  client curl -fsS --noproxy '*' "http://10.0.0.1:8080/" >/dev/null
  client curl -fsS --noproxy '*' "http://$last:8080/" >/dev/null
  echo "$count listeners answered from client-01"
done
client 'for ip in 10.0.0.1 10.114.112.224 10.228.225.192; do
  curl -fsS --noproxy "*" "http://$ip:8080/"; echo; done'

labctl playground tasks "$play" --wait --fail-fast --timeout 5m
echo "Walkthrough passed: every task completed in $play"
