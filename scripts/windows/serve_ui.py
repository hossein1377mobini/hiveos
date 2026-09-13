"""HiveOS Windows: local UI server (no node needed).

Serves frontend/dist on 127.0.0.1:8080 and transparently forwards every
/api/* request to the local API on 127.0.0.1:8000 - so the SPA sees the
same /api/v1 origin it uses behind the staging/prod nginx.

Usage:  .venv\Scripts\python.exe scripts\windows\serve_ui.py
"""
from __future__ import annotations

import http.client
import mimetypes
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DIST = (Path(__file__).resolve().parents[2] / "frontend" / "dist").resolve()
API_HOST, API_PORT = "127.0.0.1", 8000
UI_HOST, UI_PORT = "127.0.0.1", 8080

# Upstream headers that must not be relayed verbatim. content-length is here on
# purpose: http.client decodes content-encoding transparently, but the upstream
# Content-Length counts the *compressed* bytes, so forwarding it desynchronizes
# the client (it waits for bytes that never arrive). The proxy sets its own.
HOP_HEADERS = {
    "connection",
    "keep-alive",
    "transfer-encoding",
    "upgrade",
    "content-encoding",
    "content-length",
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _proxy(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None
        conn = http.client.HTTPConnection(API_HOST, API_PORT, timeout=3600)
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
        # Mirror the staging nginx (NB-1): the api keys its per-IP rate limiters
        # on X-Forwarded-For when the peer is a trusted proxy.
        client_ip = self.client_address[0]
        prior = self.headers.get("X-Forwarded-For")
        headers["X-Forwarded-For"] = f"{prior}, {client_ip}" if prior else client_ip
        headers["X-Forwarded-Proto"] = "http"
        try:
            conn.request(self.command, self.path, body=body, headers=headers)
            resp = conn.getresponse()
        except OSError as exc:
            conn.close()
            self.send_error(502, f"API unreachable: {exc}")
            return
        try:
            self._relay(resp)
        finally:
            # the proxy runs for the whole session: one socket per request would
            # otherwise pile up until the GC happens to reap it.
            conn.close()

    def _relay(self, resp) -> None:

        streaming = (resp.getheader("Content-Type") or "").startswith("text/event-stream")
        self.send_response(resp.status)
        for k, v in resp.getheaders():
            if k.lower() not in HOP_HEADERS:
                self.send_header(k, v)
        if streaming:
            # SSE: no content-length; flush each frame as it arrives.
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Accel-Buffering", "no")
            self.end_headers()
            if self.command != "HEAD":
                while True:
                    try:
                        chunk = resp.read1(65536)
                    except OSError:
                        break
                    if not chunk:
                        break
                    self.wfile.write(chunk)
                    self.wfile.flush()
            self.close_connection = True
            return

        try:
            data = resp.read()
        except OSError as exc:
            self.send_error(502, f"API unreachable: {exc}")
            return
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def _static(self) -> None:
        rel = self.path.lstrip("/").split("?")[0]
        target = (DIST / rel).resolve() if rel else DIST / "index.html"
        if not str(target).startswith(str(DIST)):
            self.send_error(403)
            return
        if target.is_dir() or not target.exists():
            target = DIST / "index.html"  # SPA fallback
        if not target.exists():
            self.send_error(404)
            return
        data = target.read_bytes()
        ctype = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(data)

    def do_GET(self):
        self._proxy() if self.path.startswith("/api") else self._static()

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        self._proxy()

    def do_PUT(self):
        self._proxy()

    def do_PATCH(self):
        self._proxy()

    def do_DELETE(self):
        self._proxy()

    def log_message(self, fmt, *args):  # quieter console
        sys.stderr.write("[ui] " + fmt % args + "\n")


if __name__ == "__main__":
    if not (DIST / "index.html").exists():
        sys.exit(f"dist not found: {DIST}")
    print(f"HiveOS UI:  http://{UI_HOST}:{UI_PORT}   (panel: /admin)")
    print(f"API proxy:  /api/* -> http://{API_HOST}:{API_PORT}")
    ThreadingHTTPServer((UI_HOST, UI_PORT), Handler).serve_forever()
