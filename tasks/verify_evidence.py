#!/usr/bin/env python3
"""Validate recent reports created by root-owned bounded probe launchers."""

import json
import sys
import time
from pathlib import Path


RUNS = Path("/var/lib/15m-lab/runs")


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in {"port", "anyip", "process", "socket"}:
        raise SystemExit("usage: verify_evidence.py port|anyip|process|socket")
    kind = sys.argv[1]
    candidates = sorted(RUNS.glob(f"*/{kind}.json"), key=lambda path: path.stat().st_mtime,
                        reverse=True)
    if not candidates:
        raise RuntimeError(f"run the bounded {kind} experiment first")
    path = candidates[0]
    if path.stat().st_uid != 0:
        raise RuntimeError("report must be created by the root-owned probe")
    report = json.loads(path.read_text())
    if time.time() - report["unix_time"] > 2 * 60 * 60:
        raise RuntimeError("report is stale; rerun the experiment")
    if report.get("kind") != kind or report.get("schema") != 1 or not report.get("ok"):
        raise RuntimeError(f"{kind} experiment did not pass; inspect {path}")
    if kind == "port":
        probe = report["probe"]
        width = probe["range_high"] - probe["range_low"] + 1
        assert probe["errno"] == 98 and probe["failed_syscall"] == "listen"
        assert width - 64 <= probe["count"] <= width
        assert report["cgroup_limit"] <= 256 * 1024 * 1024
    elif kind == "anyip":
        assert report["route"] == "2001:db8:1234:5678::/64"
        assert report["replies"] == {"2001:db8:1234:5678::1": "alpha",
                                     "2001:db8:1234:5678::2": "beta"}
    elif kind == "process":
        assert report["events"]["oom_kill"] > 0
        assert report["cgroup_limit"] <= 64 * 1024 * 1024
        assert report["peak_live"] > 10 and report["bytes_per_process_estimate"] > 0
    else:
        assert report["events"]["oom_kill"] > 0
        assert report["max_observed_count"] > 1000
        assert report["bytes_per_socket_estimate"] > 128
        assert report["slab_peak_observed"] > 0
    print(f"Verified {kind} evidence from {path}: {json.dumps(report, sort_keys=True)}")


if __name__ == "__main__":
    main()
