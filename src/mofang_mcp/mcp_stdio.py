from __future__ import annotations

import json
import os
import sys
import time
import uuid
from typing import Any

from .config import Settings
from .gateway import GatewayCore
from .logging_utils import log_event
from .tool_catalog import TOOLS, TOOL_BY_NAME


PROTOCOL_VERSION = "2025-03-26"
SUPPORTED_PROTOCOL_VERSIONS = {"2024-11-05", "2025-03-26"}
PROFILE_SOURCE_MODULES = ["company", "personnel", "websites"]
_LAST_READ_TRANSPORT = "content-length"


def _debug_log(event: str, **fields: Any) -> None:
    path = os.getenv("MOFANG_MCP_DEBUG_LOG")
    if not path:
        return
    try:
        payload = {"ts": int(time.time() * 1000), "event": event, **fields}
        with open(path, "a", encoding="utf-8") as fp:
            fp.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    except Exception:
        return


class McpServer:
    def __init__(self, gateway: GatewayCore | None = None) -> None:
        self.gateway = gateway or GatewayCore(Settings.from_env())

    def handle(self, message: dict[str, Any]) -> dict[str, Any] | None:
        method = message.get("method")
        message_id = message.get("id")
        try:
            if method == "initialize":
                params = message.get("params") or {}
                return self._response(message_id, self._initialize_result(params))
            if method == "notifications/initialized":
                return None
            if method == "ping":
                return self._response(message_id, {})
            if method == "tools/list":
                return self._response(message_id, {"tools": TOOLS})
            if method == "tools/call":
                params = message.get("params") or {}
                return self._response(message_id, self._call_tool(params, message_id))
            return self._error(message_id, -32601, f"method not found: {method}")
        except Exception as exc:
            return self._error(message_id, -32000, str(exc))

    def _initialize_result(self, params: dict[str, Any] | None = None) -> dict[str, Any]:
        client_protocol = str((params or {}).get("protocolVersion") or "")
        protocol_version = client_protocol if client_protocol in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        return {
            "protocolVersion": protocol_version,
            "capabilities": {
                "tools": {
                    "listChanged": False,
                }
            },
            "serverInfo": {
                "name": "mofang-enterprise-query",
                "version": "0.1.0",
            },
        }

    def _call_tool(self, params: Any, message_id: Any = None) -> dict[str, Any]:
        started = time.perf_counter()
        request_id = self._make_request_id(params, message_id)
        if not isinstance(params, dict):
            result = self._tool_error(10001, "INVALID_ARGUMENT", "params must be object", False, request_id, started)
            return self._tool_result(result)
        name = str(params.get("name") or "")
        arguments = params.get("arguments", {})
        if name not in TOOL_BY_NAME:
            result = self._tool_error(10001, "INVALID_ARGUMENT", f"unknown tool: {name}", False, request_id, started, name)
            return self._tool_result(result)
        if not isinstance(arguments, dict):
            result = self._tool_error(10001, "INVALID_ARGUMENT", "arguments must be object", False, request_id, started, name)
            return self._tool_result(result)
        validation_error = self._validate_schema(TOOL_BY_NAME[name]["inputSchema"], arguments)
        if validation_error:
            result = self._tool_error(10001, "INVALID_ARGUMENT", validation_error, False, request_id, started, name)
            return self._tool_result(result)
        result = self._dispatch_tool(name, arguments, request_id)
        return self._tool_result(result)

    def _tool_result(self, result: dict[str, Any]) -> dict[str, Any]:
        is_error = bool(result.get("code") not in (None, 0))
        telemetry = (result.get("meta") or {}).get("telemetry") or {}
        log_event(
            "mcp.tool_result",
            request_id=result.get("request_id"),
            tool_id=telemetry.get("tool_id"),
            code=result.get("code"),
            message=result.get("message"),
            is_error=is_error,
            latency_ms=(result.get("meta") or {}).get("latency_ms"),
            error_code=telemetry.get("error_code"),
        )
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(result, ensure_ascii=False, indent=2),
                }
            ],
            "isError": is_error,
        }

    def _dispatch_tool(self, name: str, arguments: dict[str, Any], request_id: str) -> dict[str, Any]:
        if name == "route_query":
            return self.gateway.route_query(str(arguments["query"]), request_id=request_id)
        if name == "resolve_entity":
            return self.gateway.resolve_entity(
                str(arguments["query"]),
                region_hint=arguments.get("region_hint"),
                top_k=int(arguments.get("top_k", 5)),
                request_id=request_id,
            )
        if name == "company_snapshot":
            return self.gateway.company_snapshot(
                arguments.get("entity") or {},
                list(arguments.get("modules") or []),
                options=arguments.get("options") or {},
                request_id=request_id,
            )
        if name == "company_profile":
            result = self.gateway.company_snapshot(
                arguments.get("entity") or {},
                ["profile"],
                options=arguments.get("options") or {},
                request_id=request_id,
            )
            return self._single_module_response(result, "profile", PROFILE_SOURCE_MODULES)
        if name == "company_risk":
            result = self.gateway.company_snapshot(
                arguments.get("entity") or {},
                ["risk"],
                options=arguments.get("options") or {},
                request_id=request_id,
            )
            return self._single_module_response(result, "risk")
        if name == "company_bidding":
            result = self.gateway.company_snapshot(
                arguments.get("entity") or {},
                ["bidding"],
                options=arguments.get("options") or {},
                request_id=request_id,
            )
            return self._single_module_response(result, "bidding")
        raise ValueError(f"tool not implemented: {name}")

    def _single_module_response(
        self,
        result: dict[str, Any],
        module: str,
        source_modules: list[str] | None = None,
    ) -> dict[str, Any]:
        if result.get("code") != 0:
            return result
        data = result.get("data") or {}
        modules = data.get("modules") or {}
        module_result = modules.get(module) or {"status": "error", "records": []}
        coverage = data.get("coverage") or {}
        gap_flags = list(coverage.get("gap_flags") or [])
        partial = module_result.get("status") != "ok" or bool(gap_flags)
        coverage = {**coverage, "partial": partial, "gap_flags": gap_flags}
        transformed_data = {
            "entity": data.get("entity") or {},
            module: module_result,
            "coverage": coverage,
            "partial": partial,
            "gap_flags": gap_flags,
        }
        if source_modules:
            transformed_data["source_modules"] = source_modules
        meta = result.get("meta") or {}
        telemetry = {**(meta.get("telemetry") or {}), "partial": partial}
        return {**result, "data": transformed_data, "meta": {**meta, "telemetry": telemetry}}

    def _make_request_id(self, params: Any, message_id: Any) -> str:
        meta = params.get("_meta") if isinstance(params, dict) else None
        if isinstance(meta, dict):
            request_id = meta.get("request_id") or meta.get("requestId")
            if isinstance(request_id, str) and request_id:
                return request_id
        if message_id is not None:
            return f"req_rpc_{message_id}"
        return f"req_{uuid.uuid4().hex}"

    def _tool_error(
        self,
        code: int,
        message: str,
        detail: str,
        retryable: bool,
        request_id: str,
        started: float,
        tool_id: str | None = None,
    ) -> dict[str, Any]:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return {
            "code": code,
            "message": message,
            "request_id": request_id,
            "error": {
                "type": "business",
                "detail": detail,
                "retryable": retryable,
            },
            "meta": {
                "latency_ms": latency_ms,
                "telemetry": {
                    "partial": False,
                    "api_call_count": 0,
                    "api_parallel_groups": 0,
                    "cache_hit_token": False,
                    "cache_hit_entity": False,
                    "cache_hit_route": False,
                    "cache_hit_snapshot": False,
                    "coverage_ratio": None,
                    "tool_id": tool_id,
                    "error_code": code,
                    "total_ms": latency_ms,
                },
            },
        }

    def _validate_schema(self, schema: dict[str, Any], value: Any, path: str = "arguments") -> str | None:
        expected_type = schema.get("type")
        if expected_type and not self._matches_type(value, expected_type):
            return f"{path} must be {expected_type}"

        if expected_type == "object":
            properties = schema.get("properties") or {}
            for required_key in schema.get("required") or []:
                if required_key not in value:
                    return f"{path}.{required_key} is required"
            if schema.get("additionalProperties") is False:
                extra_keys = sorted(set(value) - set(properties))
                if extra_keys:
                    return f"{path} has unsupported fields: {', '.join(extra_keys)}"
            for key, child_schema in properties.items():
                if key not in value:
                    continue
                error = self._validate_schema(child_schema, value[key], f"{path}.{key}")
                if error:
                    return error

        if expected_type == "array":
            item_schema = schema.get("items")
            if item_schema:
                for index, item in enumerate(value):
                    error = self._validate_schema(item_schema, item, f"{path}[{index}]")
                    if error:
                        return error

        enum_values = schema.get("enum")
        if enum_values is not None and value not in enum_values:
            return f"{path} must be one of: {', '.join(str(item) for item in enum_values)}"

        if isinstance(value, int) and not isinstance(value, bool):
            minimum = schema.get("minimum")
            maximum = schema.get("maximum")
            if minimum is not None and value < minimum:
                return f"{path} must be >= {minimum}"
            if maximum is not None and value > maximum:
                return f"{path} must be <= {maximum}"
        return None

    def _matches_type(self, value: Any, expected_type: str) -> bool:
        if expected_type == "object":
            return isinstance(value, dict)
        if expected_type == "string":
            return isinstance(value, str)
        if expected_type == "integer":
            return isinstance(value, int) and not isinstance(value, bool)
        if expected_type == "array":
            return isinstance(value, list)
        return True

    def _response(self, message_id: Any, result: dict[str, Any]) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "result": result,
        }

    def _error(self, message_id: Any, code: int, message: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": message_id,
            "error": {
                "code": code,
                "message": message,
            },
        }


