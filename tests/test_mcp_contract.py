import json
import os
import tempfile
import time
from pathlib import Path

from mofang_mcp import gateway as gateway_module
from mofang_mcp.cache import TokenCache
from mofang_mcp.config import Settings
from mofang_mcp.credentials import Credential
from mofang_mcp.gateway import GatewayCore, MODULE_API_IDS, AuthError
from mofang_mcp.mcp_stdio import McpServer
from mofang_mcp.router import route_query


os.environ.setdefault("APP_ACCESS_KEY", "dummy")
os.environ.setdefault("APP_SECRET_KEY", "dummy")


def _tool_payload(response: dict) -> dict:
    return json.loads(response["result"]["content"][0]["text"])


def test_initialize() -> None:
    server = McpServer()
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert response["result"]["serverInfo"]["name"] == "mofang-enterprise-query"


def test_initialize_protocol_version_negotiation() -> None:
    server = McpServer()
    supported = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2024-11-05"},
        }
    )
    unsupported = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "initialize",
            "params": {"protocolVersion": "2099-01-01"},
        }
    )
    assert supported["result"]["protocolVersion"] == "2024-11-05"
    assert unsupported["result"]["protocolVersion"] == "2025-03-26"


def test_tools_list_contains_a0_tools() -> None:
    server = McpServer()
    response = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {item["name"] for item in response["result"]["tools"]}
    assert {
        "route_query",
        "resolve_entity",
        "company_snapshot",
        "company_profile",
        "company_risk",
        "company_bidding",
        "bidding_search",
    } <= names
    for item in response["result"]["tools"]:
        assert item["tool_id"] == item["name"]
        assert item["version"]
        assert item["deprecated"] is False
        assert "sunset_at" in item


def test_route_query_call() -> None:
    server = McpServer()
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "route_query",
                "arguments": {
                    "query": "查一下华为最近一年招投标和裁判文书",
                },
            },
        }
    )
    assert response["result"]["isError"] is False
    text = response["result"]["content"][0]["text"]
    assert "bidding" in text
    assert "risk" in text
    assert "query_signature" not in text


def test_single_module_tool_response_shape() -> None:
    server = McpServer()
    result = {
        "code": 0,
        "message": "ok",
        "request_id": "req_test",
        "data": {
            "entity": {"ent_name": "测试公司"},
            "modules": {"profile": {"status": "ok"}},
            "coverage": {"coverage_ratio": 1.0, "gap_flags": []},
        },
        "meta": {"telemetry": {"partial": False}},
    }
    transformed = server._single_module_response(result, "profile", ["company"])
    assert transformed["data"]["entity"]["ent_name"] == "测试公司"
    assert transformed["data"]["profile"]["status"] == "ok"
    assert transformed["data"]["source_modules"] == ["company"]
    assert transformed["data"]["partial"] is False
    assert transformed["meta"]["telemetry"]["partial"] is False


def test_single_module_partial_is_explicit_degraded_success() -> None:
    server = McpServer()
    result = {
        "code": 0,
        "message": "ok",
        "request_id": "req_test",
        "data": {
            "entity": {"ent_name": "测试公司"},
            "modules": {"risk": {"status": "partial", "records": [{"status": 500}]}},
            "coverage": {"coverage_ratio": 0.0, "gap_flags": ["risk_partial"]},
        },
        "meta": {"telemetry": {"partial": True, "coverage_ratio": 0.0}},
    }
    transformed = server._single_module_response(result, "risk")
    assert transformed["code"] == 0
    assert transformed["data"]["risk"]["status"] == "partial"
    assert transformed["data"]["partial"] is True
    assert transformed["data"]["gap_flags"] == ["risk_partial"]
    assert transformed["meta"]["telemetry"]["partial"] is True


def test_route_query_has_contract_fields_only() -> None:
    routed = route_query("查一下华为招投标")
    assert routed["modules"] == ["bidding"]
    assert routed["deferred_modules"] == []
    assert routed["route_warnings"] == []
    assert "query_signature" not in routed


def test_route_query_defers_non_a0_modules() -> None:
    routed = route_query("查一下华为的专利、招聘和融资")
    assert routed["modules"] == ["profile"]
    assert routed["deferred_modules"] == ["ip", "operation", "development"]
    assert routed["route_warnings"] == [
        "ip_not_available_in_a0",
        "operation_not_available_in_a0",
        "development_not_available_in_a0",
    ]


def test_build_body_for_icp_api_includes_keyword_only() -> None:
    gateway = GatewayCore(Settings.from_env())
    entity = {"ent_name": "启魔方（北京）科技有限公司"}
    body = gateway._build_body(1013, entity, {"current": 2, "limit": 20})
    assert body == {"keyword": "启魔方（北京）科技有限公司"}


