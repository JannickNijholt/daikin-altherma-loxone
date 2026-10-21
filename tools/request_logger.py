#!/usr/bin/env python3
"""Log every HTTP request exactly as received, to inspect what Loxone sends.

Usage: python3 tools/request_logger.py [port]   (default 8099)

Point a Loxone Virtual Output at http://<this-machine>:<port> and watch stdout.
Responds with a small JSON echo, so "save HTTP response" has something to store.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class Handler(BaseHTTPRequestHandler):
    def _handle(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length).decode(errors="replace") if length else ""
        print(f"\n=== {datetime.now():%H:%M:%S} {self.client_address[0]} {self.command} {self.path}", flush=True)
        for name, value in self.headers.items():
            print(f"{name}: {value}", flush=True)
        print(f"--- body ({length} bytes)\n{body}", flush=True)
        reply = json.dumps({"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _handle

    def log_message(self, *args) -> None:
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8099
    print(f"Listening on 0.0.0.0:{port}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", port), Handler).serve_forever()
