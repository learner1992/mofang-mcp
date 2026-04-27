from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def http_json(method: str, url: str, body: dict[str, Any] | None, timeout: int) -> tuple[int, dict[str, Any]]:
    data = None
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method=method.upper(),
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            payload = resp.read().decode("utf-8", "replace")
            return resp.status, json.loads(payload) if payload else {}
    except (TimeoutError, socket.timeout) as exc:
        return 598, {"code": "UPSTREAM_TIMEOUT", "msg": str(exc)}
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", "replace")
        try:
            return exc.code, json.loads(payload)
        except Exception:
            return exc.code, {"code": str(exc.code), "msg": payload}
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            return 598, {"code": "UPSTREAM_TIMEOUT", "msg": str(exc.reason)}
        return 599, {"code": "UPSTREAM_BAD_GATEWAY", "msg": str(exc.reason)}


def quote(value: str) -> str:
    return urllib.parse.quote(value, safe="")
