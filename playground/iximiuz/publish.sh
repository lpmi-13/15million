#!/usr/bin/env bash
# Builds and pushes the next rootfs image, sets its tag in manifest.yaml, and updates the
# registered playground. Modelled on rstudio-guide's iximiuz/publish-rootfs-image.sh.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
manifest="$root/playground/iximiuz/manifest.yaml"
image_repo="ghcr.io/lpmi-13/15million-rootfs"
repo_re="${image_repo//./\\.}"

usage() {
  cat <<'EOF'
Usage: playground/iximiuz/publish.sh [new-image-tag]
       playground/iximiuz/publish.sh --sync-remote

Builds and pushes the rootfs image, sets its tag in playground/iximiuz/manifest.yaml,
and updates the registered playground from that manifest. Without a tag, it publishes
the version after the one in manifest.yaml (v10 becomes v11).
--sync-remote retries only the playground update.
EOF
}

# Prints the tag of the single drive in manifest.yaml.
current_tag() {
  local sources tag
  mapfile -t sources < <(sed -nE 's#^[[:space:]]*- source: oci://([^[:space:]]+)[[:space:]]*$#\1#p' "$manifest")
  if [[ ${#sources[@]} -eq 1 ]]; then
    tag="${sources[0]##*:}"
    if [[ "${sources[0]}" == "$image_repo:$tag" ]]; then
      printf '%s\n' "$tag"
      return 0
    fi
  fi
  echo "error: $manifest must have one drive with a $image_repo:<tag> image." >&2
  return 1
}

next_image_tag() {
  if [[ ! "$1" =~ ^v([0-9]+)$ ]]; then
    echo "error: cannot increment the image tag '$1'. Pass a new tag explicitly." >&2
    return 1
  fi
  printf 'v%d\n' "$((10#${BASH_REMATCH[1]} + 1))"
}

set_manifest_tag() {
  sed -i -E "s#(- source: oci://)${repo_re}:[A-Za-z0-9_.-]+#\\1${image_repo}:$1#" "$manifest"
  [[ "$(current_tag)" == "$1" ]] || { echo "error: could not set $1 in $manifest." >&2; return 1; }
}

# Updates the registered playground from the checked-in manifest.
sync_remote_playground() {
  local name tag
  name="$(awk '/^name:/ { print $2; exit }' "$manifest")"
  [[ -n "$name" ]] || { echo "error: $manifest has no playground name." >&2; return 1; }
  tag="$(current_tag)"
  echo "Updating the playground $name to $image_repo:$tag..."
  if ! labctl playground update "$name" -f "$manifest"; then
    echo "error: the playground update failed. Retry with: playground/iximiuz/publish.sh --sync-remote" >&2
    return 1
  fi
}

if [[ "${1:-}" == -h || "${1:-}" == --help ]]; then
  usage
  exit 0
fi
if [[ $# -gt 1 || ( "${1:-}" == -* && "$1" != --sync-remote ) ]]; then
  usage >&2
  exit 2
fi
if ! labctl auth whoami >/dev/null 2>&1; then
  echo "error: labctl is not logged in. Run 'labctl auth login' first." >&2
  exit 1
fi

if [[ "${1:-}" == --sync-remote ]]; then
  sync_remote_playground
  exit 0
fi

old_tag="$(current_tag)"
if [[ $# -eq 1 ]]; then
  new_tag="$1"
else
  new_tag="$(next_image_tag "$old_tag")"
fi
[[ "$new_tag" =~ ^v[1-9][0-9]*$ ]] || { echo "error: '$new_tag' is not a versioned tag like v11." >&2; exit 2; }
[[ "$new_tag" != "$old_tag" ]] || { echo "error: $new_tag is already in use. Choose a new tag." >&2; exit 2; }
new_image="$image_repo:$new_tag"

echo "Publishing $new_tag (replacing $old_tag)..."
ROOTFS_IMAGE="$new_image" PUSH_IMAGE=1 bash "$root/playground/iximiuz/build-rootfs-image.sh"
echo "Setting $new_tag in $manifest..."
set_manifest_tag "$new_tag"
sync_remote_playground
echo "Published $new_image."