def test_bidding_search_returns_standardized_list() -> None:
    gateway = GatewayCore(Settings.from_env())

    def fake_request_with_token_retry(
        credential,
        method,
        path,
        body,
        request_id=None,
        api_id=None,
        api_name=None,
    ):
        assert method == "POST"
        assert path == "/open/data/bidding/search"
        assert body == {"keyword": "小米", "searchType": "1", "current": 2, "size": 20}
        return (
            200,
            {
                "code": "200",
                "current": "2",
                "size": "20",
                "total": "1",
                "pages": "1",
                "records": [{"title": "测试标讯", "region": "北京"}],
            },
            {"cache_hit_token": True},
        )

    gateway._request_with_token_retry = fake_request_with_token_retry
    response = gateway.bidding_search("小米", search_type="1", options={"current": 2, "limit": 20}, request_id="req_bid_search")
    assert response["code"] == 0
    assert response["request_id"] == "req_bid_search"
    assert response["data"]["query"] == "小米"
    assert response["data"]["search_type_label"] == "exact"
    assert response["data"]["bidding_search"]["records"][0]["title"] == "测试标讯"
    assert response["data"]["bidding_search"]["pagination"]["total"] == "1"


def test_bidding_search_rejects_invalid_search_type() -> None:
    gateway = GatewayCore(Settings.from_env())
    response = gateway.bidding_search("小米", search_type="2", request_id="req_bad_search_type")
    assert response["code"] == 10001
    assert response["message"] == "INVALID_ARGUMENT"
    assert response["request_id"] == "req_bad_search_type"


def test_snapshot_cache_key_canonicalizes_options() -> None:
    gateway = GatewayCore(Settings.from_env())
    credential = Credential("default", "ak", "sk")
    entity = {"ent_name": "测试公司"}
    left = gateway._snapshot_cache_key(credential, "profile", entity, {"limit": 5, "current": 1})
    right = gateway._snapshot_cache_key(credential, "profile", entity, {"current": 1, "limit": 5})
    assert left == right


def test_error_names_match_contract() -> None:
    gateway = GatewayCore(Settings.from_env())
    assert gateway._auth_error("x")["message"] == "UNAUTHORIZED"
    assert gateway._upstream_timeout_error("x", True)["message"] == "UPSTREAM_TIMEOUT"
    assert gateway._upstream_error("x", True)["message"] == "UPSTREAM_BAD_GATEWAY"


def test_tools_call_validation_returns_jsonrpc_error() -> None:
    server = McpServer()
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "route_query",
                "arguments": {},
            },
        }
    )
    assert response["error"]["code"] == -32602
    assert response["error"]["message"] == "arguments.query is required"


def test_snapshot_invalid_options_return_jsonrpc_error() -> None:
    server = McpServer()
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "company_snapshot",
                "arguments": {
                    "entity": {"ent_name": "测试公司"},
                    "modules": ["profile"],
                    "options": {"limit": "abc"},
                },
            },
        }
    )
    assert response["error"]["code"] == -32602
    assert response["error"]["message"] == "arguments.options.limit must be integer"


def test_request_id_is_propagated_from_mcp_params() -> None:
    server = McpServer()
    response = server.handle(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {
                "name": "route_query",
                "_meta": {"request_id": "req_external"},
                "arguments": {
                    "query": "查一下华为招投标",
                },
            },
        }
    )
    payload = _tool_payload(response)
    assert payload["request_id"] == "req_external"


def test_snapshot_rejects_unsupported_modules_explicitly() -> None:
    gateway = GatewayCore(Settings.from_env())
    response = gateway.company_snapshot(
        {"ent_name": "测试公司"},
        ["profile", "ip"],
        request_id="req_unsupported",
    )
    assert response["code"] == 10001
    assert response["message"] == "INVALID_ARGUMENT"
    assert response["request_id"] == "req_unsupported"
    assert response["error"]["context"]["unsupported_modules"] == ["ip"]
    assert "profile" in response["error"]["context"]["supported_modules"]


def test_snapshot_rejects_empty_entity_before_fetch() -> None:
    gateway = GatewayCore(Settings.from_env())
    called = False

    def fake_fetch_module(module, entity, credential, options, request_id=None):
        nonlocal called
        called = True
        return {"status": "ok", "records": [], "cache_hit_snapshot": False}

    gateway._fetch_module = fake_fetch_module
    response = gateway.company_snapshot({"ent_name": " "}, ["profile"], request_id="req_bad_entity")
    assert called is False
    assert response["code"] == 10001
    assert response["message"] == "INVALID_ARGUMENT"
    assert response["request_id"] == "req_bad_entity"
    assert response["error"]["context"]["required_any_of"] == ["ent_name", "uni_sc_id", "keyword"]


