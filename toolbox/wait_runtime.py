#!/usr/bin/env python3
"""Wait for the live resident-listener count before issuing client probes."""

import argparse
import json
import time

from status import read_status


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, required=True)
    parser.add_argument("--timeout", type=int, default=120)
    args = parser.parse_args()
    deadline = time.monotonic() + args.timeout
    last = None
    while time.monotonic() < deadline:
        try:
            last = read_status("/run/15m-lab/status.sock")
            if last["ready"] and last["initialized"] == args.count:
                print(json.dumps(last, sort_keys=True))
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.5)
    raise SystemExit(f"runtime did not initialize {args.count} listeners; last status: {last}")


if __name__ == "__main__":
    main()
