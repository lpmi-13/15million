#!/usr/bin/env bash
# Publish only after a clean rootfs integration run and owner authorization.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
[[ "${CONFIRM_PUBLISH:-}" == 1 ]] || { echo "Set CONFIRM_PUBLISH=1 after approving publication." >&2; exit 2; }
[[ -n "${PLAYGROUND_NAME:-}" && -n "${CHALLENGE_NAME:-}" && -n "${ROOTFS_IMAGE:-}" ]] || {
  echo "Set PLAYGROUND_NAME, CHALLENGE_NAME and a versioned ROOTFS_IMAGE." >&2; exit 2;
}
[[ "$PLAYGROUND_NAME" =~ ^[a-z0-9][a-z0-9-]*$ && "$CHALLENGE_NAME" =~ ^[a-z0-9][a-z0-9-]*$ ]] || {
  echo "Registered names must be lowercase slugs." >&2; exit 2;
}
[[ "$ROOTFS_IMAGE" =~ ^ghcr\.io/[a-zA-Z0-9_.-]+/[a-zA-Z0-9_.-]+:v[1-9][0-9]*$ ]] || {
  echo "ROOTFS_IMAGE must be a versioned ghcr.io image." >&2; exit 2;
}
python3 "$root/harness/check_release.py"
python3 "$root/harness/check_release.py" --dir "$root/harness/reports/image-15m"
# The image must already have been pushed and tested in a fresh playground.
# Rebuilding here would make the test report refer to a different artifact.
tested_sha="$(python3 - "$root/harness/reports/image-15m/server.json" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1]))["cgroup"]["exe_sha256"])
PY
)"
registry_digest="$(docker buildx imagetools inspect "$ROOTFS_IMAGE" --format '{{.Manifest.Digest}}')"
python3 - "$root/harness/reports/image-15m/image-meta.json" "$ROOTFS_IMAGE" \
  "$(docker image inspect "$ROOTFS_IMAGE" --format '{{.Id}}')" "$registry_digest" "$tested_sha" <<'PY'
import json
import sys

meta = json.load(open(sys.argv[1]))
if (meta["image_ref"], meta["image_id"], meta["image_digest"], meta["runtime_sha256"]) != tuple(sys.argv[2:]):
    raise SystemExit("The rootfs image differs from the exact-image test report.")
PY
current_sha="$(docker run --rm --entrypoint sha256sum "$ROOTFS_IMAGE" \
  /opt/15m-lab/bin/million-listeners)"
current_sha="${current_sha%% *}"
[[ "$current_sha" == "$tested_sha" ]] || {
  echo "The local rootfs binary differs from the exact-image test report." >&2; exit 2;
}
stage="$(mktemp -d)"
trap 'rm -rf "$stage"' EXIT
python3 - "$root" "$stage" "$PLAYGROUND_NAME" "$ROOTFS_IMAGE" <<'PY'
from pathlib import Path
import re
import sys

root, stage, playground, image = sys.argv[1:]
root, stage = Path(root), Path(stage)
manifest = (root / "playground/iximiuz/manifest.yaml").read_text()
if not re.search(rf"(?m)^name: {re.escape(playground)}$", manifest):
    raise SystemExit("Local manifest does not name the registered playground.")
if manifest.count(f"oci://{image}") != 2:
    raise SystemExit("Local manifest must reference the tested image for both VMs.")
(stage / "manifest.yaml").write_text(manifest)
index = (root / "index.md").read_text()
if not re.search(rf"(?m)^  name: {re.escape(playground)}$", index):
    raise SystemExit("Local challenge does not reference the registered playground.")
(stage / "index.md").write_text(index)
(stage / "solution.md").write_text((root / "solution.md").read_text())
PY
labctl playground update "$PLAYGROUND_NAME" -f "$stage/manifest.yaml"
rm "$stage/manifest.yaml"
if [[ "${CONTENT_CREATE:-0}" == 1 ]]; then
  created_name="$(labctl content create challenge "$CHALLENGE_NAME" --dir "$stage" --no-open -q)"
  labctl content push challenge "$created_name" --dir "$stage" --force
  echo "Created challenge: $created_name"
else
  labctl content push challenge "$CHALLENGE_NAME" --dir "$stage" --force
fi
