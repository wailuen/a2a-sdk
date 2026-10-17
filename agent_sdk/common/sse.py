"""SSE framing helpers.

Both streaming surfaces use bare ``data:`` frames (no ``event:`` line —
AG-UI clients dispatch on the JSON ``type`` field, A2A on ``kind``).
"""

from __future__ import annotations

from typing import Any

from .json_strict import dumps_strict

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

HEARTBEAT = b": ping\n\n"

# Idle gap after which a stream sends HEARTBEAT. Read as ``sse.STREAM_HEARTBEAT_SECONDS``
# at call time so tests can patch it.
STREAM_HEARTBEAT_SECONDS = 15.0


def sse_data(obj: Any) -> bytes:
    """One SSE frame. ``obj`` must already be wire-shaped (camelCase done
    by the caller's model dump)."""
    if not isinstance(obj, str):
        obj = dumps_strict(obj)
    return f"data: {obj}\n\n".encode()
