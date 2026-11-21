#!/usr/bin/env python3
"""Check a learner-started implicit-bind C server through a real TCP request."""

import argparse
from pathlib import Path
import socket

from grading import CheckFailed, add_hint_argument, run


PORT_FILE = Path("/tmp/15m-baseline.port")
EXPECTED = Path("/opt/15m-lab/baseline/bin/webserver_libc")


def check() -> str:
    if not PORT_FILE.exists():
        raise CheckFailed(f"{PORT_FILE} does not exist yet. Start the C baseline with "
                          f"PORT_FILE={PORT_FILE} so that it records its port.")
    try:
        port = int(PORT_FILE.read_text().strip())
    except ValueError:
        raise CheckFailed(f"{PORT_FILE} does not contain a port number.") from None
    if not 1 <= port <= 65535:
        raise CheckFailed(f"{PORT_FILE} contains {port}, which is not a valid TCP port.")
    pids = []
    for path in Path("/proc").glob("[0-9]*"):
        try:
            if (path / "exe").resolve() == EXPECTED:
                pids.append(int(path.name))
        except (FileNotFoundError, PermissionError):
            continue
    if not pids:
        raise CheckFailed("The C baseline (baseline/bin/webserver_libc) is not running.")
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
            connection.sendall(b"GET / HTTP/1.0\r\n\r\n")
            response = connection.recv(512)
    except OSError as error:
        raise CheckFailed(f"Nothing answered on 127.0.0.1:{port} ({error}). The port file may "
                          "be left over from an earlier run.") from None
    if not response.startswith(b"HTTP/1.0 200 OK\r\n") or not response.endswith(b"\r\n\r\nok"):
        raise CheckFailed(f"Port {port} answered, but the response was {response[:80]!r}.")
    return f"Baseline PID {pids[0]} answered HTTP on its implicit port {port}."


def main() -> None:
    parser = argparse.ArgumentParser()
    add_hint_argument(parser)
    args = parser.parse_args()
    run(check, args.hint_file)


if __name__ == "__main__":
    main()
