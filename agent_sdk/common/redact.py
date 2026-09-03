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

# SI-2: map every Unicode control char to a space — C0 (0x00-0x1F), DEL
# (0x7F) and C1 (0x80-0x9F). C1 is not optional: NEL (0x85) is treated as a
# line break by many log/terminal consumers and CSI (0x9B) is a single-byte
# ANSI escape introducer equivalent to ESC '[', so leaving 0x7F/C1 through
# would defeat the very log/terminal-injection guard this helper exists for.
_CONTROL_CHAR_MAP = dict.fromkeys([*range(0x20), 0x7F, *range(0x80, 0xA0)], " ")


def sanitize_text(s: str, *, max_len: int = 64) -> str:
    """Strip control chars and cap length before untrusted (caller-/model-/
    tool-supplied) text reaches a log line or the wire (SI-2). C-007."""
    return s[:max_len].translate(_CONTROL_CHAR_MAP)


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
