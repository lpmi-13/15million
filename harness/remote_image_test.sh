#!/usr/bin/env bash
# Run after a versioned rootfs image is pushed and a playground that boots it has started.
set -euo pipefail

run_id="${1:?usage: remote_image_test.sh PLAYGROUND_RUN_ID}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
report="$root/harness/reports/image-15m"
rootfs_image="${ROOTFS_IMAGE:-ghcr.io/lpmi-13/15million-rootfs:v9}"
image_id="$(docker image inspect "$rootfs_image" --format '{{.Id}}')"
image_digest="$(docker buildx imagetools inspect "$rootfs_image" --format '{{.Manifest.Digest}}')"
[[ "$image_digest" == sha256:* ]] || { echo "Could not resolve the pushed image digest." >&2; exit 1; }
mkdir -p "$report"

server() { labctl ssh "$run_id" -m dev-01 -u root -- "$@"; }
client() { labctl ssh "$run_id" -m client-01 -u root -- "$@"; }
learner() { labctl ssh "$run_id" -m dev-01 -u laborant -- "$@"; }
edit() { learner bash /tmp/15m-learner-edits.sh "$1"; }
cleanup() { learner sudo /opt/15m-lab/toolbox/runtime.sh stop >/dev/null 2>&1 || true; }
trap cleanup EXIT

labctl cp -m dev-01 -u laborant "$root/harness/apply_learner_edits.sh" \
  "$run_id:/tmp/15m-learner-edits.sh"

server /opt/15m-lab/tasks/wait_ready.sh server
client /opt/15m-lab/tasks/wait_ready.sh client
if server python3 /opt/15m-lab/tasks/verify_baseline.py >/dev/null 2>&1; then
  echo "baseline grader unexpectedly passed before startup" >&2; exit 1
fi
if server python3 /opt/15m-lab/tasks/verify_indexed.py >/dev/null 2>&1; then
  echo "indexed grader unexpectedly passed before editing" >&2; exit 1
fi
if server python3 /opt/15m-lab/tasks/verify_rust.py >/dev/null 2>&1; then
  echo "Rust grader unexpectedly passed before editing" >&2; exit 1
fi
for kind in port anyip process socket; do
  if server python3 /opt/15m-lab/tasks/verify_evidence.py "$kind" >/dev/null 2>&1; then
    echo "$kind grader unexpectedly passed before its probe" >&2; exit 1
  fi
done
if client python3 /opt/15m-lab/tasks/verify_runtime.py >/dev/null 2>&1; then
  echo "runtime grader unexpectedly passed before startup" >&2; exit 1
fi

learner 'cd ~/15m-work; cc -O2 -Wall -Wextra -Werror -std=c11 server.c -o server; ./server' && {
  echo "The C starter unexpectedly accepted connections" >&2; exit 1;
}
edit baseline
server systemd-run --unit baseline-image-test --uid laborant \
  --setenv PORT_FILE=/tmp/15m-baseline.port /home/laborant/15m-work/server
server python3 /opt/15m-lab/tasks/verify_baseline.py
server systemctl stop baseline-image-test

if learner 'cd ~/15m-work; for i in $(seq 1 15_000_000); do echo $i; ./server &; done'; then
  echo 'The literal article loop unexpectedly parsed in Bash.' >&2; exit 1
fi
if learner 'seq 1 15_000_000'; then
  echo 'The literal seq argument unexpectedly worked.' >&2; exit 1
fi
learner "cd ~/15m-work; sudo /opt/15m-lab/toolbox/bounded.sh article 'for ((i=1; i<=15000000; i++)); do echo \"\$i\"; ./server & done; wait'"
learner sudo ip netns add 15m-ports
learner sudo ip -n 15m-ports link set lo up
learner 'sudo ip netns exec 15m-ports /opt/15m-lab/baseline/bin/port_exhaust 15000000 > /tmp/15m-port.json 2>/tmp/15m-port.err; status=$?; jq -r .count /tmp/15m-port.json; printf "program exited with error %s\n" "$status"; test "$status" -eq 1'
learner sudo ip netns del 15m-ports
server python3 /opt/15m-lab/tasks/verify_evidence.py port
learner sudo ip -6 route add local 2001:db8:1234:5678::/64 dev lo
learner sudo sysctl -w net.ipv6.ip_nonlocal_bind=1
server systemd-run --unit 15m-image-alpha --uid laborant \
  /opt/15m-lab/baseline/bin/bound_server 2001:db8:1234:5678::1 8081 alpha