def test_snapshot_all_timeout_returns_timeout_error() -> None:
    gateway = GatewayCore(Settings.from_env())

    def fake_fetch_module(module, entity, credential, options, request_id=None):
        return {
            "status": "error",
            "error_type": "UPSTREAM_TIMEOUT",
            "records": [{"status": 598}],
            "cache_hit_snapshot": False,
        }

    gateway._fetch_module = fake_fetch_module
    response = gateway.company_snapshot(
        {"ent_name": "测试公司"},
        ["profile", "risk"],
        request_id="req_timeout",
    )
    assert response["code"] == 15001
    assert response["message"] == "UPSTREAM_TIMEOUT"
    assert response["request_id"] == "req_timeout"
    assert response["meta"]["telemetry"]["error_code"] == 15001
    assert "total_ms" in response["meta"]["telemetry"]


def test_snapshot_auth_error_returns_unauthorized() -> None:
    gateway = GatewayCore(Settings.from_env())

    def fake_fetch_module(module, entity, credential, options, request_id=None):
        raise AuthError("openapi auth failed after token refresh")

    gateway._fetch_module = fake_fetch_module
    response = gateway.company_snapshot(
        {"ent_name": "测试公司"},
        ["profile"],
        request_id="req_auth_failed",
    )
    assert response["code"] == 11001
    assert response["message"] == "UNAUTHORIZED"
    assert response["request_id"] == "req_auth_failed"
    assert response["meta"]["telemetry"]["tool_id"] == "company_snapshot"


def test_request_with_token_retry_raises_auth_after_retry_failure() -> None:
    gateway = GatewayCore(Settings.from_env())
    calls = []

    def fake_get_token(credential, force_refresh=False):
        return ("fresh_token" if force_refresh else "stale_token"), {
            "cache_hit_token": not force_refresh,
            "token_refresh_result": "force_refresh" if force_refresh else "cache_hit",
        }

    original_http_json = gateway_module.http_json

    def fake_http_json(method, url, body, timeout):
        calls.append(url)
        return 401, {"code": "401", "msg": "auth failed"}

    gateway._get_token = fake_get_token
    gateway_module.http_json = fake_http_json
    try:
        try:
            gateway._request_with_token_retry(
                gateway._resolve_credential(),
                "POST",
                "/mock",
                {"keyword": "测试公司"},
                request_id="req_retry_auth_failed",
            )
        except AuthError as exc:
            assert "auth failed" in str(exc)
        else:
            raise AssertionError("AuthError was not raised")
    finally:
        gateway_module.http_json = original_http_json

    assert len(calls) == 2
    assert "stale_token" in calls[0]
    assert "fresh_token" in calls[1]


def test_snapshot_error_result_is_not_cached() -> None:
    gateway = GatewayCore(Settings.from_env())
    credential = Credential("default", "ak", "sk")
    entity = {"ent_name": "测试公司"}

    def fake_call_openapi(api_id, entity, credential, options, request_id=None):
        return (
            {"api_id": api_id, "api_name": str(api_id), "path": "/mock", "status": 500, "body": {}},
            {"cache_hit_token": True, "token_refresh_result": "cache_hit"},
        )

    gateway._call_openapi = fake_call_openapi
    result = gateway._fetch_module("profile", entity, credential, {"current": 1, "limit": 5})
    cache_key = gateway._snapshot_cache_key(credential, "profile", entity, {"current": 1, "limit": 5})
    assert result["status"] == "error"
    assert gateway.snapshot_cache.get(cache_key) is None


def test_snapshot_partial_result_uses_short_cache() -> None:
    gateway = GatewayCore(Settings.from_env())
    credential = Credential("default", "ak", "sk")
    entity = {"ent_name": "测试公司"}
    calls = []

    def fake_call_openapi(api_id, entity, credential, options, request_id=None):
        calls.append(api_id)
        status = 200 if len(calls) == 1 else 500
        return (
            {"api_id": api_id, "api_name": str(api_id), "path": "/mock", "status": status, "body": {}},
            {"cache_hit_token": True, "token_refresh_result": "cache_hit"},
        )

    gateway._call_openapi = fake_call_openapi
    result = gateway._fetch_module("profile", entity, credential, {"current": 1, "limit": 5})
    cache_key = gateway._snapshot_cache_key(credential, "profile", entity, {"current": 1, "limit": 5})
    cached = gateway.snapshot_cache.get(cache_key)
    assert result["status"] == "partial"
    assert cached is not None
    assert cached["status"] == "partial"


