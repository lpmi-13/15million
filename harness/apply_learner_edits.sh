#!/usr/bin/env bash
# Apply the tutorial's small source edits in an automated playground walkthrough.
set -euo pipefail

stage="${1:?usage: apply_learner_edits.sh baseline|indexed|rust}"
python3 - "$stage" <<'PY'
from pathlib import Path
import sys

stage = sys.argv[1]
work = Path.home() / "15m-work"
if stage == "baseline":
    path = work / "server.c"
    old = "// TODO (step 1): Call listen(server, 128) here and handle its error."
    new = 'if (listen(server, 128) < 0) { perror("listen"); return 1; }'
elif stage == "indexed":
    path = work / "server.c"
    old = "address.sin_addr.s_addr = htonl(0x7f000001u);"
    new = "address.sin_addr.s_addr = htonl(0x7f000001u + (uint32_t)index);"
elif stage == "rust":
    path = work / "context.rs"
    content = path.read_text()
    changes = (
        ("// TODO (step 5): Add fd_server and fd_client as i32 fields.",
         "fd_server: i32,\n    fd_client: i32,"),
        ("fn listener_address(_index: u32)", "fn listener_address(index: u32)"),
        ("Ipv4Addr::from(base)", "Ipv4Addr::from(base + index - 1)"),
    )
    for old, new in changes:
        if old not in content:
            raise SystemExit(f"missing starter text: {old}")
        content = content.replace(old, new, 1)
    path.write_text(content)
    raise SystemExit(0)
else:
    raise SystemExit(f"unknown stage: {stage}")

content = path.read_text()
if old not in content:
    raise SystemExit(f"missing starter text: {old}")
path.write_text(content.replace(old, new, 1))
PY

cd "$HOME/15m-work"
case "$stage" in
  baseline|indexed) cc -O2 -Wall -Wextra -Werror -std=c11 server.c -o server ;;
  rust) rustc context.rs -o context ;;
esac
