"""RT-012: SourceAdapter._request()'s 429/503 retry-once call must map
TimeoutException/HTTPError to AgentError exactly like the first attempt.

Before the fix, the retry call (module-level, after the first attempt's
try/except) sat unprotected — an exception on the retry escaped as a raw
httpx exception instead of the adapter's promised AgentError, leaking
``request.url`` (which carries credentials for query-param-auth upstreams
like Profit.co) into any caller that only catches AgentError.
"""

from __future__ import annotations

import httpx
import pytest

from agent_sdk.models.errors import AgentError, ErrorCategory
from agent_sdk.sources import SourceAdapter


class _ProbeSource(SourceAdapter):
    source_name = "probe"
    allowed_hosts = ["example.com"]


def _resolver(_source: str, _field: str) -> str | None:
    return None


def _adapter() -> _ProbeSource:
    return _ProbeSource(object(), _resolver)


async def test_retry_timeout_maps_to_agent_error():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503)
        raise httpx.TimeoutException("connect timed out", request=request)

    src = _adapter()
    src._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AgentError) as exc_info:
            await src.get("https://example.com/thing")
    finally:
        await src.aclose()

    assert exc_info.value.category is ErrorCategory.TIMEOUT
    assert len(calls) == 2


async def test_retry_http_error_maps_to_agent_error():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429)
        raise httpx.ConnectError("connection refused", request=request)

    src = _adapter()
    src._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        with pytest.raises(AgentError) as exc_info:
            await src.get("https://example.com/thing")
    finally:
        await src.aclose()

    assert exc_info.value.category is ErrorCategory.UPSTREAM
    assert len(calls) == 2


async def test_retry_success_returns_response():
    calls: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(503)
        return httpx.Response(200, json={"ok": True})

    src = _adapter()
    src._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    try:
        resp = await src.get("https://example.com/thing")
    finally:
        await src.aclose()

    assert resp.status_code == 200
    assert len(calls) == 2
