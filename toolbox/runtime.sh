#!/usr/bin/env bash
set -euo pipefail

case "${1:-}" in
  start)
    count="${2:-}"
    [[ "$count" =~ ^[1-9][0-9]*$ && ${#count} -le 8 ]] || { echo "count must be a positive decimal integer up to 15000000" >&2; exit 2; }
    (( 10#$count <= 15000000 )) || { echo "count exceeds 15000000" >&2; exit 2; }
    printf 'LISTENERS=%s\n' "$count" > /etc/15m-lab/runtime.env
    systemctl restart 15m-runtime.service
    echo "Started $count listeners. Watch: journalctl -fu 15m-runtime.service"
    ;;
  stop) systemctl stop 15m-runtime.service ;;
  status) /usr/bin/python3 /opt/15m-lab/toolbox/status.py ;;
  *) echo "usage: runtime.sh start COUNT|stop|status" >&2; exit 2 ;;
esac
