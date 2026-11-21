#!/usr/bin/env python3
"""Check captured full-run evidence before any playground publication."""

import argparse
import json
from pathlib import Path


def require(test: bool, message: str) -> None:
    if not test:
        raise SystemExit(f"release evidence failed: {message}")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", type=Path, default=Path(__file__).resolve().parent /
                        "reports/release-15m")
    args = parser.parse_args()
    server = json.loads((args.dir / "server.json").read_text())
    client = json.loads((args.dir / "client.json").read_text())
    concurrency = json.loads((args.dir / "concurrency.json").read_text())
    require(server["backend"] == "tun" and server["ready"], "live TUN status")
    require(server["requested"] == server["initialized"] == 15_000_000, "listener count")
    require(server["base"] == "10.0.0.1" and server["last"] == "10.228.225.192", "bounds")
    require(server["task_bytes"] == 16 and server["listener_bytes"] == 24, "resident layout")
    group = server["cgroup"]
    require(group["exe"] == "/opt/15m-lab/bin/million-listeners", "runtime executable")
    require(group["path"].endswith("/15m-runtime.service"), "protected service")
    require(int(group["memory_max"]) <= 9 * 1024 ** 3, "memory ceiling")
    require(int(group["memory_peak"]) < int(group["memory_max"]), "cgroup peak")
    require(int(group["vm_mem_available_kib"]) >= 512 * 1024, "VM headroom")
    events = dict(line.split() for line in group["memory_events"].splitlines())
    require(int(events.get("oom", "0")) == int(events.get("oom_kill", "0")) == 0, "OOM events")

    require(client["ok"] and client["count"] == 15_000_000, "client grader")
    require(client["before"]["pid"] == client["after"]["pid"] == server["pid"], "stable PID")
    require(client["after"]["accepted"] - client["before"]["accepted"] >= len(client["sample"]),
            "accepted-flow counter")
    sampled = {item["ip"]: item["body"] for item in client["sample"]}
    for ip, body in (("10.0.0.1", "1"), ("10.114.112.224", "7500000"),
                     ("10.228.225.192", "15000000")):
        require(sampled.get(ip) == body, f"HTTP at {ip}")
    require(client["outside"]["ip"] == "10.228.225.193" and
            "error" in client["outside"], "outside-range probe")
    require(concurrency["ok"] and len(concurrency["results"]) == 12, "concurrency")
    require(sum(item["index"] == 0 for item in concurrency["results"]) >= 4,
            "same-address overlap")
    print(f"release evidence passed: 15,000,000 listeners, peak {group['memory_peak']} bytes")


if __name__ == "__main__":
    main()
