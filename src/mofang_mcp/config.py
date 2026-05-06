from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class Settings:
    base_url: str
    manifest_path: Path
    cache_dir: Path
    timeout_seconds: int
    http_host: str
    http_port: int
    http_path: str

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            base_url=os.getenv("BASE_URL", "https://openapi.qike366.com").rstrip("/"),
            manifest_path=Path(os.getenv("MOFANG_MANIFEST_PATH", PROJECT_ROOT / "data" / "api_manifest.json")),
            cache_dir=Path(os.getenv("MOFANG_CACHE_DIR", Path(tempfile.gettempdir()) / "mofang-skill-v2-cache")),
            timeout_seconds=int(os.getenv("MOFANG_HTTP_TIMEOUT_SECONDS", "30")),
            http_host=os.getenv("MOFANG_MCP_HTTP_HOST", "0.0.0.0"),
            http_port=int(os.getenv("MOFANG_MCP_HTTP_PORT", "8000")),
            http_path=os.getenv("MOFANG_MCP_HTTP_PATH", "/mcp/company/stream"),
        )

    @classmethod
    def from_file_or_env(cls, config_path: str | None = None) -> "Settings":
        env_settings = cls.from_env()
        if not config_path:
            return env_settings

        payload = _load_config_payload(Path(config_path))
        return cls(
            base_url=str(payload.get("base_url", env_settings.base_url)).rstrip("/"),
            manifest_path=Path(payload.get("manifest_path", env_settings.manifest_path)),
            cache_dir=Path(payload.get("cache_dir", env_settings.cache_dir)),
            timeout_seconds=int(payload.get("timeout_seconds", env_settings.timeout_seconds)),
            http_host=str(payload.get("http_host", env_settings.http_host)),
            http_port=int(payload.get("http_port", env_settings.http_port)),
            http_path=str(payload.get("http_path", env_settings.http_path)),
        )


def _load_config_payload(path: Path) -> dict[str, Any]:
    raw = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".json":
        payload = json.loads(raw)
    else:
        try:
            import yaml
        except ModuleNotFoundError as exc:
            raise ValueError("YAML config requires PyYAML installed") from exc
        payload = yaml.safe_load(raw)

    if not isinstance(payload, dict):
        raise ValueError("config file root must be object")
    return payload
