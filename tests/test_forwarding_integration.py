"""End-to-end: X-Agent-Credentials reaches a real tool's adapter on BOTH the
A2A worker path and the MCP tools/call path; absent → store fallback.

The probe tool reports only a boolean match (its declared ``expected`` vs the
resolved key) — it never returns the credential itself, so even the test wire
carries no secret. Resolution is observed on the singleton adapter.
"""

from __future__ import annotations

import base64
import json
import uuid
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from agent_sdk import Agent, BaseAgentSettings, CredentialField, SourceAdapter
from agent_sdk.agent.registry import ToolSet
from agent_sdk.testing import FakeModelClient, reply, tool_call

probe_tools = ToolSet()


class ProbeSource(SourceAdapter):
    source_name = "probe"
    allowed_hosts: list[str] = []

    def __init__(self, settings: Any, resolver: Any, **_kw: Any) -> None:
        super().__init__(settings, resolver)
        self.observations: list[bool] = []


class ProbeInput(BaseModel):
    expected: str = Field(default="")


@probe_tools.tool(tier=1)
async def probe_credential(inp: ProbeInput, *, src: ProbeSource) -> dict[str, Any]:
    """Report whether the resolved 'probe' api_key equals the expected marker."""
    matched = src.credential_or_none("api_key") == inp.expected
    src.observations.append(matched)
    return {"matched": matched}


def header(value: dict) -> str:
    return base64.b64encode(json.dumps(value).encode()).decode()


@pytest.fixture
def probe_app(tmp_path):
    settings = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="probe-agent"
    )
    fake = FakeModelClient()
    agent = Agent(
        settings=settings,
        persona="probe",
        skills_dir=Path(__file__).parent.parent / "agent_sdk" / "example" / "skills",
        toolsets=[probe_tools],
        model_client=fake,
    )
    agent.register_source(
        ProbeSource, credentials=[CredentialField(name="api_key", label="API key")]
    )
    app = agent.build_app()
    app.state._fake = fake  # type: ignore[attr-defined]
    return app


def send_body(text: str) -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


async def _wait(client, task_id, timeout=5.0):
    import asyncio

    for _ in range(int(timeout / 0.02)):
        r = await client.get(f"/v1/tasks/{task_id}")
        if r.json()["status"]["state"] in ("completed", "failed"):
            return r.json()
        await asyncio.sleep(0.02)
    raise AssertionError("probe task did not finish")


async def test_a2a_forwarded_then_store_fallback(probe_app):
    app = probe_app
    fake = app.state._fake
    async with app.router.lifespan_context(app):
        app.state.credential_store.set("probe", "api_key", "STORED-KEY")
        adapter = app.state.adapters[ProbeSource]
        _, token = app.state.auth.api_keys.mint("admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            # (1) forwarded header → the worker's tool resolves the FORWARDED key
            fake.script(
                tool_call("probe_credential", {"expected": "FORWARDED-KEY"}),
                reply("done"),
            )
            r = await c.post(
                "/v1/message:send",
                json=send_body("probe"),
                headers={"X-Agent-Credentials": header({"probe": {"api_key": "FORWARDED-KEY"}})},
            )
            await _wait(c, r.json()["id"])
            assert adapter.observations[-1] is True  # resolved FORWARDED-KEY

            # (2) no header → falls back to the STORED key
            fake.script(
                tool_call("probe_credential", {"expected": "STORED-KEY"}),
                reply("done"),
            )
            r = await c.post("/v1/message:send", json=send_body("probe"))
            await _wait(c, r.json()["id"])
            assert adapter.observations[-1] is True  # resolved STORED-KEY

            # (3) a forwarded header is NOT the stored key (proves it overrode)
            fake.script(
                tool_call("probe_credential", {"expected": "STORED-KEY"}),
                reply("done"),
            )
            r = await c.post(
                "/v1/message:send",
                json=send_body("probe"),
                headers={"X-Agent-Credentials": header({"probe": {"api_key": "OTHER-KEY"}})},
            )
            await _wait(c, r.json()["id"])
            assert adapter.observations[-1] is False  # resolved OTHER-KEY, not STORED


def _init_body() -> dict:
    return {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {}},
    }


