import json
import threading
import urllib.error
import urllib.request
from contextlib import contextmanager

from mofang_mcp.mcp_http import _McpHttpHandler, _McpHttpServer
from mofang_mcp.mcp_stdio import McpServer


@contextmanager
def _start_test_server(path: str = "/mcp/company/stream", mcp_server: McpServer | None = None):
    server = _McpHttpServer(("127.0.0.1", 0), _McpHttpHandler)
    server.mcp_server = mcp_server or McpServer()
    server.mcp_path = path
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host, port = server.server_address
        yield f"http://{host}:{port}{path}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def _post(
    url: str,
    body: dict,
    headers: dict[str, str] | None = None,
    content_type: str = "application/json",
):
    payload = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", content_type)
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=2) as resp:
            status = resp.getcode()
            content = resp.read().decode("utf-8")
            return status, json.loads(content) if content else {}
    except urllib.error.HTTPError as exc:
        content = exc.read().decode("utf-8")
        return exc.code, json.loads(content) if content else {}


def test_http_initialize_success_with_headers() -> None:
    with _start_test_server() as url:
        status, body = _post(
            url,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={
                "X-App-Access-Key": "ak",
                "X-App-Secret-Key": "sk",
            },
        )
    assert status == 200
    assert body["result"]["serverInfo"]["name"] == "mofang-enterprise-query"


def test_http_missing_credentials_headers_returns_401() -> None:
    with _start_test_server() as url:
        status, body = _post(
            url,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        )
    assert status == 401
    assert body["error"] == "missing credentials headers"


def test_http_invalid_content_type_returns_400() -> None:
    with _start_test_server() as url:
        status, body = _post(
            url,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={
                "X-App-Access-Key": "ak",
                "X-App-Secret-Key": "sk",
            },
            content_type="text/plain",
        )
    assert status == 400
    assert body["error"] == "invalid content-type"


def test_http_unknown_method_returns_jsonrpc_error() -> None:
    with _start_test_server() as url:
        status, body = _post(
            url,
            {"jsonrpc": "2.0", "id": 1, "method": "not-exists", "params": {}},
            headers={
                "X-App-Access-Key": "ak",
                "X-App-Secret-Key": "sk",
            },
        )
    assert status == 200
    assert body["error"]["code"] == -32601


def test_http_unknown_tool_returns_jsonrpc_error() -> None:
    with _start_test_server() as url:
        status, body = _post(
            url,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "not-exists",
                    "arguments": {},
                },
            },
            headers={
                "X-App-Access-Key": "ak",
                "X-App-Secret-Key": "sk",
            },
        )
    assert status == 200
    assert body["error"]["code"] == -32602
    assert body["error"]["message"] == "unknown tool: not-exists"


def test_http_tool_schema_validation_returns_jsonrpc_error() -> None:
    with _start_test_server() as url:
        status, body = _post(
            url,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "route_query",
                    "arguments": {},
                },
            },
            headers={
                "X-App-Access-Key": "ak",
                "X-App-Secret-Key": "sk",
            },
        )
    assert status == 200
    assert body["error"]["code"] == -32602
    assert body["error"]["message"] == "arguments.query is required"


def test_http_internal_error_returns_500() -> None:
    class CrashServer:
        def handle(self, _message, _ctx):
            raise RuntimeError("boom")

    with _start_test_server(mcp_server=CrashServer()) as url:
        status, body = _post(
            url,
            {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
            headers={
                "X-App-Access-Key": "ak",
                "X-App-Secret-Key": "sk",
            },
        )
    assert status == 500
    assert body["error"] == "internal server error"


def test_http_x_request_id_overrides_meta_request_id() -> None:
    with _start_test_server() as url:
        status, body = _post(
            url,
            {
                "jsonrpc": "2.0",
                "id": 99,
                "method": "tools/call",
                "params": {
                    "name": "route_query",
                    "_meta": {"request_id": "req_from_meta"},
                    "arguments": {"query": "查一下华为招投标"},
                },
            },
            headers={
                "X-App-Access-Key": "ak",
                "X-App-Secret-Key": "sk",
                "X-Request-Id": "req_from_header",
            },
        )
    assert status == 200
    payload = json.loads(body["result"]["content"][0]["text"])
    assert payload["request_id"] == "req_from_header"
