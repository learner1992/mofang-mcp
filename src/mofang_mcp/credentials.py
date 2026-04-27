from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass


DEFAULT_ACCOUNT_ID = "default"


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

    def resolve(self) -> Credential:
        if not self._credential:
            raise ValueError("APP_ACCESS_KEY and APP_SECRET_KEY are required")
        return self._credential

    def _load_credential(self) -> Credential | None:
        app_key = os.getenv("APP_ACCESS_KEY", "")
        app_secret = os.getenv("APP_SECRET_KEY", "")
        if app_key and app_secret:
            return Credential(DEFAULT_ACCOUNT_ID, app_key, app_secret)
        return None
