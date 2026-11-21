#!/usr/bin/env python3
"""Check the learner's compiled Rust context and address calculation."""

import argparse
import subprocess
from pathlib import Path

from grading import CheckFailed, add_hint_argument, run


SOURCE = Path("/home/laborant/15m-work/context.rs")
PROGRAM = Path("/home/laborant/15m-work/context")
EXPECTED = [
    "context_bytes=16",
    "all_contexts_bytes=240000000",
    "1 -> 10.0.0.1",
    "7500000 -> 10.114.112.224",
    "15000000 -> 10.228.225.192",
]


def check() -> str:
    if not PROGRAM.exists() or PROGRAM.stat().st_mtime < SOURCE.stat().st_mtime:
        raise CheckFailed("Compile the edited ~/15m-work/context.rs with rustc first.")
    try:
        result = subprocess.run(["/usr/sbin/runuser", "-u", "laborant", "--", str(PROGRAM)],
                                capture_output=True, text=True, timeout=5,
                                check=False)
    except (OSError, subprocess.TimeoutExpired) as error:
        raise CheckFailed(f"The Rust program could not run ({error}).") from None
    if result.returncode or result.stdout.splitlines() != EXPECTED:
        raise CheckFailed("The Rust program must print the 16-byte context size and the first, "
                          "middle, and last listener addresses. Run it to see the error.")
    return "The Rust context is 16 bytes and its address calculation matches the runtime."


def main() -> None:
    parser = argparse.ArgumentParser()
    add_hint_argument(parser)
    args = parser.parse_args()
    run(check, args.hint_file)


if __name__ == "__main__":
    main()
