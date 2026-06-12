"""Strong ETag helpers (agent card + well-known documents)."""

from __future__ import annotations

import hashlib
import json
from typing import Any


def etag_for(payload: Any) -> str:
    if not isinstance(payload, (str, bytes)):
        payload = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    if isinstance(payload, str):
        payload = payload.encode()
    return '"' + hashlib.sha256(payload).hexdigest()[:32] + '"'


def matches(if_none_match: str | None, etag: str) -> bool:
    if not if_none_match:
        return False
    candidates = [v.strip() for v in if_none_match.split(",")]
    return "*" in candidates or etag in candidates