server systemd-run --unit 15m-image-beta --uid laborant \
  /opt/15m-lab/baseline/bin/bound_server 2001:db8:1234:5678::2 8081 beta
learner 'curl -fsS -g -6 --noproxy "*" "http://[2001:db8:1234:5678::1]:8081/"'
learner 'curl -fsS -g -6 --noproxy "*" "http://[2001:db8:1234:5678::2]:8081/"'
server python3 /opt/15m-lab/tasks/verify_evidence.py anyip
edit indexed
server systemd-run --unit 15m-image-index-1 --uid laborant /home/laborant/15m-work/server 1
server systemd-run --unit 15m-image-index-2 --uid laborant /home/laborant/15m-work/server 2
server python3 /opt/15m-lab/tasks/verify_indexed.py
server systemctl stop 15m-image-index-1 15m-image-index-2
if learner 'cd ~/15m-work; for i in $(seq 1 15_000_000); do echo $i; ./server $i &; done'; then
  echo 'The literal indexed article loop unexpectedly parsed in Bash.' >&2; exit 1
fi
learner "cd ~/15m-work; sudo /opt/15m-lab/toolbox/bounded.sh process 'for ((i=1; i<=15000000; i++)); do echo \"\$i\"; ./server \"\$i\" & done; wait'"
server python3 /opt/15m-lab/tasks/verify_evidence.py process
learner 'cd ~/15m-work; rustc context.rs -o context; ./context' && {
  echo "The Rust starter unexpectedly passed its assertions" >&2; exit 1;
}
edit rust
learner 'cd ~/15m-work; ./context'
server python3 /opt/15m-lab/tasks/verify_rust.py
learner "cd ~/15m-lab/baseline/bin; sudo /opt/15m-lab/toolbox/bounded.sh socket './socket_cost 10000000'"
server python3 /opt/15m-lab/tasks/verify_evidence.py socket

learner sudo /opt/15m-lab/toolbox/runtime.sh start 1000
server python3 /opt/15m-lab/toolbox/wait_runtime.py --count 1000
client python3 /opt/15m-lab/toolbox/probe_client.py --count 1000 --check-outside
if client python3 /opt/15m-lab/tasks/verify_runtime.py >/dev/null 2>&1; then
  echo "runtime grader unexpectedly passed with only 1000 listeners" >&2; exit 1
fi

learner sudo /opt/15m-lab/toolbox/runtime.sh start 15000000
server python3 /opt/15m-lab/toolbox/wait_runtime.py --count 15000000
client python3 /opt/15m-lab/tasks/verify_runtime.py \
  --output /var/lib/15m-lab/runs/image-15m/client.json
labctl cp -m client-01 -u root "$root/harness/concurrency_probe.py" \
  "$run_id:/tmp/concurrency_probe.py"
client python3 /tmp/concurrency_probe.py \
  --output /var/lib/15m-lab/runs/image-15m/concurrency.json
server python3 /opt/15m-lab/toolbox/status.py \
  --output /var/lib/15m-lab/runs/image-15m/server.json

labctl cp -m dev-01 -u root \
  "$run_id:/var/lib/15m-lab/runs/image-15m/server.json" "$report/server.json"
labctl cp -m client-01 -u root \
  "$run_id:/var/lib/15m-lab/runs/image-15m/client.json" "$report/client.json"
labctl cp -m client-01 -u root \
  "$run_id:/var/lib/15m-lab/runs/image-15m/concurrency.json" "$report/concurrency.json"
python3 "$root/harness/check_release.py" --dir "$report"
python3 - "$report" "$rootfs_image" "$image_id" "$image_digest" "$run_id" <<'PY'
import json
import sys
from pathlib import Path

report, image_ref, image_id, image_digest, playground_id = sys.argv[1:]
server = json.loads((Path(report) / "server.json").read_text())
(Path(report) / "image-meta.json").write_text(json.dumps({
    "image_ref": image_ref,
    "image_id": image_id,
    "image_digest": image_digest,
    "runtime_sha256": server["cgroup"]["exe_sha256"],
    "playground_id": playground_id,
}, indent=2, sort_keys=True) + "\n")
PY
echo "Exact-image run passed; reports saved in $report"
