"""GH-94: openai.RateLimitError must map to ErrorCategory.RATE_LIMITED, not UPSTREAM.

Tests use monkeypatch to inject errors without unittest.mock / MagicMock / AsyncMock.
httpx.Response is used directly (real class, no mock) to simulate Retry-After headers.
"""

from __future__ import annotations

import pytest
import pytest_asyncio  # noqa: F401 — imported for plugin registration

import httpx

from agent_sdk.agent.openai_client import OpenAIModelClient
from agent_sdk.models.errors import AgentError, ErrorCategory


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")

_CONVERSE_KWARGS = dict(
    system="test",
    messages=[{"role": "user", "content": [{"text": "hi"}]}],
    tools=[],
)


def _make_client() -> OpenAIModelClient:
    """Return a client instance that will never actually hit the network."""
    return OpenAIModelClient(model="gpt-test", api_key="sk-fake")


async def _converse(client: OpenAIModelClient) -> None:
    """Helper that calls converse() with minimal valid args."""
    await client.converse(**_CONVERSE_KWARGS)


# ---------------------------------------------------------------------------
# Fixtures: inject openai errors via monkeypatching _openai_client()
# ---------------------------------------------------------------------------

class _FakeCompletions:
    """Minimal stand-in that raises the error we want on .create()."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    async def create(self, **_kwargs):  # noqa: D102
        raise self._exc


class _FakeChatObj:
    def __init__(self, exc: Exception) -> None:
        self.completions = _FakeCompletions(exc)


class _FakeOpenAIClientObj:
    """Mimics the openai async client's .chat property."""

    def __init__(self, exc: Exception) -> None:
        self.chat = _FakeChatObj(exc)


def _patch_client(monkeypatch, client: OpenAIModelClient, exc: Exception) -> None:
    """Make client._openai_client() return a fake object that raises *exc*."""
    monkeypatch.setattr(client, "_openai_client", lambda: _FakeOpenAIClientObj(exc))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limit_raises_rate_limited_category(monkeypatch):
    """RateLimitError maps to ErrorCategory.RATE_LIMITED."""
    import openai

    exc = openai.RateLimitError(
        "rate limit", response=httpx.Response(429, request=_FAKE_REQUEST), body=None
    )
    client = _make_client()
    _patch_client(monkeypatch, client, exc)

    with pytest.raises(AgentError) as ei:
        await _converse(client)

    err = ei.value
    assert err.category == ErrorCategory.RATE_LIMITED
    assert err.message == "model rate limit exceeded; retry later"


@pytest.mark.asyncio
async def test_rate_limit_not_upstream(monkeypatch):
    """RateLimitError must NOT map to ErrorCategory.UPSTREAM."""
    import openai

    exc = openai.RateLimitError(
        "rate limit", response=httpx.Response(429, request=_FAKE_REQUEST), body=None
    )
    client = _make_client()
    _patch_client(monkeypatch, client, exc)

    with pytest.raises(AgentError) as ei:
        await _converse(client)

    assert ei.value.category != ErrorCategory.UPSTREAM


@pytest.mark.asyncio
async def test_fatal_error_still_upstream(monkeypatch):
    """Non-RateLimitError exceptions still produce ErrorCategory.UPSTREAM."""
    import openai

    exc = openai.APIConnectionError(request=_FAKE_REQUEST)
    client = _make_client()
    _patch_client(monkeypatch, client, exc)

    with pytest.raises(AgentError) as ei:
        await _converse(client)

    assert ei.value.category == ErrorCategory.UPSTREAM


@pytest.mark.asyncio
async def test_retry_after_extracted(monkeypatch):
    """Retry-After header value is extracted into AgentError.detail."""
    import openai

    resp = httpx.Response(429, headers={"retry-after": "30"}, request=_FAKE_REQUEST)
    exc = openai.RateLimitError("rate limit", response=resp, body=None)
    client = _make_client()
    _patch_client(monkeypatch, client, exc)

    with pytest.raises(AgentError) as ei:
        await _converse(client)

    err = ei.value
    assert err.category == ErrorCategory.RATE_LIMITED
    assert err.detail.get("retry_after") == 30


@pytest.mark.asyncio
async def test_retry_after_absent_gives_no_detail(monkeypatch):
    """When no Retry-After header, detail does not contain retry_after."""
    import openai

    resp = httpx.Response(429, request=_FAKE_REQUEST)
    exc = openai.RateLimitError("rate limit", response=resp, body=None)
    client = _make_client()
    _patch_client(monkeypatch, client, exc)

    with pytest.raises(AgentError) as ei:
        await _converse(client)

    err = ei.value
    assert err.category == ErrorCategory.RATE_LIMITED
    # detail may be empty dict (AgentError normalises None→{}), never has retry_after key
    assert "retry_after" not in err.detail
