#!/usr/bin/env python3
"""Check a learner-started implicit-bind C server through a real TCP request."""

from pathlib import Path
import socket


PORT_FILE = Path("/tmp/15m-baseline.port")
EXPECTED = Path("/opt/15m-lab/baseline/bin/webserver_libc")


def main() -> None:
    if not PORT_FILE.exists():
        raise RuntimeError("start the C baseline with PORT_FILE=/tmp/15m-baseline.port")
    port = int(PORT_FILE.read_text().strip())
    if not 1 <= port <= 65535:
        raise RuntimeError("invalid baseline port")
    pids = []
    for path in Path("/proc").glob("[0-9]*"):
        try:
            if (path / "exe").resolve() == EXPECTED:
                pids.append(int(path.name))
        except (FileNotFoundError, PermissionError):
            continue
    if not pids:
        raise RuntimeError("start the C baseline yourself before checking")
    with socket.create_connection(("127.0.0.1", port), timeout=3) as connection:
        connection.sendall(b"GET / HTTP/1.0\r\n\r\n")
        response = connection.recv(512)
    if not response.startswith(b"HTTP/1.0 200 OK\r\n") or not response.endswith(b"\r\n\r\nok"):
        raise RuntimeError(f"unexpected baseline response: {response!r}")
    print(f"Baseline PID {pids[0]} answered HTTP on its implicit port {port}.")


if __name__ == "__main__":
    main()
