#!/usr/bin/env python3
"""Final client-VM check: live process, cgroup budget, distinct TCP endpoints."""

import argparse
import ipaddress
import json
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from grading import CheckFailed, add_hint_argument, run

sys.path.insert(0, "/opt/15m-lab/toolbox")
from probe_client import atomic_json, request  # noqa: E402


COUNT = 15_000_000
BASE = int(ipaddress.IPv4Address("10.0.0.1"))
LAST = "10.228.225.192"
STATUS_URL = "http://172.16.0.2:9090/status"


def status() -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(STATUS_URL, timeout=4) as response:
            return json.load(response)
    except urllib.error.HTTPError:
        raise CheckFailed("The runtime on dev-01 is not running. Start it with runtime.sh "
                          "and wait until its status shows ready: true.") from None
    except OSError as error:
        raise CheckFailed(f"The status service on dev-01 ({STATUS_URL}) did not answer: "
                          f"{error}.") from None


def validate_status(data: dict) -> None:
    group = data["cgroup"]
    if data.get("requested") != COUNT:
        raise CheckFailed(f"The runtime was started with {data.get('requested'):,} listeners. "
                          f"The check needs {COUNT:,}.")
    if data.get("ready") is not True or data.get("initialized") != COUNT:
        raise CheckFailed(f"The runtime is still starting: {data.get('initialized', 0):,} of "
                          f"{COUNT:,} listeners are ready.")
    for key, expected in (("backend", "tun"), ("base", "10.0.0.1"), ("last", LAST),
                          ("port", 8080)):
        if data.get(key) != expected:
            raise CheckFailed(f"The runtime reports {key}={data.get(key)!r}, "
                              f"expected {expected!r}.")
    if group["exe"] != "/opt/15m-lab/bin/million-listeners":
        raise CheckFailed("The running process is not the root-owned runtime binary.")
    if not group["path"].endswith("/15m-runtime.service"):
        raise CheckFailed("The runtime is not running in its protected systemd unit.")
    events = dict(line.split() for line in group["memory_events"].splitlines())
    if int(events.get("oom", "0")) or int(events.get("oom_kill", "0")):
        raise CheckFailed("The runtime cgroup recorded an OOM event.")
    if int(group["memory_max"]) > 9 * 1024 ** 3:
        raise CheckFailed("The runtime memory ceiling is above 9 GiB.")
    if int(group["memory_peak"]) >= int(group["memory_max"]):
        raise CheckFailed("The runtime reached its memory ceiling.")
    if int(group["vm_mem_available_kib"]) < 512 * 1024:
        raise CheckFailed("dev-01 has less than 512 MiB of memory available. Stop other "
                          "memory-hungry processes and restart the runtime.")
    if int(group["vm_mem_total_kib"]) > 10 * 1024 * 1024:
        raise CheckFailed("dev-01 has more than the 10 GiB that this experiment allows.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path,
                        help="also save the full report as JSON (used by the test harness)")
    add_hint_argument(parser)
    args = parser.parse_args()
    results = []
    report = {"schema": 1, "count": COUNT, "sample": results, "ok": False,
              "unix_time": time.time()}

    def check() -> str:
        try:
            before = status()
            validate_status(before)
            points = {0, (COUNT - 1) // 2, COUNT - 1}
            points.update(random.Random(0x15_000_000).sample(range(COUNT), 5))
            sequence = sorted(points) + [0, COUNT - 1]
            for index in sequence:
                ip = str(ipaddress.IPv4Address(BASE + index))
                try:
                    code, body, latency = request(ip, 8080)
                except (OSError, ValueError) as error:
                    raise CheckFailed(f"{ip}:8080 did not answer HTTP: {error}.") from None
                if code != 200 or body != str(index + 1):
                    raise CheckFailed(f"{ip}:8080 returned HTTP {code} with body {body!r}, "
                                      f"expected {index + 1}.")
                results.append({"index": index, "ip": ip, "body": body,
                                "latency_ms": round(latency, 3)})
            outside = str(ipaddress.IPv4Address(BASE + COUNT))
            try:
                code, body, _ = request(outside, 8080, 1.0)
            except (OSError, ValueError) as error:
                report["outside"] = {"ip": outside, "error": str(error)}
            else:
                raise CheckFailed(f"{outside} is outside the range but answered HTTP {code}.")
            after = status()
            validate_status(after)
            if before["pid"] != after["pid"]:
                raise CheckFailed("The runtime PID changed during the check.")
            if after["accepted"] - before["accepted"] < len(sequence):
                raise CheckFailed("The runtime accepted-flow counter did not grow by one "
                                  "for every probe.")
            report.update({"ok": True, "before": before, "after": after})
            return json.dumps(report, sort_keys=True)
        except Exception as error:
            report["error"] = str(error)
            raise
        finally:
            if args.output:
                atomic_json(args.output, report)

    run(check, args.hint_file)


if __name__ == "__main__":
    main()
