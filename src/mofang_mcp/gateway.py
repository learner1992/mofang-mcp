from __future__ import annotations

import hashlib
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

from .cache import TTLMemoryCache, TokenCache
from .config import Settings
from .credentials import Credential, CredentialResolver, RequestContext
from .http_client import http_json, quote
from .logging_utils import log_event
from .manifest import Manifest
from .router import route_query


MODULE_API_IDS: dict[str, tuple[int, ...]] = {
    "profile": (202, 222, 204, 205, 206, 603, 1013),
    "risk": (503, 505, 510, 512, 523, 525),
    "bidding": (901, 907, 911, 912, 922),
}
SUPPORTED_MODULES = tuple(MODULE_API_IDS)
SNAPSHOT_OK_TTL_SECONDS = 3600
SNAPSHOT_PARTIAL_TTL_SECONDS = 300


class AuthError(RuntimeError):
    pass


class UpstreamError(RuntimeError):
    pass


class UpstreamTimeoutError(UpstreamError):
    pass


class GatewayCore:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.manifest = Manifest(settings.manifest_path)
        self.credentials = CredentialResolver()
        self.token_cache = TokenCache(settings.cache_dir)
        self.entity_cache = TTLMemoryCache()
        self.snapshot_cache = TTLMemoryCache()

    def route_query(self, query: str, request_id: str | None = None, ctx: RequestContext | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            self._resolve_credential(ctx)
        except AuthError as exc:
            return self._auth_error(str(exc), started, request_id, tool_id="route_query")
        data = route_query(query)
        return self._ok(data, started, {"tool_id": "route_query"}, request_id)

    def resolve_entity(
        self,
        query: str,
        region_hint: str | None = None,
        top_k: int = 5,
        request_id: str | None = None,
        ctx: RequestContext | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            credential = self._resolve_credential(ctx)
        except AuthError as exc:
            return self._auth_error(str(exc), started, request_id, tool_id="resolve_entity")
        cache_key = f"{credential.account_id}:{credential.app_key_fingerprint}:{query}:{region_hint or ''}:{top_k}"
        cached = self.entity_cache.get(cache_key)
        if cached:
            return self._ok(cached, started, {"tool_id": "resolve_entity", "cache_hit_entity": True}, request_id)

        try:
            status, payload, token_meta = self._request_with_token_retry(
                credential,
                "POST",
                "/open/data/company/intelligence-search",
                {"keyword": query},
                request_id=request_id,
            )
        except AuthError as exc:
            return self._auth_error(str(exc), started, request_id, tool_id="resolve_entity")
        except UpstreamTimeoutError as exc:
            return self._upstream_timeout_error(str(exc), True, started, request_id, tool_id="resolve_entity")
        except UpstreamError as exc:
            return self._upstream_error(str(exc), True, started, request_id, tool_id="resolve_entity")
        if status in (401, 403) or str(payload.get("code")) in {"401", "403", "11001"}:
            return self._auth_error(
                payload.get("msg") or "entity resolve auth failed",
                started,
                request_id,
                tool_id="resolve_entity",
            )
        if status == 598:
            return self._upstream_timeout_error(
                payload.get("msg") or "entity resolve upstream timeout",
                True,
                started,
                request_id,
                tool_id="resolve_entity",
            )
        if status >= 500 or status == 599:
            return self._upstream_error(
                payload.get("msg") or f"entity resolve upstream status={status}",
                True,
                started,
                request_id,
                tool_id="resolve_entity",
            )
        result = self._parse_entity_result(query, payload, status, top_k)
        self.entity_cache.set(cache_key, result, 86400)
        return self._ok(result, started, {"tool_id": "resolve_entity", "api_call_count": 1, **token_meta}, request_id)

    def company_snapshot(
        self,
        entity: dict[str, Any],
        modules: list[str],
        options: dict[str, Any] | None = None,
        request_id: str | None = None,
        ctx: RequestContext | None = None,
    ) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            credential = self._resolve_credential(ctx)
        except AuthError as exc:
            return self._auth_error(str(exc), started, request_id, tool_id="company_snapshot")
        options = options or {}
        entity_error = self._validate_entity(entity, started, request_id, tool_id="company_snapshot")
        if entity_error:
            return entity_error
        options, options_error = self._normalize_options(options, started, request_id, tool_id="company_snapshot")
        if options_error:
            return options_error
        requested_modules = list(modules)
        unsupported_modules = [module for module in requested_modules if module not in MODULE_API_IDS]
        if unsupported_modules:
            return self._error(
                10001,
                "INVALID_ARGUMENT",
                f"unsupported modules: {', '.join(unsupported_modules)}",
                False,
                started=started,
                request_id=request_id,
                context={
                    "unsupported_modules": unsupported_modules,
                    "supported_modules": list(SUPPORTED_MODULES),
                },
                tool_id="company_snapshot",
            )
        modules = requested_modules
        if not modules:
            return self._error(10001, "INVALID_ARGUMENT", "modules is empty", False, started, request_id, tool_id="company_snapshot")

        module_outputs: dict[str, dict[str, Any]] = {}
        results: dict[str, Any] = {}
        fulfilled: list[str] = []
        returned: list[str] = []
        degraded: list[str] = []
        gap_flags: list[str] = []
        failure_types: list[str] = []
        token_telemetry_items: list[dict[str, Any]] = []
        with ThreadPoolExecutor(max_workers=min(len(modules), 4)) as pool:
            futures = {
                pool.submit(self._fetch_module, module, entity, credential, options, request_id): module
                for module in modules
            }
            auth_error_detail = None
            for future in as_completed(futures):
                module = futures[future]
                try:
                    module_outputs[module] = future.result()
                except AuthError as exc:
                    auth_error_detail = str(exc)
                except Exception as exc:
                    error_type = self._exception_error_type(exc)
                    module_outputs[module] = {"status": "error", "error": str(exc), "error_type": error_type}
        if auth_error_detail:
            return self._auth_error(auth_error_detail, started, request_id, tool_id="company_snapshot")

        for module in modules:
            module_result = module_outputs[module]
            token_telemetry = module_result.pop("_token_telemetry", None)
            if isinstance(token_telemetry, dict):
                token_telemetry_items.append(token_telemetry)
            results[module] = module_result
            if module_result.get("status") == "ok":
                fulfilled.append(module)
                returned.append(module)
            elif module_result.get("status") == "partial":
                returned.append(module)
                degraded.append(module)
                gap_flags.append(f"{module}_partial")
            else:
                error_type = str(module_result.get("error_type") or "UPSTREAM_BAD_GATEWAY")
                failure_types.append(error_type)
                gap_flags.append(self._module_gap_flag(module, error_type))

        if not returned:
            detail = "all requested modules failed; see module-level results in logs or retry with fewer modules"
            if failure_types and all(item == "UPSTREAM_TIMEOUT" for item in failure_types):
                return self._upstream_timeout_error(detail, True, started, request_id, tool_id="company_snapshot")
            return self._upstream_error(
                detail,
                True,
                started,
                request_id,
                tool_id="company_snapshot",
            )

        coverage = {
            "requested_modules": modules,
            "fulfilled_modules": fulfilled,
            "returned_modules": returned,
            "degraded_modules": degraded,
            "coverage_ratio": len(fulfilled) / len(modules),
            "returned_ratio": len(returned) / len(modules),
            "compensation_triggered": False,
            "gap_flags": gap_flags,
        }
        api_call_count = sum(
            0 if item.get("cache_hit_snapshot") else len(item.get("records") or [])
            for item in results.values()
            if isinstance(item, dict)
        )
        cache_hit_snapshot = bool(results) and all(
            bool(item.get("cache_hit_snapshot")) for item in results.values() if isinstance(item, dict)
        )
        partial = bool(gap_flags)
        return self._ok(
            {
                "entity": entity,
                "modules": results,
                "coverage": coverage,
            },
            started,
            {
                "tool_id": "company_snapshot",
                "api_call_count": api_call_count,
                "api_parallel_groups": len(modules),
                "cache_hit_snapshot": cache_hit_snapshot,
                "coverage_ratio": coverage["coverage_ratio"],
                "partial": partial,
                **self._merge_token_telemetry(token_telemetry_items),
            },
            request_id,
        )

    def _fetch_module(
        self,
        module: str,
        entity: dict[str, Any],
        credential: Credential,
        options: dict[str, Any],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        cache_key = self._snapshot_cache_key(credential, module, entity, options)
        cached = self.snapshot_cache.get(cache_key)
        if cached:
            return {**cached, "cache_hit_snapshot": True}

        records = []
        token_telemetry_items: list[dict[str, Any]] = []
        success_count = 0
        timeout_count = 0
        for api_id in MODULE_API_IDS[module]:
            result, token_telemetry = self._call_openapi(api_id, entity, credential, options, request_id)
            records.append(result)
            token_telemetry_items.append(token_telemetry)
            if result["status"] not in (200, 204):
                if result["status"] == 598:
                    timeout_count += 1
            else:
                success_count += 1
        if success_count == len(records):
            status = "ok"
            error_type = None
        elif success_count == 0:
            status = "error"
            error_type = "UPSTREAM_TIMEOUT" if timeout_count == len(records) else "UPSTREAM_BAD_GATEWAY"
        else:
            status = "partial"
            error_type = None
        payload = {
            "status": status,
            "records": records,
            "cache_hit_snapshot": False,
        }
        if error_type:
            payload["error_type"] = error_type
        if status == "ok":
            self.snapshot_cache.set(cache_key, payload, SNAPSHOT_OK_TTL_SECONDS)
        elif status == "partial":
            self.snapshot_cache.set(cache_key, payload, SNAPSHOT_PARTIAL_TTL_SECONDS)
        return {**payload, "_token_telemetry": self._merge_token_telemetry(token_telemetry_items)}

    def _snapshot_cache_key(
        self,
        credential: Credential,
        module: str,
        entity: dict[str, Any],
        options: dict[str, Any],
    ) -> str:
        entity_key = self._entity_keyword(entity)
        options_json = json.dumps(options, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
        options_hash = hashlib.sha1(options_json.encode("utf-8")).hexdigest()
        return f"{credential.account_id}:{credential.app_key_fingerprint}:{module}:{entity_key}:{options_hash}"

    def _call_openapi(
        self,
        api_id: int,
        entity: dict[str, Any],
        credential: Credential,
        options: dict[str, Any],
        request_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        api = self.manifest.get(api_id)
        body = self._build_body(api_id, entity, options)
        status, payload, token_telemetry = self._request_with_token_retry(
            credential,
            api.method,
            api.path,
            body,
            request_id=request_id,
            api_id=api.id,
            api_name=api.name,
        )
        return (
            {
                "api_id": api.id,
                "api_name": api.name,
                "path": api.path,
                "status": status,
                "body": payload,
            },
            token_telemetry,
        )

    def _build_body(self, api_id: int, entity: dict[str, Any], options: dict[str, Any]) -> dict[str, Any] | None:
        if api_id in {911, 912, 922, 1013}:
            return None
        keyword = self._entity_keyword(entity)
        body: dict[str, Any] = {"keyword": keyword}
        if api_id in {204, 205, 206, 503, 505, 510, 512, 523, 525, 901, 907}:
            body["current"] = int(options.get("current", 1))
            body["size"] = int(options.get("limit", 5))
        return body

    def _request_with_token_retry(
        self,
        credential: Credential,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        request_id: str | None = None,
        api_id: int | None = None,
        api_name: str | None = None,
    ) -> tuple[int, dict[str, Any], dict[str, Any]]:
        token, token_telemetry = self._get_token(credential)
        started = time.perf_counter()
        status, payload = http_json(
            method,
            f"{self.settings.base_url}{path}?access_token={quote(token)}",
            body,
            self.settings.timeout_seconds,
        )
        self._log_upstream_call(
            request_id,
            method,
            path,
            status,
            int((time.perf_counter() - started) * 1000),
            False,
            token_telemetry,
            api_id,
            api_name,
        )
        if self._is_auth_failure(status, payload):
            token, retry_telemetry = self._get_token(credential, force_refresh=True)
            retry_started = time.perf_counter()
            status, payload = http_json(
                method,
                f"{self.settings.base_url}{path}?access_token={quote(token)}",
                body,
                self.settings.timeout_seconds,
            )
            self._log_upstream_call(
                request_id,
                method,
                path,
                status,
                int((time.perf_counter() - retry_started) * 1000),
                True,
                retry_telemetry,
                api_id,
                api_name,
            )
            token_telemetry = self._merge_token_telemetry(
                [
                    token_telemetry,
                    {**retry_telemetry, "token_retry_after_401": True},
                ]
            )
            if self._is_auth_failure(status, payload):
                raise AuthError(payload.get("msg") or "openapi auth failed after token refresh")
        return status, payload, token_telemetry

    def _is_auth_failure(self, status: int, payload: dict[str, Any]) -> bool:
        return status in (401, 403) or str(payload.get("code")) in {"401", "403", "11001"}

    def _log_upstream_call(
        self,
        request_id: str | None,
        method: str,
        path: str,
        status: int,
        latency_ms: int,
        retry_after_401: bool,
        token_telemetry: dict[str, Any],
        api_id: int | None = None,
        api_name: str | None = None,
    ) -> None:
        log_event(
            "gateway.upstream_call",
            request_id=request_id,
            method=method,
            path=path,
            api_id=api_id,
            api_name=api_name,
            status=status,
            latency_ms=latency_ms,
            retry_after_401=retry_after_401,
            cache_hit_token=token_telemetry.get("cache_hit_token"),
            token_refresh_result=token_telemetry.get("token_refresh_result"),
        )

    def _validate_entity(
        self,
        entity: dict[str, Any],
        started: float,
        request_id: str | None,
        tool_id: str | None = None,
    ) -> dict[str, Any] | None:
        if not isinstance(entity, dict):
            return self._error(10001, "INVALID_ARGUMENT", "entity must be object", False, started, request_id, tool_id=tool_id)
        if not self._entity_keyword(entity):
            return self._error(
                10001,
                "INVALID_ARGUMENT",
                "entity must contain non-empty ent_name, uni_sc_id, or keyword",
                False,
                started=started,
                request_id=request_id,
                context={"required_any_of": ["ent_name", "uni_sc_id", "keyword"]},
                tool_id=tool_id,
            )
        return None

    def _normalize_options(
        self,
        options: Any,
        started: float,
        request_id: str | None,
        tool_id: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any] | None]:
        if not isinstance(options, dict):
            return {}, self._error(
                10001,
                "INVALID_ARGUMENT",
                "options must be object",
                False,
                started,
                request_id,
                tool_id=tool_id,
            )
        normalized: dict[str, Any] = {}
        for key, default, minimum, maximum in (
            ("current", 1, 1, 1000),
            ("limit", 5, 1, 100),
        ):
            value = options.get(key, default)
            if isinstance(value, bool) or not isinstance(value, int):
                return {}, self._error(
                    10001,
                    "INVALID_ARGUMENT",
                    f"options.{key} must be integer",
                    False,
                    started,
                    request_id,
                    context={"field": f"options.{key}", "minimum": minimum, "maximum": maximum},
                    tool_id=tool_id,
                )
            if value < minimum or value > maximum:
                return {}, self._error(
                    10001,
                    "INVALID_ARGUMENT",
                    f"options.{key} must be between {minimum} and {maximum}",
                    False,
                    started,
                    request_id,
                    context={"field": f"options.{key}", "minimum": minimum, "maximum": maximum},
                    tool_id=tool_id,
                )
            normalized[key] = value
        return normalized, None

    def _entity_keyword(self, entity: dict[str, Any]) -> str:
        if not isinstance(entity, dict):
            return ""
        for key in ("ent_name", "uni_sc_id", "keyword"):
            value = entity.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _merge_token_telemetry(self, telemetry_items: list[dict[str, Any]]) -> dict[str, Any]:
        items = [item for item in telemetry_items if item]
        if not items:
            return {}
        hit_count = 0
        refresh_count = 0
        refresh_results: list[str] = []
        refresh_ms = 0
        fingerprints = set()
        for item in items:
            if "token_cache_hit_count" in item or "token_refresh_count" in item:
                hit_count += int(item.get("token_cache_hit_count") or 0)
                refresh_count += int(item.get("token_refresh_count") or 0)
            elif item.get("cache_hit_token") is True:
                hit_count += 1
            else:
                refresh_count += 1
            result = item.get("token_refresh_result")
            if result and result not in refresh_results:
                refresh_results.append(str(result))
            ms = item.get("token_refresh_ms")
            if isinstance(ms, int) and not isinstance(ms, bool):
                refresh_ms += ms
            fingerprint = item.get("app_key_fingerprint")
            if fingerprint:
                fingerprints.add(str(fingerprint))

        total_count = hit_count + refresh_count
        telemetry: dict[str, Any] = {
            "cache_hit_token": total_count > 0 and hit_count == total_count,
            "token_cache_hit_count": hit_count,
            "token_refresh_count": refresh_count,
        }
        if refresh_results:
            telemetry["token_refresh_result"] = ",".join(refresh_results)
        if refresh_ms:
            telemetry["token_refresh_ms"] = refresh_ms
        if any(item.get("token_retry_after_401") for item in items):
            telemetry["token_retry_after_401"] = True
        if len(fingerprints) == 1:
            telemetry["app_key_fingerprint"] = next(iter(fingerprints))
        return telemetry

    def _get_token(self, credential: Credential, force_refresh: bool = False) -> tuple[str, dict[str, Any]]:
        def refresh() -> str:
            status, payload = http_json(
                "POST",
                f"{self.settings.base_url}/api/openapi/tokens/getToken",
                {"accessKey": credential.app_key, "secretKey": credential.app_secret},
                self.settings.timeout_seconds,
            )
            if status != 200 or str(payload.get("code")) != "200" or not payload.get("msg"):
                code = str(payload.get("code") or status)
                if status in (401, 403) or code in {"401", "403", "11001"}:
                    raise AuthError("AK/SK rejected by token service")
                if status == 598 or code == "UPSTREAM_TIMEOUT":
                    raise UpstreamTimeoutError(f"token refresh timeout: status={status}, code={code}")
                raise UpstreamError(f"token refresh failed: status={status}, code={code}")
            return str(payload["msg"])

        return self.token_cache.get_or_refresh(
            credential.account_id,
            credential.app_key_fingerprint,
            refresh,
            force_refresh=force_refresh,
        )

    def _resolve_credential(self, ctx: RequestContext | None = None) -> Credential:
        try:
            return self.credentials.resolve(ctx)
        except ValueError as exc:
            raise AuthError(str(exc)) from exc

    def _parse_entity_result(self, query: str, payload: dict[str, Any], status: int, top_k: int) -> dict[str, Any]:
        records = payload.get("records") or payload.get("data") or []
        candidates = []
        if isinstance(records, dict):
            records = records.get("records") or records.get("list") or []
        for index, item in enumerate(records[:top_k], start=1):
            candidates.append(
                {
                    "index": index,
                    "ent_name": item.get("entName") or item.get("name") or "",
                    "uni_sc_id": item.get("uniScId") or item.get("creditCode") or "",
                }
            )
        if candidates:
            return {
                "matched": True,
                "need_confirm": len(candidates) > 1,
                "entity": candidates[0],
                "candidates": candidates,
            }
        return {
            "matched": False,
            "need_confirm": False,
            "entity": None,
            "candidates": [],
            "error": {"status": status, "message": payload.get("msg") or f"entity not found: {query}"},
        }

    def _ok(
        self,
        data: dict[str, Any],
        started: float,
        telemetry: dict[str, Any],
        request_id: str | None = None,
    ) -> dict[str, Any]:
        latency_ms = int((time.perf_counter() - started) * 1000)
        telemetry = {
            "partial": False,
            "api_call_count": 0,
            "api_parallel_groups": 0,
            "cache_hit_token": False,
            "cache_hit_entity": False,
            "cache_hit_route": False,
            "cache_hit_snapshot": False,
            "coverage_ratio": None,
            **telemetry,
            "total_ms": latency_ms,
        }
        return {
            "code": 0,
            "message": "ok",
            "request_id": request_id or f"req_{uuid.uuid4().hex}",
            "data": data,
            "meta": {
                "latency_ms": latency_ms,
                "telemetry": telemetry,
            },
        }

    def _error(
        self,
        code: int,
        message: str,
        detail: str,
        retryable: bool,
        started: float | None = None,
        request_id: str | None = None,
        context: dict[str, Any] | None = None,
        tool_id: str | None = None,
    ) -> dict[str, Any]:
        latency_ms = int((time.perf_counter() - started) * 1000) if started is not None else 0
        error = {
            "type": "business",
            "detail": detail,
            "retryable": retryable,
        }
        if context:
            error["context"] = context
        return {
            "code": code,
            "message": message,
            "request_id": request_id or f"req_{uuid.uuid4().hex}",
            "error": error,
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
                }
            },
        }

    def _exception_error_type(self, exc: Exception) -> str:
        if isinstance(exc, UpstreamTimeoutError):
            return "UPSTREAM_TIMEOUT"
        return "UPSTREAM_BAD_GATEWAY"

    def _module_gap_flag(self, module: str, error_type: str) -> str:
        if error_type == "UPSTREAM_TIMEOUT":
            return f"{module}_timeout"
        return f"{module}_failed"

    def _auth_error(
        self,
        detail: str,
        started: float | None = None,
        request_id: str | None = None,
        tool_id: str | None = None,
    ) -> dict[str, Any]:
        return self._error(11001, "UNAUTHORIZED", detail, False, started, request_id, tool_id=tool_id)

    def _upstream_timeout_error(
        self,
        detail: str,
        retryable: bool,
        started: float | None = None,
        request_id: str | None = None,
        tool_id: str | None = None,
    ) -> dict[str, Any]:
        return self._error(15001, "UPSTREAM_TIMEOUT", detail, retryable, started, request_id, tool_id=tool_id)

    def _upstream_error(
        self,
        detail: str,
        retryable: bool,
        started: float | None = None,
        request_id: str | None = None,
        tool_id: str | None = None,
    ) -> dict[str, Any]:
        return self._error(15002, "UPSTREAM_BAD_GATEWAY", detail, retryable, started, request_id, tool_id=tool_id)
