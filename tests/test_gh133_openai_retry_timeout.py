"""GH-133: max_retries/timeout must reach the underlying OpenAI client.

SourceAdapter._request() (agent_sdk/sources.py:151-154) retries once on
429/503 for tool-facing outbound HTTP. OpenAIModelClient has no equivalent
retry policy of its own — GH-94/w028 only distinguished RATE_LIMITED from
UPSTREAM, it never added retries. This closes the actual GH-133 ask: expose
`max_retries`/`timeout` so a caller can opt the underlying AsyncOpenAI /
AsyncAzureOpenAI client into its own native retry behavior.

No MagicMock/AsyncMock: sys.modules["openai"] is replaced with a minimal fake
module (plain classes, not mocks) so _openai_client() runs its real
construction path without requiring the openai package to be installed.
"""

from __future__ import annotations

import sys
import types

from agent_sdk.agent.openai_client import OpenAIModelClient


class _FakeAsyncOpenAI:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


class _FakeAsyncAzureOpenAI:
    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs


def _install_fake_openai(monkeypatch) -> None:
    fake = types.ModuleType("openai")
    fake.AsyncOpenAI = _FakeAsyncOpenAI  # type: ignore[attr-defined]
    fake.AsyncAzureOpenAI = _FakeAsyncAzureOpenAI  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake)


def test_max_retries_and_timeout_reach_async_openai(monkeypatch):
    _install_fake_openai(monkeypatch)
    client = OpenAIModelClient(
        model="gpt-5", api_key="sk-fake", max_retries=5, timeout=12.5
    )

    raw = client._openai_client()

    assert raw.kwargs["max_retries"] == 5
    assert raw.kwargs["timeout"] == 12.5


def test_max_retries_and_timeout_reach_async_azure_openai(monkeypatch):
    _install_fake_openai(monkeypatch)
    client = OpenAIModelClient(
        model="gpt-5",
        api_key="sk-fake",
        azure_endpoint="https://my-resource.openai.azure.com/",
        azure_api_version="2024-02-01",
        max_retries=3,
        timeout=7.0,
    )

    raw = client._openai_client()

    assert raw.kwargs["max_retries"] == 3
    assert raw.kwargs["timeout"] == 7.0


def test_defaults_omit_max_retries_and_timeout_kwargs(monkeypatch):
    """Unset max_retries/timeout must not be forwarded as explicit None —
    that would override the underlying SDK client's own defaults."""
    _install_fake_openai(monkeypatch)
    client = OpenAIModelClient(model="gpt-5", api_key="sk-fake")

    raw = client._openai_client()

    assert "max_retries" not in raw.kwargs
    assert "timeout" not in raw.kwargs
