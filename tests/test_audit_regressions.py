"""Regression tests for agent_sdk/ code-audit findings."""

from __future__ import annotations

import json

import pytest

from agent_sdk import Agent, BaseAgentSettings
from agent_sdk.agent.registry import ToolSet
from agent_sdk.auth.api_keys import ApiKeyStore
from agent_sdk.credentials.store import CredentialStore, resolver_for_source
from agent_sdk.sources import SourceAdapter


class CountingStore(CredentialStore):
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], str] = {}
        self.list_calls = 0

    def get(self, namespace: str, field: str) -> str | None:
        return self.values.get((namespace, field))

    def set(self, namespace: str, field: str, value: str) -> None:
        self.values[(namespace, field)] = value

    def delete(self, namespace: str, field: str) -> None:
        self.values.pop((namespace, field), None)

    def list_fields(self, namespace: str) -> list[str]:
        self.list_calls += 1
        return sorted(field for ns, field in self.values if ns == namespace)

    def close(self) -> None:
        pass


def test_malformed_api_key_does_not_scan_store() -> None:
    store = CountingStore()
    keys = ApiKeyStore(store)
    keys.mint("admin", admin=True)
    store.list_calls = 0

    assert keys.verify("not-an-api-key") is None
    assert keys.verify("ak_bad") is None
    assert store.list_calls == 0


def test_valid_api_key_still_verifies() -> None:
    store = CountingStore()
    keys = ApiKeyStore(store)
    key_id, plaintext = keys.mint("admin", admin=True)

    identity = keys.verify(plaintext)

    assert identity is not None
    assert identity.subject == key_id
    assert json.loads(store.get("__api_keys__", key_id) or "{}")["last_used"] is not None


def test_tool_required_keyword_parameter_rejected() -> None:
    tools = ToolSet()

    with pytest.raises(TypeError, match="required keyword-only parameter"):

        @tools.tool()
        async def bad_tool(*, required: str) -> str:
            return required


def test_tool_required_positional_parameter_rejected() -> None:
    tools = ToolSet()

    with pytest.raises(TypeError, match="required positional parameter"):

        @tools.tool()
        async def bad_tool(required: str) -> str:
            return required


def test_tool_varargs_rejected() -> None:
    tools = ToolSet()

    with pytest.raises(TypeError, match="not supported"):

        @tools.tool()
        async def bad_tool(**kwargs: object) -> str:
            return str(kwargs)


def test_invalid_source_name_rejected_by_resolver() -> None:
    with pytest.raises(ValueError, match="source_name must match"):
        resolver_for_source(CountingStore(), "bad'name")


def test_invalid_source_name_rejected_at_registration(tmp_path) -> None:
    class BadSource(SourceAdapter):
        source_name = "bad'name"
        allowed_hosts = ["example.com"]

    agent = Agent(
        settings=BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path)),
        persona="test",
    )

    with pytest.raises(ValueError, match="source_name must match"):
        agent.register_source(BadSource)
