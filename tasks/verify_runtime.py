#!/usr/bin/env python3
"""Final client-VM check: live process, cgroup budget, distinct TCP endpoints."""

import argparse
import ipaddress
import json
import random
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, "/opt/15m-lab/toolbox")
from probe_client import atomic_json, request  # noqa: E402


COUNT = 15_000_000
BASE = int(ipaddress.IPv4Address("10.0.0.1"))
LAST = "10.228.225.192"


def status() -> dict:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open("http://172.16.0.2:9090/status", timeout=4) as response:
        return json.load(response)


def validate_status(data: dict) -> None:
    for key, expected in (("backend", "tun"), ("base", "10.0.0.1"),
                          ("last", LAST), ("port", 8080), ("requested", COUNT),
                          ("initialized", COUNT), ("ready", True)):
        if data.get(key) != expected:
            raise RuntimeError(f"runtime {key}={data.get(key)!r}; expected {expected!r}")
    group = data["cgroup"]
    if group["exe"] != "/opt/15m-lab/bin/million-listeners":
        raise RuntimeError("the root-owned runtime binary is not running")
    if not group["path"].endswith("/15m-runtime.service"):
        raise RuntimeError("runtime is not in its protected systemd unit")
    events = dict(line.split() for line in group["memory_events"].splitlines())
    if int(events.get("oom", "0")) or int(events.get("oom_kill", "0")):
        raise RuntimeError("runtime cgroup recorded an OOM event")
    if int(group["memory_max"]) > 9 * 1024 ** 3:
        raise RuntimeError("runtime memory ceiling exceeds 9 GiB")
    if int(group["memory_peak"]) >= int(group["memory_max"]):
        raise RuntimeError("runtime hit its memory ceiling")
    if int(group["vm_mem_available_kib"]) < 512 * 1024:
        raise RuntimeError("server VM has less than 512 MiB available")
    if int(group["vm_mem_total_kib"]) > 10 * 1024 * 1024:
        raise RuntimeError("server VM exceeds the 10 GiB challenge budget")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("/var/lib/15m-lab/runs") /
                        f"grader-{int(time.time())}" / "final.json")
    args = parser.parse_args()
    results = []
    report = {"schema": 1, "count": COUNT, "sample": results, "ok": False,
              "unix_time": time.time()}
    try:
        before = status()
        validate_status(before)
        points = {0, (COUNT - 1) // 2, COUNT - 1}
        points.update(random.Random(0x15_000_000).sample(range(COUNT), 5))
        sequence = sorted(points) + [0, COUNT - 1]
        for index in sequence:
            ip = str(ipaddress.IPv4Address(BASE + index))
            code, body, latency = request(ip, 8080)
            if code != 200 or body != str(index + 1):
                raise RuntimeError(f"{ip} returned HTTP {code}, body {body!r}")
            results.append({"index": index, "ip": ip, "body": body,
                            "latency_ms": round(latency, 3)})
        outside = str(ipaddress.IPv4Address(BASE + COUNT))
        try:
            code, body, _ = request(outside, 8080, 1.0)
        except (OSError, ValueError) as error:
            report["outside"] = {"ip": outside, "error": str(error)}
        else:
            raise RuntimeError(f"outside address {outside} answered HTTP {code}: {body!r}")
        after = status()
        validate_status(after)
        if before["pid"] != after["pid"]:
            raise RuntimeError("runtime PID changed during client probes")
        if after["accepted"] - before["accepted"] < len(sequence):
            raise RuntimeError("runtime accepted-flow counter did not advance for every probe")
        report.update({"ok": True, "before": before, "after": after})
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        report["error"] = str(error)
    atomic_json(args.output, report)
    print(json.dumps(report, sort_keys=True))
    if not report["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
