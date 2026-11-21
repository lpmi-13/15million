"""Shared failure reporting for the lab's verification tasks.

A check prints one readable line when it fails. With --hint-file, it also writes
that line to a root-owned file that the task's hintcheck script shows the learner.
"""

import argparse
import sys
from pathlib import Path
from typing import Callable


class CheckFailed(Exception):
    """A learner-facing reason why a check has not passed yet."""


def add_hint_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--hint-file", type=Path,
                        help="write a one-line reason to this file when the check fails")


def run(check: Callable[[], str], hint_file: Path | None) -> None:
    if hint_file:
        hint_file.unlink(missing_ok=True)
    try:
        print(check())
        return
    except CheckFailed as error:
        message = str(error)
    except Exception as error:  # noqa: BLE001 - any state the check did not expect
        message = f"The check could not read the lab state ({type(error).__name__}: {error})."
    print(message, file=sys.stderr)
    if hint_file:
        hint_file.parent.mkdir(mode=0o755, parents=True, exist_ok=True)
        hint_file.write_text(message + "\n")
    raise SystemExit(1)