def read_message(stdin) -> dict[str, Any] | None:
    global _LAST_READ_TRANSPORT
    while True:
        line = stdin.readline()
        if line == b"":
            _debug_log("read.eof")
            return None

        stripped = line.strip()
        if not stripped:
            continue

        if stripped.startswith((b"{", b"[")):
            try:
                message = json.loads(stripped.decode("utf-8"))
                _LAST_READ_TRANSPORT = "jsonline"
                _debug_log("read.message", transport="jsonline", method=message.get("method"), id=message.get("id"))
                return message
            except json.JSONDecodeError as exc:
                _debug_log(
                    "read.bad_json_line",
                    error=str(exc),
                    payload_preview=stripped[:200].decode("utf-8", "replace"),
                )
                continue

        headers: dict[str, str] = {}
        decoded = stripped.decode("ascii", "replace")
        if ":" in decoded:
            key, value = decoded.split(":", 1)
            headers[key.lower()] = value.strip()

        while True:
            line = stdin.readline()
            if line == b"":
                _debug_log("read.eof")
                return None
            line = line.decode("ascii", "replace").strip()
            if not line:
                if headers:
                    break
                continue
            if ":" in line:
                key, value = line.split(":", 1)
                headers[key.lower()] = value.strip()

        _debug_log("read.headers", headers=headers)
        length_raw = headers.get("content-length")
        if length_raw is None:
            _debug_log("read.skip_no_content_length")
            continue

        try:
            length = int(length_raw)
        except ValueError:
            _debug_log("read.skip_bad_content_length", length_raw=length_raw)
            continue
        if length <= 0:
            _debug_log("read.skip_non_positive_length", length=length)
            continue

        payload = stdin.read(length)
        if not payload:
            _debug_log("read.empty_payload", length=length)
            return None

        try:
            message = json.loads(payload.decode("utf-8"))
            _LAST_READ_TRANSPORT = "content-length"
            _debug_log("read.message", transport="content-length", method=message.get("method"), id=message.get("id"))
            return message
        except json.JSONDecodeError as exc:
            _debug_log("read.bad_json", error=str(exc), payload_preview=payload[:200].decode("utf-8", "replace"))
            continue



def write_message(stdout, message: dict[str, Any]) -> None:
    payload = json.dumps(message, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if _LAST_READ_TRANSPORT == "jsonline":
        stdout.write(payload + b"\n")
    else:
        stdout.write(f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii"))
        stdout.write(payload)
    stdout.flush()


def serve_stdio() -> None:
    server = McpServer()
    stdin = sys.stdin.buffer
    stdout = sys.stdout.buffer
    _debug_log("serve.start")
    while True:
        message = read_message(stdin)
        if message is None:
            _debug_log("serve.stop")
            break
        response = server.handle(message)
        if response is not None:
            _debug_log("serve.write", id=response.get("id"), has_result="result" in response, has_error="error" in response)
            write_message(stdout, response)
