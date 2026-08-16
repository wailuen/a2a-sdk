"""RT-009: openai_max_retries/openai_timeout settings must reach the client
built by Agent._build_model_client(), not just OpenAIModelClient.__init__().

GH-133 added max_retries/timeout kwargs to OpenAIModelClient and pinned them
with a unit test (test_gh133_openai_retry_timeout.py) that constructs the
client directly. Nothing in BaseAgentSettings or _build_model_client ever
forwarded them, so every settings-driven deployment silently kept the openai
SDK's default max_retries=2 — the sustained-throttling failure GH-133 reports
was unchanged. This is the seam test LRN-077 requires: it must fail if the
wiring from settings to constructor is ever missing again.

RT-005: the env aliases are AGENT_SDK_OPENAI_MAX_RETRIES/AGENT_SDK_OPENAI_TIMEOUT
(reserved-prefix rename from the original bare OPENAI_MAX_RETRIES/OPENAI_TIMEOUT,
DESIGN.md §4.0). The bare-name regression test below pins that the old aliases
are no longer recognized.
"""

from __future__ import annotations

import sys
import types

from agent_sdk import BaseAgentSettings
from agent_sdk.agent.openai_client import OpenAIModelClient
from agent_sdk.app import Agent
from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore

_MK = "test-master-key-padded-to-32-chars!!"


def _store(tmp_path):
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    return EncryptedSqliteStore(data_dir / "credentials.db", _MK)


def _install_fake_openai(monkeypatch) -> None:
    # openai is an optional extra; _build_model_client only checks it is
    # importable (agent_sdk/app.py's `import openai as _openai_pkg`), it
    # never touches attributes on the module at this seam.
    monkeypatch.setitem(sys.modules, "openai", types.ModuleType("openai"))


def test_build_model_client_forwards_openai_max_retries_and_timeout(monkeypatch, tmp_path):
    _install_fake_openai(monkeypatch)
    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        OPENAI_MODEL="gpt-5",
        AGENT_SDK_OPENAI_MAX_RETRIES=5,
        AGENT_SDK_OPENAI_TIMEOUT=12.5,
    )
    store = _store(tmp_path)
    try:
        agent = Agent(settings=settings, persona="Test agent.")
        mc = agent._build_model_client(store)
        assert isinstance(mc, OpenAIModelClient)
        assert mc._max_retries == 5
        assert mc._timeout == 12.5
    finally:
        store.close()


def test_bare_openai_max_retries_and_timeout_aliases_no_longer_recognized(
    monkeypatch, tmp_path
):
    _install_fake_openai(monkeypatch)
    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        OPENAI_MODEL="gpt-5",
        OPENAI_MAX_RETRIES=5,
        OPENAI_TIMEOUT=12.5,
    )
    store = _store(tmp_path)
    try:
        agent = Agent(settings=settings, persona="Test agent.")
        mc = agent._build_model_client(store)
        assert isinstance(mc, OpenAIModelClient)
        assert mc._max_retries is None
        assert mc._timeout is None
    finally:
        store.close()


def test_build_model_client_omits_openai_max_retries_and_timeout_by_default(monkeypatch, tmp_path):
    _install_fake_openai(monkeypatch)
    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        OPENAI_MODEL="gpt-5",
    )
    store = _store(tmp_path)
    try:
        agent = Agent(settings=settings, persona="Test agent.")
        mc = agent._build_model_client(store)
        assert isinstance(mc, OpenAIModelClient)
        assert mc._max_retries is None
        assert mc._timeout is None
    finally:
        store.close()
