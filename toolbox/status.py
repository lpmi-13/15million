#!/usr/bin/env python3
"""Query the live runtime and its cgroup, then print a compact JSON snapshot."""

import argparse
import hashlib
import json
import os
import socket
import tempfile
from pathlib import Path


def read_status(path: str) -> dict:
    with socket.socket(socket.AF_UNIX) as connection:
        connection.settimeout(2)
        connection.connect(path)
        connection.sendall(b"status\n")
        chunks = []
        while data := connection.recv(4096):
            chunks.append(data)
    return json.loads(b"".join(chunks))


def cgroup_status(pid: int) -> dict:
    line = next((line for line in Path(f"/proc/{pid}/cgroup").read_text().splitlines()
                 if line.startswith("0::")), None)
    if line is None:
        raise RuntimeError("runtime is not in cgroup v2")
    path = Path("/sys/fs/cgroup") / line.partition("0::")[2].lstrip("/")
    values = {}
    for name in ("memory.current", "memory.peak", "memory.max", "memory.events"):
        values[name.replace(".", "_")] = (path / name).read_text().strip()
    meminfo = {parts[0].rstrip(":"): int(parts[1]) for line in
               Path("/proc/meminfo").read_text().splitlines() if (parts := line.split())}
    values["vm_mem_available_kib"] = meminfo["MemAvailable"]
    values["vm_mem_total_kib"] = meminfo["MemTotal"]
    values["path"] = str(path)
    exe = Path(f"/proc/{pid}/exe")
    values["exe"] = str(exe.resolve())
    with exe.open("rb") as binary:
        values["exe_sha256"] = hashlib.file_digest(binary, "sha256").hexdigest()
    rollup = Path(f"/proc/{pid}/smaps_rollup").read_text().splitlines()
    for name in ("Rss", "Pss"):
        values[name.lower() + "_bytes"] = next(int(line.split()[1]) * 1024 for line in rollup
                                               if line.startswith(name + ":"))
    return values


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", default="/run/15m-lab/status.sock")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    status = read_status(args.socket)
    status["cgroup"] = cgroup_status(status["pid"])
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", dir=args.output.parent, delete=False) as temporary:
            json.dump(status, temporary, indent=2, sort_keys=True)
            temporary.write("\n")
            name = temporary.name
        os.replace(name, args.output)
    print(json.dumps(status, sort_keys=True))


if __name__ == "__main__":
    main()
