#!/usr/bin/env bash
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
image="${ROOTFS_IMAGE:-15million-rootfs:dev}"
docker build -f "$root/playground/iximiuz/Dockerfile" -t "$image" "$root"
if [[ "${PUSH_IMAGE:-0}" == 1 ]]; then
  docker push "$image"
fi
echo "Built $image"
