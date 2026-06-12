"""Request-id propagation (contextvar; no external tracing dependency)."""

from __future__ import annotations

import uuid
from contextvars import ContextVar
from typing import Any, Awaitable, Callable

_request_id: ContextVar[str | None] = ContextVar("agent_sdk_request_id", default=None)


def current_request_id() -> str | None:
    return _request_id.get()


async def request_id_middleware(request: Any, call_next: Callable[[Any], Awaitable[Any]]) -> Any:
    """FastAPI http middleware: honors inbound X-Request-Id, else mints one;
    always echoes it on the response."""
    rid = request.headers.get("x-request-id") or uuid.uuid4().hex
    token = _request_id.set(rid)
    try:
        response = await call_next(request)
    finally:
        _request_id.reset(token)
    response.headers["X-Request-Id"] = rid
    return response
