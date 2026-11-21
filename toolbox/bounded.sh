#!/usr/bin/env bash
# Run a learner's Bash command in a small cgroup, then show the real OOM event.
set -euo pipefail

kind="${1:-}"
script="${2:-}"
case "$kind" in
  article) limit=$((32 * 1024 * 1024)); max_pids=400 ;;
  process) limit=$((32 * 1024 * 1024)); max_pids=400 ;;
  socket)  limit=$((64 * 1024 * 1024)); max_pids=8 ;;
  *) echo 'usage: bounded.sh {article|process|socket} BASH_COMMAND' >&2; exit 2 ;;
esac
[[ -n "$script" && "${3:-}" == '' && "${SUDO_USER:-}" == laborant ]] || exit 2

group="/sys/fs/cgroup/15m-lab-${kind}-$$"
run="/var/lib/15m-lab/runs/$(date +%s)-$$"
mkdir "$group" "$run"
cleanup() {
  if [[ -e "$group/cgroup.kill" ]]; then echo 1 > "$group/cgroup.kill" 2>/dev/null || true; fi
  for _ in {1..20}; do rmdir "$group" 2>/dev/null && break; sleep 0.05; done
}
trap cleanup EXIT
printf '%s\n' "$limit" > "$group/memory.max"
if [[ -e "$group/memory.swap.max" ]]; then echo 0 > "$group/memory.swap.max"; fi
printf '%s\n' "$max_pids" > "$group/pids.max"

# Only the fixed bootstrap runs as root in the cgroup. The supplied command
# runs as laborant, with the same working directory as the learner's shell.
/bin/bash -c 'echo $$ > "$1/cgroup.procs"; exec /usr/sbin/runuser -u laborant -- /usr/bin/timeout 45s /bin/bash -c "$2"' \
  _ "$group" "$script" > "$run/$kind.log" 2>&1 &
child=$!
slab_peak=0
for _ in {1..500}; do
  slab=$(awk '$1 == "slab" {print $2}' "$group/memory.stat")
  (( slab > slab_peak )) && slab_peak=$slab
  oom_kill=$(awk '$1 == "oom_kill" {print $2}' "$group/memory.events")
  if (( oom_kill > 0 )); then break; fi
  if ! kill -0 "$child" 2>/dev/null; then break; fi
  sleep 0.1
done
echo 1 > "$group/cgroup.kill" 2>/dev/null || true
wait "$child" 2>/dev/null || true

peak=$(cat "$group/memory.peak")
oom_kill=$(awk '$1 == "oom_kill" {print $2}' "$group/memory.events")
if [[ "$kind" == process || "$kind" == article ]]; then
  observed=$(awk '/^[0-9]+$/ {n=$1} END {print n+0}' "$run/$kind.log")
  requested=0
else
  observed=$(awk -F= '/^count=[0-9]+$/ {n=$2} END {print n+0}' "$run/$kind.log")
  requested=$(awk -F= '/^target=[0-9]+$/ {n=$2} END {print n+0}' "$run/$kind.log")
fi
jq -n --arg kind "$kind" --argjson now "$(date +%s)" \
  --argjson limit "$limit" --argjson peak "$peak" \
  --argjson oom "$oom_kill" --argjson observed "$observed" --argjson requested "$requested" \
  --argjson slab "$slab_peak" \
  '{schema: 1, kind: $kind, unix_time: $now, cgroup_limit: $limit,
    memory_peak: $peak, observed_count: $observed, requested_count: $requested,
    bytes_per_item_estimate: (if $observed > 0 then $peak / $observed else 0 end),
    slab_peak_observed: $slab, events: {oom_kill: $oom}, ok: ($oom > 0)}' \
  > "$run/$kind.json"
tail -n 8 "$run/$kind.log"
printf 'memory.peak=%s bytes; memory.events oom_kill=%s\n' "$peak" "$oom_kill"
if (( oom_kill > 0 )); then echo 'Out of memory'; else echo 'No OOM kill'; fi
echo "report=$run/$kind.json"
(( oom_kill > 0 ))
