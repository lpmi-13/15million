#!/usr/bin/env python3
"""Small active-flow check kept separate from idle-listener measurements."""

import ipaddress
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, "/opt/15m-lab/toolbox")
from probe_client import atomic_json, request  # noqa: E402


BASE = int(ipaddress.IPv4Address("10.0.0.1"))


def probe(index: int) -> dict:
    ip = str(ipaddress.IPv4Address(BASE + index))
    try:
        status, body, latency = request(ip, 8080, 5.0)
        return {"index": index, "ip": ip, "status": status, "body": body,
                "latency_ms": round(latency, 3), "ok": status == 200 and body == str(index + 1)}
    except (OSError, ValueError) as error:
        return {"index": index, "ip": ip, "error": str(error), "ok": False}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=15_000_000)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if args.count < 8:
        parser.error("count must be at least 8")
    # Eight clients to different listeners, then four overlapping clients to
    # the same listener. Both cases exercise active state and repeated accepts.
    indices = [index * ((args.count - 1) // 7) for index in range(8)] + [0] * 4
    with ThreadPoolExecutor(max_workers=12) as pool:
        results = [future.result() for future in as_completed(pool.submit(probe, i) for i in indices)]
    report = {"concurrency": 12, "results": results, "ok": all(item["ok"] for item in results)}
    if args.output:
        atomic_json(args.output, report)
    print(json.dumps(report, sort_keys=True))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
