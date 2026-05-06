from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path


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
