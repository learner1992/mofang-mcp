from __future__ import annotations

import json
import os
import sys
import time
from typing import Any


def log_event(event: str, **fields: Any) -> None:
    if os.getenv("MOFANG_JSON_LOGS", "1").lower() in {"0", "false", "no", "off"}:
        return
    payload = {
        "ts": int(time.time() * 1000),
        "event": event,
        **{key: value for key, value in fields.items() if value is not None},
    }
    sys.stderr.write(json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n")
    sys.stderr.flush()
