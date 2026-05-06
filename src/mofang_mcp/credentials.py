from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from typing import Mapping


DEFAULT_ACCOUNT_ID = "default"


@dataclass(frozen=True)
class RequestContext:
    request_id: str | None = None
    session_id: str | None = None
    headers: Mapping[str, str] | None = None
    app_key: str | None = None
    app_secret: str | None = None
    transport: str = "stdio"


@dataclass(frozen=True)
class Credential:
    account_id: str
    app_key: str
    app_secret: str

    @property
    def app_key_fingerprint(self) -> str:
        return hashlib.sha256(self.app_key.encode("utf-8")).hexdigest()[:12]


class CredentialResolver:
    def __init__(self) -> None:
        self._credential = self._load_credential()

    def resolve(self, ctx: RequestContext | None = None) -> Credential:
        contextual = self._load_context_credential(ctx)
        if contextual:
            return contextual
        if not self._credential:
            raise ValueError("APP_ACCESS_KEY and APP_SECRET_KEY are required")
        return self._credential

    def _load_context_credential(self, ctx: RequestContext | None) -> Credential | None:
        if ctx is None:
            return None
        app_key = (ctx.app_key or "").strip()
        app_secret = (ctx.app_secret or "").strip()
        headers = {str(k).lower(): str(v) for k, v in (ctx.headers or {}).items()}
        if not app_key:
            app_key = headers.get("x-app-access-key", "").strip()
        if not app_secret:
            app_secret = headers.get("x-app-secret-key", "").strip()
        if app_key and app_secret:
            return Credential(DEFAULT_ACCOUNT_ID, app_key, app_secret)
        return None

    def _load_credential(self) -> Credential | None:
        app_key = os.getenv("APP_ACCESS_KEY", "")
        app_secret = os.getenv("APP_SECRET_KEY", "")
        if app_key and app_secret:
            return Credential(DEFAULT_ACCOUNT_ID, app_key, app_secret)
        return None
