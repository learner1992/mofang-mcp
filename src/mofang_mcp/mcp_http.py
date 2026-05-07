from __future__ import annotations

import json
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlsplit

from .credentials import RequestContext
from .mcp_stdio import McpServer


class _McpHttpHandler(BaseHTTPRequestHandler):
    server_version = "MofangMCPHTTP/0.1"

    def do_GET(self) -> None:  # noqa: N802
        if self._request_path() != self.server.mcp_path:
            self._write_json(404, {"error": "not found"})
            return
        accept = str(self.headers.get("Accept") or "").lower()
        if "text/event-stream" not in accept:
            self._write_json(406, {"error": "text/event-stream required in Accept header"})
            return
        auth_error = self._check_credentials()
        if auth_error:
            return
        session_id = self._session_id()
        if session_id and not self.server.has_session(session_id):
            self._write_json(404, {"error": "unknown session"})
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        if session_id:
            self.send_header("Mcp-Session-Id", session_id)
        self.end_headers()
        try:
            self.wfile.write(b": stream opened\n\n")
            self.wfile.flush()
            while True:
                time.sleep(self.server.sse_heartbeat_seconds)
                self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self) -> None:  # noqa: N802
        if self._request_path() != self.server.mcp_path:
            self._write_json(404, {"error": "not found"})
            return

        content_type = str(self.headers.get("Content-Type") or "").lower()
        if "application/json" not in content_type:
            self._write_json(400, {"error": "invalid content-type"})
            return

        if self._check_credentials():
            return
        session_id = self._session_id()
        if session_id and not self.server.has_session(session_id):
            self._write_json(404, {"error": "unknown session"})
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
            app_key=str(self.headers.get("X-App-Access-Key") or "").strip(),
            app_secret=str(self.headers.get("X-App-Secret-Key") or "").strip(),
            transport="http",
        )

        try:
            response = self.server.mcp_server.handle(message, ctx)
        except Exception:
            self._write_json(500, {"error": "internal server error"})
            return
        if response is None:
            self.send_response(202)
            self.end_headers()
            return

        extra_headers: dict[str, str] = {}
        if message.get("method") == "initialize":
            session_id = self.server.create_session()
            extra_headers["Mcp-Session-Id"] = session_id
        elif session_id:
            extra_headers["Mcp-Session-Id"] = session_id
        self._write_json(200, response, extra_headers=extra_headers)

    def do_DELETE(self) -> None:  # noqa: N802
        if self._request_path() != self.server.mcp_path:
            self._write_json(404, {"error": "not found"})
            return
        if self._check_credentials():
            return
        session_id = self._session_id()
        if not session_id:
            self._write_json(400, {"error": "missing Mcp-Session-Id header"})
            return
        if not self.server.delete_session(session_id):
            self._write_json(404, {"error": "unknown session"})
            return
        self.send_response(204)
        self.end_headers()

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A003
        return

    def _request_path(self) -> str:
        return urlsplit(self.path).path

    def _session_id(self) -> str | None:
        return str(self.headers.get("Mcp-Session-Id") or "").strip() or None

    def _check_credentials(self) -> bool:
        app_key = str(self.headers.get("X-App-Access-Key") or "").strip()
        app_secret = str(self.headers.get("X-App-Secret-Key") or "").strip()
        if app_key and app_secret:
            return False
        self._write_json(401, {"error": "missing credentials headers"})
        return True

    def _write_json(self, status: int, payload: dict[str, Any], extra_headers: dict[str, str] | None = None) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.wfile.write(body)


class _McpHttpServer(ThreadingHTTPServer):
    mcp_server: McpServer
    mcp_path: str
    sse_heartbeat_seconds: float

    def __init__(self, server_address, RequestHandlerClass):  # noqa: N803
        super().__init__(server_address, RequestHandlerClass)
        self._session_lock = threading.Lock()
        self._sessions: set[str] = set()
        self.sse_heartbeat_seconds = 1.0

    def create_session(self) -> str:
        session_id = f"mcp_{uuid.uuid4().hex}"
        with self._session_lock:
            self._sessions.add(session_id)
        return session_id

    def has_session(self, session_id: str) -> bool:
        with self._session_lock:
            return session_id in self._sessions

    def delete_session(self, session_id: str) -> bool:
        with self._session_lock:
            if session_id not in self._sessions:
                return False
            self._sessions.remove(session_id)
            return True


def serve_http(host: str, port: int, path: str, mcp_server: McpServer | None = None) -> None:
    server = _McpHttpServer((host, port), _McpHttpHandler)
    server.mcp_server = mcp_server or McpServer()
    server.mcp_path = path
    server.serve_forever()
