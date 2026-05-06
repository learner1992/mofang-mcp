from __future__ import annotations

import json
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

from .credentials import RequestContext
from .mcp_stdio import McpServer


class _McpHttpHandler(BaseHTTPRequestHandler):
    server_version = "MofangMCPHTTP/0.1"

    def do_POST(self) -> None:  # noqa: N802
        if self.path != self.server.mcp_path:
            self._write_json(404, {"error": "not found"})
            return

        content_type = str(self.headers.get("Content-Type") or "").lower()
        if "application/json" not in content_type:
            self._write_json(400, {"error": "invalid content-type"})
            return

        app_key = str(self.headers.get("X-App-Access-Key") or "").strip()
        app_secret = str(self.headers.get("X-App-Secret-Key") or "").strip()
        if not app_key or not app_secret:
            self._write_json(401, {"error": "missing credentials headers"})
            return

        length_raw = self.headers.get("Content-Length")
        if not length_raw:
            self._write_json(400, {"error": "missing content-length"})
            return
        try:
            length = int(length_raw)
        except ValueError:
            self._write_json(400, {"error": "invalid content-length"})
            return

        try:
            payload = self.rfile.read(length)
            message = json.loads(payload.decode("utf-8"))
        except Exception:
            self._write_json(400, {"error": "invalid json payload"})
            return

        if not isinstance(message, dict):
            self._write_json(400, {"error": "json-rpc payload must be object"})
            return

        request_id = str(self.headers.get("X-Request-Id") or "").strip() or None
        if not request_id:
            rpc_id = message.get("id")
            request_id = f"req_rpc_{rpc_id}" if rpc_id is not None else f"req_{uuid.uuid4().hex}"

        headers = {str(k): str(v) for k, v in self.headers.items()}
        ctx = RequestContext(
            request_id=request_id,
            session_id=str(self.headers.get("X-Session-Id") or "").strip() or None,
            headers=headers,
            app_key=app_key,
            app_secret=app_secret,
            transport="http",
        )

        try:
            response = self.server.mcp_server.handle(message, ctx)
        except Exception:
            self._write_json(500, {"error": "internal server error"})
            return
        if response is None:
            self.send_response(204)
            self.end_headers()
            return

        self._write_json(200, response)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _write_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


class _McpHttpServer(ThreadingHTTPServer):
    mcp_server: McpServer
    mcp_path: str


def serve_http(host: str, port: int, path: str, mcp_server: McpServer | None = None) -> None:
    server = _McpHttpServer((host, port), _McpHttpHandler)
    server.mcp_server = mcp_server or McpServer()
    server.mcp_path = path
    server.serve_forever()