async def test_card_advertises_credential_extension(probe_app):
    """The vendor key is a forwarding EXTENSION, never an agent securityScheme
    (a2a-advisor) — field names only, never values."""
    app = probe_app
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            card = (await c.get("/.well-known/agent-card.json")).json()

    exts = {e["uri"]: e for e in card["capabilities"]["extensions"]}
    cred = exts["urn:agent-sdk:credential-forwarding:v1"]
    assert cred["required"] is False
    assert cred["params"]["header"] == "X-Agent-Credentials"
    assert cred["params"]["sources"] == {"probe": ["api_key"]}
    # the credential header must NOT masquerade as the agent's own auth
    assert card["securitySchemes"] == {"bearer": {"type": "http", "scheme": "bearer"}}
    assert "X-Agent-Credentials" not in json.dumps(card["securitySchemes"])


async def test_initialize_surfaces_credential_instructions(probe_app):
    app = probe_app
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={
                "Authorization": f"Bearer {token}",
                "MCP-Protocol-Version": "2025-06-18",
            },
        ) as c:
            result = (await c.post("/mcp", json=_init_body())).json()["result"]

    instructions = result["instructions"]
    assert "X-Agent-Credentials" in instructions
    assert "probe: api_key" in instructions
    # serverInfo stays name/version only (Claude.ai schema strictness, LRN-087)
    assert set(result["serverInfo"]) == {"name", "version"}


async def test_no_credential_sources_omits_surfaces(tmp_path):
    """An agent with no credentialed sources advertises neither surface."""
    from agent_sdk.example.agent import make_agent

    settings = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data2"), AGENT_NAME="echo"
    )
    app = make_agent(settings, model_client=FakeModelClient()).build_app()
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={
                "Authorization": f"Bearer {token}",
                "MCP-Protocol-Version": "2025-06-18",
            },
        ) as c:
            card = (await c.get("/.well-known/agent-card.json")).json()
            result = (await c.post("/mcp", json=_init_body())).json()["result"]

    uris = [e["uri"] for e in card["capabilities"]["extensions"]]
    assert "urn:agent-sdk:credential-forwarding:v1" not in uris
    assert "instructions" not in result


async def test_mcp_tools_call_forwarded(probe_app):
    app = probe_app
    async with app.router.lifespan_context(app):
        app.state.credential_store.set("probe", "api_key", "STORED-KEY")
        adapter = app.state.adapters[ProbeSource]
        _, token = app.state.auth.api_keys.mint("admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={
                "Authorization": f"Bearer {token}",
                "MCP-Protocol-Version": "2025-06-18",
            },
        ) as c:
            def call(expected):
                return {
                    "jsonrpc": "2.0", "id": 1, "method": "tools/call",
                    "params": {"name": "probe_credential", "arguments": {"expected": expected}},
                }

            # forwarded header → tool resolves the forwarded key
            r = await c.post(
                "/mcp",
                json=call("FORWARDED-KEY"),
                headers={"X-Agent-Credentials": header({"probe": {"api_key": "FORWARDED-KEY"}})},
            )
            assert r.json()["result"]["isError"] is False
            assert adapter.observations[-1] is True

            # no header → store fallback
            r = await c.post("/mcp", json=call("STORED-KEY"))
            assert adapter.observations[-1] is True

            # malformed header fails closed → store fallback (not an error)
            r = await c.post(
                "/mcp",
                json=call("STORED-KEY"),
                headers={"X-Agent-Credentials": "!!!not-base64!!!"},
            )
            assert r.json()["result"]["isError"] is False
            assert adapter.observations[-1] is True
