"""Log redaction — secrets never reach logs or error payloads (§6)."""

from __future__ import annotations

import re
from typing import Any

_SECRET_KEY = re.compile(
    r"(secret|token|password|api[_-]?key|authorization|credential|assertion|"
    r"master[_-]?key|refresh|bearer)",
    re.IGNORECASE,
)
_BEARER_VALUE = re.compile(r"(?i)\b(bearer)\s+\S+")

REDACTED = "[redacted]"


def redact_value(text: str) -> str:
    return _BEARER_VALUE.sub(r"\1 " + REDACTED, text)


def redact(obj: Any, *, _depth: int = 0) -> Any:
    """Deep-copy with secret-named keys masked. Safe for log payloads."""
    if _depth > 8:
        return REDACTED
    if isinstance(obj, dict):
        return {
            k: REDACTED if isinstance(k, str) and _SECRET_KEY.search(k) else redact(v, _depth=_depth + 1)
            for k, v in obj.items()
        }
    if isinstance(obj, (list, tuple)):
        return [redact(v, _depth=_depth + 1) for v in obj]
    if isinstance(obj, str):
        return redact_value(obj)
    return obj
