from __future__ import annotations

import fcntl
import json
import os
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REFRESH_AHEAD_SECONDS = 300


@dataclass
class CacheEntry:
    value: Any
    expire_at: int


class TTLMemoryCache:
    def __init__(self) -> None:
        self._data: dict[str, CacheEntry] = {}
        self._lock = threading.Lock()

    def get(self, key: str) -> Any | None:
        with self._lock:
            entry = self._data.get(key)
            if not entry:
                return None
            if entry.expire_at <= int(time.time()):
                self._data.pop(key, None)
                return None
            return entry.value

    def set(self, key: str, value: Any, ttl_seconds: int) -> None:
        with self._lock:
            self._data[key] = CacheEntry(value=value, expire_at=int(time.time()) + ttl_seconds)


class TokenCache:
    def __init__(self, cache_dir: Path) -> None:
        self.cache_dir = cache_dir
        self.cache_file = cache_dir / "token_cache.json"
        self.lock_file = cache_dir / "token_cache.lock"
        self._process_cache: dict[str, dict[str, Any]] = {}

    @contextmanager
    def _file_lock(self):
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        with open(self.lock_file, "a+", encoding="utf-8") as fh:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)

    def get_or_refresh(
        self,
        account_id: str,
        app_key_fingerprint: str,
        refresh_fn,
        force_refresh: bool = False,
    ) -> tuple[str, dict[str, Any]]:
        key = f"token:{account_id}:{app_key_fingerprint}"
        if not force_refresh:
            entry = self._get_entry(key)
            if self._is_usable(entry):
                return str(entry["access_token"]), {
                    "cache_hit_token": True,
                    "token_refresh_result": "cache_hit",
                    "app_key_fingerprint": entry.get("app_key_fingerprint", app_key_fingerprint),
                }

        with self._file_lock():
            if not force_refresh:
                entry = self._get_entry(key)
                if self._is_usable(entry):
                    return str(entry["access_token"]), {
                        "cache_hit_token": True,
                        "token_refresh_result": "cache_hit_after_lock",
                        "app_key_fingerprint": entry.get("app_key_fingerprint", app_key_fingerprint),
                    }
            started = time.perf_counter()
            token = refresh_fn()
            refresh_ms = int((time.perf_counter() - started) * 1000)
            now = int(time.time())
            entry = {
                "access_token": token,
                "expire_at": now + 3600,
                "refresh_at": now + 3600 - REFRESH_AHEAD_SECONDS,
                "app_key_fingerprint": app_key_fingerprint,
            }
            self._set_entry(key, entry)
            return token, {
                "cache_hit_token": False,
                "token_refresh_result": "force_refresh" if force_refresh else "refresh",
                "token_refresh_ms": refresh_ms,
                "app_key_fingerprint": app_key_fingerprint,
            }

    def _is_usable(self, entry: dict[str, Any] | None) -> bool:
        if not entry:
            return False
        now = int(time.time())
        return (
            bool(entry.get("access_token"))
            and int(entry.get("expire_at", 0)) > now
            and int(entry.get("refresh_at", 0)) > now
        )

    def _get_entry(self, key: str) -> dict[str, Any] | None:
        entry = self._process_cache.get(key)
        if entry:
            return entry
        file_cache = self._load_file_cache()
        entry = file_cache.get(key)
        if entry:
            self._process_cache[key] = entry
        return entry

    def _set_entry(self, key: str, entry: dict[str, Any]) -> None:
        self._process_cache[key] = entry
        file_cache = self._load_file_cache()
        file_cache[key] = entry
        self._save_file_cache(file_cache)

    def _load_file_cache(self) -> dict[str, dict[str, Any]]:
        if not self.cache_file.exists():
            return {}
        try:
            return json.loads(self.cache_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_file_cache(self, cache: dict[str, dict[str, Any]]) -> None:
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.cache_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(cache, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.cache_file)
