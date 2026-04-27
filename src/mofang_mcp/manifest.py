from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class ApiDef:
    id: int
    name: str
    category: str
    path: str
    method: str
    body_params: list[dict[str, Any]]


class Manifest:
    def __init__(self, path: Path) -> None:
        raw = json.loads(path.read_text(encoding="utf-8"))
        self.by_id: dict[int, ApiDef] = {}
        for item in raw:
            api = ApiDef(
                id=int(item["id"]),
                name=str(item["name"]),
                category=str(item.get("category", "")),
                path=str(item["path"]),
                method=str(item.get("method", "POST")).upper(),
                body_params=list(item.get("body_params", [])),
            )
            self.by_id[api.id] = api

    def get(self, api_id: int) -> ApiDef:
        return self.by_id[api_id]

