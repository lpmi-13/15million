#!/usr/bin/env python3
"""Probe real TCP endpoints and verify each listener's destination-derived body."""

import argparse
import ipaddress
import json
import os
import random
import socket
import tempfile
import time
from pathlib import Path


def request(ip: str, port: int, timeout: float = 4.0) -> tuple[int, str, float]:
    started = time.monotonic()
    with socket.create_connection((ip, port), timeout=timeout) as connection:
        connection.settimeout(timeout)
        connection.sendall(b"GET / HTTP/1.0\r\nHost: lab\r\n\r\n")
        chunks = []
        while sum(map(len, chunks)) < 4096:
            data = connection.recv(4096)
            if not data:
                break
            chunks.append(data)
    wire = b"".join(chunks)
    head, separator, body = wire.partition(b"\r\n\r\n")
    if not separator:
        raise ValueError(f"no HTTP header from {ip}: {wire!r}")
    status = int(head.split(b" ", 2)[1])
    return status, body.decode("ascii"), (time.monotonic() - started) * 1000


def atomic_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", dir=path.parent, delete=False) as temporary:
        json.dump(data, temporary, indent=2, sort_keys=True)
        temporary.write("\n")
        name = temporary.name
    # NamedTemporaryFile creates 0600 files. Reports must stay readable by the learner.
    os.chmod(name, 0o644)
    os.replace(name, path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="10.0.0.1")
    parser.add_argument("--count", type=int, default=15_000_000)
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-outside", action="store_true")
    args = parser.parse_args()
    if not 1 <= args.count <= 15_000_000:
        parser.error("count must be between 1 and 15000000")
    base = int(ipaddress.IPv4Address(args.base))
    points = {0, (args.count - 1) // 2, args.count - 1}
    points.update(random.Random(0x15_000_000).sample(range(args.count), min(5, args.count)))
    # Recheck the boundaries after random probes to catch a failed runner.
    sequence = sorted(points) + [0, args.count - 1]
    results = []
    failed = False
    for index in sequence:
        ip = str(ipaddress.IPv4Address(base + index))
        try:
            status, body, latency = request(ip, args.port)
            good = status == 200 and body == str(index + 1)
            results.append({"index": index, "ip": ip, "status": status, "body": body,
                            "latency_ms": round(latency, 3), "ok": good})
            failed |= not good
        except (OSError, ValueError) as error:
            results.append({"index": index, "ip": ip, "error": str(error), "ok": False})
            failed = True
    outside = None
    if args.check_outside:
        ip = str(ipaddress.IPv4Address(base + args.count))
        try:
            status, body, _ = request(ip, args.port, 1.0)
            outside = {"ip": ip, "unexpected_status": status, "body": body, "ok": False}
            failed = True
        except (OSError, ValueError) as error:
            outside = {"ip": ip, "error": str(error), "ok": True}
    report = {"schema": 1, "base": args.base, "count": args.count, "port": args.port,
              "sample": results, "outside": outside, "ok": not failed,
              "unix_time": time.time()}
    if args.output:
        atomic_json(args.output, report)
    print(json.dumps(report, sort_keys=True))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