def test_snapshot_partial_coverage_has_returned_and_degraded_modules() -> None:
    gateway = GatewayCore(Settings.from_env())

    def fake_fetch_module(module, entity, credential, options, request_id=None):
        if module == "profile":
            return {"status": "ok", "records": [{"status": 200}], "cache_hit_snapshot": False}
        return {"status": "partial", "records": [{"status": 200}, {"status": 500}], "cache_hit_snapshot": False}

    gateway._fetch_module = fake_fetch_module
    response = gateway.company_snapshot(
        {"ent_name": "测试公司"},
        ["profile", "risk"],
        request_id="req_partial",
    )
    coverage = response["data"]["coverage"]
    assert response["code"] == 0
    assert coverage["fulfilled_modules"] == ["profile"]
    assert sorted(coverage["returned_modules"]) == ["profile", "risk"]
    assert coverage["degraded_modules"] == ["risk"]
    assert coverage["coverage_ratio"] == 0.5
    assert coverage["returned_ratio"] == 1.0
    assert response["meta"]["telemetry"]["partial"] is True


def test_snapshot_preserves_requested_module_order() -> None:
    gateway = GatewayCore(Settings.from_env())

    def fake_fetch_module(module, entity, credential, options, request_id=None):
        if module == "profile":
            time.sleep(0.03)
            return {"status": "ok", "records": [{"status": 200}], "cache_hit_snapshot": False}
        if module == "risk":
            time.sleep(0.01)
            return {"status": "ok", "records": [{"status": 200}], "cache_hit_snapshot": False}
        return {"status": "partial", "records": [{"status": 200}, {"status": 500}], "cache_hit_snapshot": False}

    gateway._fetch_module = fake_fetch_module
    response = gateway.company_snapshot(
        {"ent_name": "测试公司"},
        ["profile", "risk", "bidding"],
        request_id="req_order",
    )
    coverage = response["data"]["coverage"]
    assert list(response["data"]["modules"]) == ["profile", "risk", "bidding"]
    assert coverage["fulfilled_modules"] == ["profile", "risk"]
    assert coverage["returned_modules"] == ["profile", "risk", "bidding"]
    assert coverage["degraded_modules"] == ["bidding"]
    assert coverage["gap_flags"] == ["bidding_partial"]


def test_snapshot_telemetry_aggregates_token_cache() -> None:
    gateway = GatewayCore(Settings.from_env())

    def fake_call_openapi(api_id, entity, credential, options, request_id=None):
        return (
            {"api_id": api_id, "api_name": str(api_id), "path": "/mock", "status": 200, "body": {}},
            {
                "cache_hit_token": True,
                "token_refresh_result": "cache_hit",
                "app_key_fingerprint": "fp_test",
            },
        )

    gateway._call_openapi = fake_call_openapi
    response = gateway.company_snapshot(
        {"ent_name": "测试公司"},
        ["profile"],
        request_id="req_token_telemetry",
    )
    telemetry = response["meta"]["telemetry"]
    assert telemetry["cache_hit_token"] is True
    assert telemetry["token_cache_hit_count"] == len(MODULE_API_IDS["profile"])
    assert telemetry["token_refresh_count"] == 0
    assert telemetry["token_refresh_result"] == "cache_hit"


def test_resolve_entity_retries_once_after_401() -> None:
    gateway = GatewayCore(Settings.from_env())
    calls = []

    def fake_get_token(credential, force_refresh=False):
        if force_refresh:
            return (
                "fresh_token",
                {
                    "cache_hit_token": False,
                    "token_refresh_result": "force_refresh",
                    "token_refresh_ms": 1,
                    "app_key_fingerprint": "fp_test",
                },
            )
        return (
            "stale_token",
            {
                "cache_hit_token": True,
                "token_refresh_result": "cache_hit",
                "app_key_fingerprint": "fp_test",
            },
        )

    original_http_json = gateway_module.http_json

    def fake_http_json(method, url, body, timeout):
        calls.append(url)
        if len(calls) == 1:
            return 401, {"code": "401", "msg": "token expired"}
        return 200, {"records": [{"entName": "测试公司", "uniScId": "913000000000000000"}]}

    gateway._get_token = fake_get_token
    gateway_module.http_json = fake_http_json
    try:
        response = gateway.resolve_entity("测试公司", request_id="req_retry_401")
    finally:
        gateway_module.http_json = original_http_json

    assert response["code"] == 0
    assert response["request_id"] == "req_retry_401"
    assert len(calls) == 2
    assert "stale_token" in calls[0]
    assert "fresh_token" in calls[1]
    telemetry = response["meta"]["telemetry"]
    assert telemetry["token_retry_after_401"] is True
    assert telemetry["token_cache_hit_count"] == 1
    assert telemetry["token_refresh_count"] == 1


def test_token_cache_requires_expire_at_and_refresh_at_to_be_valid() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        cache = TokenCache(Path(tmpdir))
        now = int(time.time())
        assert cache._is_usable({"access_token": "t", "expire_at": now + 600, "refresh_at": now + 300}) is True
        assert cache._is_usable({"access_token": "t", "expire_at": now - 1, "refresh_at": now + 300}) is False
        assert cache._is_usable({"access_token": "t", "expire_at": now + 600, "refresh_at": now - 1}) is False
