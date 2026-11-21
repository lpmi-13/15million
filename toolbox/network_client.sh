#!/usr/bin/env bash
set -euo pipefail

marker=/run/15m-client-route-created
route=10.0.0.0/8
gateway=172.16.0.2

case "${1:-}" in
  setup)
    existing="$(ip route show exact "$route")"
    if [[ -n "$existing" && "$existing" != *"via $gateway"* ]]; then
      echo "$route already has a different route: $existing" >&2
      exit 1
    fi
    if [[ -z "$existing" ]]; then
      ip route add "$route" via "$gateway"
      touch "$marker"
    fi
    ;;
  teardown)
    if [[ -f "$marker" ]]; then
      ip route del "$route" via "$gateway" 2>/dev/null || true
      rm -f "$marker"
    fi
    ;;
  *) echo "usage: network_client.sh setup|teardown" >&2; exit 2 ;;
esac
