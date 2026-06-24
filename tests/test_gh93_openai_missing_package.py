"""GH-93: openai package undeclared — ModuleNotFoundError must not be swallowed.

ACs verified:
  1. build_app() with OPENAI_MODEL set but openai not installed raises ImportError
     with 'agent-sdk[openai]' in the message (startup check path).
  2. converse() with _openai_client raising ModuleNotFoundError propagates
     ModuleNotFoundError, not AgentError (deferred-import propagation path).
"""
from __future__ import annotations

import sys

import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.app import Agent
from agent_sdk.agent.openai_client import OpenAIModelClient


# ---------------------------------------------------------------------------
# AC-1: startup check — build_app() raises ImportError when openai is absent
# ---------------------------------------------------------------------------


def test_build_app_raises_import_error_when_openai_missing(monkeypatch, tmp_path):
    """build_app() must raise ImportError (not crash cryptically) when OPENAI_MODEL
    is set but the openai package is not installed.

    Simulate a missing package by inserting None into sys.modules['openai'];
    Python's import machinery treats this as a blocked import and raises
    ModuleNotFoundError. monkeypatch restores sys.modules automatically after
    the test.
    """
    # Block the openai import at the sys.modules level.
    monkeypatch.setitem(sys.modules, "openai", None)

    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        OPENAI_MODEL="gpt-4o",
    )
    agent = Agent(settings=settings, persona="You are a test agent.")

    with pytest.raises(ImportError, match="agent-sdk\\[openai\\]"):
        agent.build_app()


def test_build_app_raises_import_error_azure_when_openai_missing(monkeypatch, tmp_path):
    """Same check for the Azure OpenAI backend (AZURE_OPENAI_ENDPOINT)."""
    monkeypatch.setitem(sys.modules, "openai", None)

    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        AZURE_OPENAI_ENDPOINT="https://my-resource.openai.azure.com/",
        AZURE_OPENAI_DEPLOYMENT="gpt-4o",
    )
    agent = Agent(settings=settings, persona="You are a test agent.")

    with pytest.raises(ImportError, match="agent-sdk\\[openai\\]"):
        agent.build_app()


# ---------------------------------------------------------------------------
# AC-2: converse() propagation — ModuleNotFoundError must not become AgentError
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_converse_propagates_module_not_found(monkeypatch):
    """converse() must let ModuleNotFoundError propagate unmodified.

    Monkeypatch _openai_client to raise ModuleNotFoundError so we exercise the
    except ModuleNotFoundError: raise guard without actually needing to uninstall
    the openai package.
    """
    client = OpenAIModelClient(model="gpt-4o", api_key="fake-key")

    def _raise_mnfe():
        raise ModuleNotFoundError("No module named 'openai'")

    monkeypatch.setattr(client, "_openai_client", _raise_mnfe)

    with pytest.raises(ModuleNotFoundError):
        await client.converse(
            system="You are a test agent.",
            messages=[{"role": "user", "content": [{"text": "hello"}]}],
            tools=[],
        )
