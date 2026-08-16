"""GH-94: openai.RateLimitError must map to ErrorCategory.RATE_LIMITED, not UPSTREAM.

Tests use monkeypatch to inject errors without unittest.mock / MagicMock / AsyncMock.
httpx.Response is used directly (real class, no mock) to simulate Retry-After headers.

`openai` is an optional extra (pyproject.toml `[project.optional-dependencies]`) and
is not part of the `dev` extra the SDK test gate installs (sdk-test SKILL.md Leg 1:
`uv pip install -e ".[dev]"`), so it is not guaranteed to be importable in a dev venv.
`pytest.importorskip("openai")` below skips this whole module cleanly when the
optional extra is absent, so every test constructs REAL `openai.RateLimitError` /
`openai.APIConnectionError` instances against the actual installed package
(RT-007) — no hand-written fake exception hierarchy standing in for it, which
would let a real signature or `isinstance` mismatch go unnoticed. Only the
`.chat.completions.create()` call surface is stubbed (via `_patch_client`,
monkeypatching `OpenAIModelClient._openai_client` on the instance under test)
so the raised exception can be injected without a live network call.
"""

from __future__ import annotations

import inspect
from typing import Any

import httpx
import pytest
import pytest_asyncio  # noqa: F401 — imported for plugin registration

from agent_sdk.agent.openai_client import OpenAIModelClient
from agent_sdk.models.errors import AgentError, ErrorCategory

openai = pytest.importorskip("openai")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FAKE_REQUEST = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")

_CONVERSE_KWARGS: dict[str, Any] = {
    "system": "test",
    "messages": [{"role": "user", "content": [{"text": "hi"}]}],
    "tools": [],
}


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

    async def create(self, **_kwargs):
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
    exc = openai.APIConnectionError(request=_FAKE_REQUEST)
    client = _make_client()
    _patch_client(monkeypatch, client, exc)

    with pytest.raises(AgentError) as ei:
        await _converse(client)

    assert ei.value.category == ErrorCategory.UPSTREAM


@pytest.mark.asyncio
async def test_retry_after_extracted(monkeypatch):
    """Retry-After header value is extracted into AgentError.detail."""
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


# ---------------------------------------------------------------------------
# RT-007: dependency-floor probe (LRN-084 pattern), non-faked
# ---------------------------------------------------------------------------


def test_async_openai_accepts_max_retries_and_timeout():
    """openai.AsyncOpenAI must accept max_retries/timeout at the declared floor.

    GH-133's OpenAIModelClient forwards max_retries/timeout verbatim into this
    constructor. Every test pinning that forwarding
    (test_gh133_openai_retry_timeout.py, test_rt009_openai_max_retries_timeout_seam.py)
    does so against a hand-written fake AsyncOpenAI that accepts any kwarg — it
    would stay green even if the real SDK renamed or dropped the parameter.
    This probes the real constructor signature directly (LRN-084's
    `assert hasattr(...)` floor-probe pattern, applied to a constructor param
    instead of a module attribute).
    """
    params = inspect.signature(openai.AsyncOpenAI.__init__).parameters
    assert "max_retries" in params, (
        "openai.AsyncOpenAI no longer accepts max_retries — raise the openai "
        "floor in pyproject.toml to a version that restores it"
    )
    assert "timeout" in params, (
        "openai.AsyncOpenAI no longer accepts timeout — raise the openai floor "
        "in pyproject.toml to a version that restores it"
    )


def test_async_azure_openai_accepts_max_retries_and_timeout():
    """Same floor probe for the Azure OpenAI backend's constructor."""
    params = inspect.signature(openai.AsyncAzureOpenAI.__init__).parameters
    assert "max_retries" in params, (
        "openai.AsyncAzureOpenAI no longer accepts max_retries — raise the "
        "openai floor in pyproject.toml to a version that restores it"
    )
    assert "timeout" in params, (
        "openai.AsyncAzureOpenAI no longer accepts timeout — raise the openai "
        "floor in pyproject.toml to a version that restores it"
    )
