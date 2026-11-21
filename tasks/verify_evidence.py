#!/usr/bin/env python3
"""Check the observations produced by the tutorial's direct commands."""

import argparse
import json
import subprocess
import time
from pathlib import Path

from grading import CheckFailed, add_hint_argument, run


RUNS = Path("/var/lib/15m-lab/runs")
MAX_AGE = 2 * 60 * 60


def recent(path: Path) -> None:
    if not path.exists():
        raise CheckFailed(f"{path} is missing. Run the command in the tutorial first.")
    if time.time() - path.stat().st_mtime > MAX_AGE:
        raise CheckFailed(f"{path} is more than two hours old. Run the command again.")


def port() -> str:
    path = Path("/tmp/15m-port.json")
    recent(path)
    try:
        probe = json.loads(path.read_text())
        width = probe["range_high"] - probe["range_low"] + 1
        if probe["failed_syscall"] != "listen" or probe["errno"] != 98:
            raise CheckFailed("The C loop must stop at listen() with EADDRINUSE (errno 98).")
        if not width - 64 <= probe["count"] <= width:
            raise CheckFailed("The listener count does not match the ephemeral port range.")
    except (ValueError, KeyError, TypeError) as error:
        raise CheckFailed(f"{path} is not a port_exhaust result ({error}).") from None
    return f"The C loop held {probe['count']} listeners before listen() returned EADDRINUSE."


def anyip() -> str:
    route = subprocess.run(
        ["ip", "-6", "route", "show", "table", "local", "2001:db8:1234:5678::/64"],
        capture_output=True, text=True, check=False)
    if "local 2001:db8:1234:5678::/64" not in route.stdout:
        raise CheckFailed("Add the local IPv6 route from the tutorial first.")
    for address, expected in (("2001:db8:1234:5678::1", "alpha"),
                              ("2001:db8:1234:5678::2", "beta")):
        reply = subprocess.run(
            ["curl", "-g", "-6", "--noproxy", "*", "-fsS", "--max-time", "3",
             f"http://[{address}]:8081/"], capture_output=True, text=True, check=False)
        if reply.returncode or reply.stdout != expected:
            raise CheckFailed(f"{address}:8081 did not answer {expected}. Start both C servers.")
    return "Both IPv6 addresses answered on port 8081."


def bounded(kind: str) -> str:
    candidates = sorted(RUNS.glob(f"*/{kind}.json"), key=lambda p: p.stat().st_mtime,
                        reverse=True)
    if not candidates:
        raise CheckFailed(f"Run the bounded {kind} command in the tutorial first.")
    path = candidates[0]
    recent(path)
    if path.stat().st_uid != 0:
        raise CheckFailed(f"{path} was not written by the root-owned cgroup wrapper.")
    try:
        report = json.loads(path.read_text())
        if report["schema"] != 1 or report["kind"] != kind:
            raise CheckFailed(f"{path} is not a {kind} report.")
        if report["events"]["oom_kill"] < 1 or not report["ok"]:
            raise CheckFailed("The bounded command did not cause a cgroup OOM kill.")
        if report["observed_count"] < (10 if kind == "process" else 1000):
            raise CheckFailed("The command stopped before it created enough entries.")
        if report["cgroup_limit"] != (32 if kind == "process" else 64) * 1024 * 1024:
            raise CheckFailed("The command did not use the tutorial's memory limit.")
        if kind == "socket" and report["slab_peak_observed"] <= 0:
            raise CheckFailed("The socket run has no kernel slab observation.")
    except (ValueError, KeyError, TypeError) as error:
        raise CheckFailed(f"{path} has an invalid report ({error}).") from None
    return (f"The {kind} command reached {report['observed_count']} entries and "
            f"triggered a cgroup OOM kill.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("kind", choices=("port", "anyip", "process", "socket"))
    add_hint_argument(parser)
    args = parser.parse_args()
    checks = {"port": port, "anyip": anyip,
              "process": lambda: bounded("process"),
              "socket": lambda: bounded("socket")}
    run(checks[args.kind], args.hint_file)


if __name__ == "__main__":
    main()
