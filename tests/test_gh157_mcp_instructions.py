"""GH-157: agent-authored text in MCP ``initialize.instructions``."""

from __future__ import annotations

import gc
from pathlib import Path

import httpx
import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.app import Agent
from agent_sdk.testing import FakeModelClient


def _settings(tmp_path: Path) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent"
    )


def _artifacts(tmp_path: Path, mcp: str | None = None, system: str = "You are {{ agent_name }}.") -> Path:
    d = tmp_path / "artifacts"
    d.mkdir()
    (d / "system.md").write_text(system, encoding="utf-8")
    if mcp is not None:
        (d / "mcp_instructions.md").write_text(mcp, encoding="utf-8")
    return d


def _agent(tmp_path: Path, **kw):
    return Agent(settings=_settings(tmp_path), model_client=FakeModelClient(), **kw)


async def _init(app) -> dict:
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("t", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            r = await c.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
                },
            )
    assert r.status_code == 200, r.text
    app.state.credential_store.close()
    gc.collect()
    return r.json()["result"]


async def test_artifact_present(tmp_path):
    d = _artifacts(tmp_path, mcp="  Rules for {{ agent_name }} v{{ agent_version }}.\n")
    app = _agent(tmp_path, artifacts_dir=d).build_app()
    assert app.state.mcp_instructions.startswith("Rules for test-agent v")
    res = await _init(app)
    assert res["instructions"] == app.state.mcp_instructions


async def test_artifact_absent_key_omitted(tmp_path):
    app = _agent(tmp_path, artifacts_dir=_artifacts(tmp_path)).build_app()
    assert not app.state.mcp_instructions
    assert "instructions" not in await _init(app)


async def test_kwarg_with_persona(tmp_path):
    app = _agent(tmp_path, persona="p", mcp_instructions="  Be terse.  ").build_app()
    assert app.state.mcp_instructions == "Be terse."
    assert (await _init(app))["instructions"] == "Be terse."


def test_both_set_is_error(tmp_path):
    d = _artifacts(tmp_path, mcp="x")
    agent = _agent(tmp_path, artifacts_dir=d, mcp_instructions="y")
    with pytest.raises(ValueError, match="mcp_instructions"):
        agent.build_app()


async def test_joined_with_credential_note(tmp_path):
    from agent_sdk.example.agent import make_agent

    agent = make_agent(_settings(tmp_path), model_client=FakeModelClient())
    agent.mcp_instructions = "Agent rule."
    app = agent.build_app()
    app.state.credential_fields = {"s": [type("F", (), {"name": "api_key"})()]}
    res = await _init(app)
    note, _, agent_text = res["instructions"].partition("\n\n")
    assert "vendor API credentials" in note
    assert agent_text == "Agent rule."


def test_over_cap_is_error(tmp_path):
    agent = _agent(tmp_path, persona="p", mcp_instructions="a" * 4001)
    with pytest.raises(ValueError, match="4000"):
        agent.build_app()


def test_exactly_cap_ok(tmp_path):
    app = _agent(tmp_path, persona="p", mcp_instructions="a" * 4000).build_app()
    assert len(app.state.mcp_instructions) == 4000
    app.state.credential_store.close()


def test_undefined_variable_is_error(tmp_path):
    d = _artifacts(tmp_path, mcp="Hello {{ nope }}")
    with pytest.raises(Exception, match="nope"):
        _agent(tmp_path, artifacts_dir=d).build_app()


async def test_unauthenticated_initialize_gets_no_instructions(tmp_path):
    app = _agent(tmp_path, persona="p", mcp_instructions="Secret-ish agent rules.").build_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            r = await c.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
                },
            )
    app.state.credential_store.close()
    gc.collect()
    assert r.status_code == 401
    assert "Secret-ish agent rules" not in r.text


def test_secret_value_in_artifact_rendering_fails_build(tmp_path):
    from pydantic import SecretStr

    d = _artifacts(tmp_path, mcp="Token: {{ tok }}")
    agent = _agent(tmp_path, artifacts_dir=d, artifact_vars={"tok": "hunter2-value-0123456789-0123456789-xyz"})
    agent.settings.master_key = SecretStr("hunter2-value-0123456789-0123456789-xyz")
    with pytest.raises(ValueError) as exc:
        agent.build_app()
    assert "master_key" in str(exc.value)
    assert "hunter2-value-0123456789-0123456789-xyz" not in str(exc.value)
