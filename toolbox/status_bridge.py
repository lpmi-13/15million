#!/usr/bin/env python3
"""Read-only private-link view of the live runner for client-side grading."""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from status import cgroup_status, read_status


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path != "/status":
            self.send_error(404)
            return
        try:
            payload = read_status("/run/15m-lab/status.sock")
            payload["cgroup"] = cgroup_status(payload["pid"])
            body = json.dumps(payload, sort_keys=True).encode() + b"\n"
            self.send_response(200)
        except (OSError, ValueError, RuntimeError) as error:
            body = json.dumps({"error": str(error)}).encode() + b"\n"
            self.send_response(503)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    ThreadingHTTPServer(("172.16.0.2", 9090), Handler).serve_forever()
