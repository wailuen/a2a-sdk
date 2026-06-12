"""SSE framing helpers.

Both streaming surfaces use bare ``data:`` frames (no ``event:`` line —
AG-UI clients dispatch on the JSON ``type`` field, A2A on ``kind``).
"""

from __future__ import annotations

import json
from typing import Any

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

HEARTBEAT = b": ping\n\n"


def sse_data(obj: Any) -> bytes:
    """One SSE frame. ``obj`` must already be wire-shaped (camelCase done
    by the caller's model dump)."""
    if not isinstance(obj, str):
        obj = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)
    return f"data: {obj}\n\n".encode()
