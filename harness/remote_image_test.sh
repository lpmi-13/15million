#!/usr/bin/env bash
# Run after a versioned rootfs image is pushed and a playground that boots it has started.
set -euo pipefail

run_id="${1:?usage: remote_image_test.sh PLAYGROUND_RUN_ID}"
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
report="$root/harness/reports/image-15m"
rootfs_image="${ROOTFS_IMAGE:-ghcr.io/lpmi-13/15million-rootfs:v4}"
image_id="$(docker image inspect "$rootfs_image" --format '{{.Id}}')"
image_digest="$(docker buildx imagetools inspect "$rootfs_image" --format '{{.Manifest.Digest}}')"
[[ "$image_digest" == sha256:* ]] || { echo "Could not resolve the pushed image digest." >&2; exit 1; }
mkdir -p "$report"

server() { labctl ssh "$run_id" -m dev-01 -u root -- "$@"; }
client() { labctl ssh "$run_id" -m client-01 -u root -- "$@"; }
learner() { labctl ssh "$run_id" -m dev-01 -u laborant -- "$@"; }
cleanup() { learner sudo /opt/15m-lab/toolbox/runtime.sh stop >/dev/null 2>&1 || true; }
trap cleanup EXIT

server /opt/15m-lab/tasks/wait_ready.sh server
client /opt/15m-lab/tasks/wait_ready.sh client
if server python3 /opt/15m-lab/tasks/verify_baseline.py >/dev/null 2>&1; then
  echo "baseline grader unexpectedly passed before startup" >&2; exit 1
fi
for kind in port anyip process socket; do
  if server python3 /opt/15m-lab/tasks/verify_evidence.py "$kind" >/dev/null 2>&1; then
    echo "$kind grader unexpectedly passed before its probe" >&2; exit 1
  fi
done
if client python3 /opt/15m-lab/tasks/verify_runtime.py >/dev/null 2>&1; then
  echo "runtime grader unexpectedly passed before startup" >&2; exit 1
fi

server systemd-run --unit baseline-image-test --uid laborant \
  --setenv PORT_FILE=/tmp/15m-baseline.port /opt/15m-lab/baseline/bin/webserver_libc
server python3 /opt/15m-lab/tasks/verify_baseline.py
server systemctl stop baseline-image-test

for kind in port anyip process socket; do
  learner sudo python3 /opt/15m-lab/toolbox/experiment.py "$kind" --run-id "image-$kind"
  server python3 /opt/15m-lab/tasks/verify_evidence.py "$kind"
done

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
