#!/usr/bin/env python3
"""Validate recent reports created by root-owned bounded probe launchers."""

import argparse
import json
import time
from pathlib import Path

from grading import CheckFailed, add_hint_argument, run


RUNS = Path("/var/lib/15m-lab/runs")
MAX_AGE = 2 * 60 * 60
ANYIP_ROUTE = "2001:db8:1234:5678::/64"
ANYIP_REPLIES = {"2001:db8:1234:5678::1": "alpha", "2001:db8:1234:5678::2": "beta"}


def port_problem(report: dict) -> str | None:
    probe = report["probe"]
    width = probe["range_high"] - probe["range_low"] + 1
    if probe["failed_syscall"] != "listen" or probe["errno"] != 98:
        return (f"The probe stopped at {probe['failed_syscall']}() with errno "
                f"{probe['errno']}. Port exhaustion shows up as listen() with errno 98 "
                "(EADDRINUSE).")
    if not width - 64 <= probe["count"] <= width:
        return (f"The probe held {probe['count']} listeners, but the ephemeral range has "
                f"{width} ports.")
    if report["cgroup_limit"] > 256 * 1024 * 1024:
        return "The probe ran with a memory limit above 256 MiB."
    return None


def anyip_problem(report: dict) -> str | None:
    if report.get("server_errors"):
        first = report["server_errors"][0].strip().splitlines()
        return f"A bound server did not start: {first[-1] if first else 'no error output'}."
    if report.get("route") != ANYIP_ROUTE:
        return f"The probe used the route {report.get('route')!r}, expected {ANYIP_ROUTE}."
    if report.get("replies") != ANYIP_REPLIES:
        return f"The replies were {report.get('replies')!r}, expected alpha and beta."
    return None


def process_problem(report: dict) -> str | None:
    if report["events"].get("oom_kill", 0) <= 0:
        return "The probe cgroup recorded no OOM kill."
    if report["cgroup_limit"] > 64 * 1024 * 1024:
        return "The probe ran with a memory limit above 64 MiB."
    if report["peak_live"] <= 10 or report["bytes_per_process_estimate"] <= 0:
        return f"Only {report['peak_live']} processes were alive at the peak."
    return None


def socket_problem(report: dict) -> str | None:
    if report["events"].get("oom_kill", 0) <= 0:
        return "The probe cgroup recorded no OOM kill."
    if report["max_observed_count"] <= 1000:
        return f"The probe observed only {report['max_observed_count']} sockets."
    if report["bytes_per_socket_estimate"] <= 128 or report["slab_peak_observed"] <= 0:
        return "The report shows no measurable memory per socket."
    return None


PROBLEMS = {"port": port_problem, "anyip": anyip_problem,
            "process": process_problem, "socket": socket_problem}


def check(kind: str) -> str:
    candidates = sorted(RUNS.glob(f"*/{kind}.json"), key=lambda path: path.stat().st_mtime,
                        reverse=True)
    if not candidates:
        raise CheckFailed(f"There is no {kind} report yet. Run the {kind} probe.")
    path = candidates[0]
    if path.stat().st_uid != 0:
        raise CheckFailed(f"{path} was not written by the root-owned probe.")
    try:
        report = json.loads(path.read_text())
    except ValueError:
        raise CheckFailed(f"{path} is not valid JSON. Run the {kind} probe again.") from None
    if report.get("kind") != kind or report.get("schema") != 1:
        raise CheckFailed(f"{path} is not a {kind} report.")
    if time.time() - report.get("unix_time", 0) > MAX_AGE:
        raise CheckFailed(f"The newest {kind} report is more than two hours old. "
                          f"Run the {kind} probe again.")
    try:
        problem = PROBLEMS[kind](report)
    except (KeyError, TypeError):
        problem = "The report is missing fields."
    if problem is None and not report.get("ok"):
        problem = "The probe did not reach the expected limit."
    if problem:
        raise CheckFailed(f"{problem} See {path}.")
    return f"Verified {kind} evidence from {path}: {json.dumps(report, sort_keys=True)}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=sorted(PROBLEMS))
    add_hint_argument(parser)
    args = parser.parse_args()
    run(lambda: check(args.kind), args.hint_file)


if __name__ == "__main__":
    main()
