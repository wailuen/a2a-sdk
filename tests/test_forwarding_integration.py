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
from agent_sdk.credentials.card import credential_forwarding_extension
from agent_sdk.testing import FakeModelClient, reply, tool_call

probe_tools = ToolSet()


class ProbeSource(SourceAdapter):
    source_name = "probe"
    _no_http = True  # non-HTTP adapter; credentials resolved in-process only (SI-7 opt-out)
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


async def test_a2a_echoes_declared_credential_extension(probe_app):
    from agent_sdk.credentials.card import EXTENSION_URI

    app = probe_app
    app.state._fake.script(reply("done"))
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}", "X-A2A-Extensions": EXTENSION_URI},
        ) as c:
            r = await c.post("/v1/message:send", json=send_body("hi"))
            assert r.status_code == 200, r.text
            assert EXTENSION_URI in r.headers.get("x-a2a-extensions", "")
            await _wait(c, r.json()["id"])


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
    cred = exts["https://agent-sdk.dev/extensions/credential-forwarding/v1"]
    assert cred["required"] is False
    assert cred["params"]["header"] == "X-Agent-Credentials"
    assert cred["params"]["sources"] == {"probe": ["api_key"]}
    # the credential header must NOT masquerade as the agent's own auth
    # GH-219: the card also advertises the SDK's own OAuth server (`oauth2`);
    # the credential header must not appear as any auth scheme.
    assert set(card["securitySchemes"]) == {"bearer", "oauth2"}
    assert card["securitySchemes"]["bearer"] == {"type": "http", "scheme": "bearer"}
    assert card["securitySchemes"]["oauth2"]["type"] == "oauth2"
    assert "X-Agent-Credentials" not in json.dumps(card["securitySchemes"])


async def test_initialize_surfaces_credential_instructions(probe_app):
    """LRN-019: serverInfo.title is only emitted when the negotiated MCP
    protocol version is 2025-11-25 or newer.  Tests that assert its presence
    must negotiate that version; older versions must NOT carry title.
    """
    app = probe_app

    def _init_body_v(version: str) -> dict:
        return {
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": version, "capabilities": {}, "clientInfo": {}},
        }

    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            # --- 2025-11-25: title MUST be present ---
            result_new = (
                await c.post(
                    "/mcp",
                    json=_init_body_v("2025-11-25"),
                    headers={"MCP-Protocol-Version": "2025-11-25"},
                )
            ).json()["result"]

            instructions = result_new["instructions"]
            assert "X-Agent-Credentials" in instructions
            assert "probe: api_key" in instructions
            # serverInfo must carry name, version, AND title on 2025-11-25+
            assert {"name", "version", "title"} <= set(result_new["serverInfo"])

            # --- 2025-06-18: title MUST NOT be present (GH #43 / LRN-019) ---
            result_old = (
                await c.post(
                    "/mcp",
                    json=_init_body_v("2025-06-18"),
                    headers={"MCP-Protocol-Version": "2025-06-18"},
                )
            ).json()["result"]

            assert "title" not in result_old["serverInfo"]
            # instructions are still emitted on the older version
            assert "X-Agent-Credentials" in result_old["instructions"]


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
    assert "https://agent-sdk.dev/extensions/credential-forwarding/v1" not in uris
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


# ── GH-79: extension URI must use https:// scheme ────────────────────────────


def test_credential_forwarding_extension_uri_uses_https_scheme():
    """GH-79: EXTENSION_URI must use https:// so consumer allowlists accept it."""
    fields = {"probe": [CredentialField(name="api_key", label="Probe API Key", env_var="PROBE_API_KEY")]}
    ext = credential_forwarding_extension(fields)
    assert ext is not None
    assert ext.uri.startswith("https://"), (
        f"extension URI must use https:// scheme, got: {ext.uri!r}"
    )


def test_credential_forwarding_extension_no_sources_returns_none():
    """AC-3 (None branch): credential_forwarding_extension({}) must return None
    when there are no credential sources — no extension should be advertised."""
    assert credential_forwarding_extension({}) is None
