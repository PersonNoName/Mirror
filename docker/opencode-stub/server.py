"""Minimal Phase 0 placeholder for the future OpenCode service."""

from http.server import BaseHTTPRequestHandler, HTTPServer
import json


class Handler(BaseHTTPRequestHandler):
    def _send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        if self.path in {"/", "/health"}:
            self._send_json(
                {
                    "service": "opencode-stub",
                    "status": "ok",
                    "mode": "phase0-placeholder",
                }
            )
            return
        self._send_json({"detail": "not found"}, status=404)

    def log_message(self, fmt: str, *args) -> None:
        return


if __name__ == "__main__":
    server = HTTPServer(("0.0.0.0", 4096), Handler)
    server.serve_forever()
