#!/usr/bin/env python3
"""Check that the learner's rebuilt C server uses the index as an address."""

import argparse
import socket
from pathlib import Path

from grading import CheckFailed, add_hint_argument, run


SOURCE = Path("/home/laborant/15m-work/server.c")
SERVER = Path("/home/laborant/15m-work/server")


def check() -> str:
    if not SERVER.exists() or SERVER.stat().st_mtime < SOURCE.stat().st_mtime:
        raise CheckFailed("Compile the edited ~/15m-work/server.c before testing its addresses.")
    for index, address in ((1, "127.0.0.2"), (2, "127.0.0.3")):
        try:
            with socket.create_connection((address, 8081), timeout=2) as connection:
                connection.sendall(b"GET / HTTP/1.0\r\n\r\n")
                response = connection.recv(512)
        except OSError as error:
            raise CheckFailed(f"{address}:8081 did not answer ({error}). Start ./server {index}.") from None
        if not response.startswith(b"HTTP/1.0 200 OK\r\n") or not response.endswith(
            f"\r\n\r\n{index}".encode()
        ):
            raise CheckFailed(f"{address}:8081 answered, but did not return body {index}.")
    return "The rebuilt C server answered from two indexed addresses on port 8081."


def main() -> None:
    parser = argparse.ArgumentParser()
    add_hint_argument(parser)
    args = parser.parse_args()
    run(check, args.hint_file)


if __name__ == "__main__":
    main()
