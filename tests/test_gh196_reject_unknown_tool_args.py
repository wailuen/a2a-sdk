"""GH-196: tool arguments not declared by the input model are rejected.

Ruling: https://github.com/wailuen/a2a-sdk/issues/196#issuecomment-6229360794
"""

from __future__ import annotations

import gc
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolInputValidationError, ToolRegistry, ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient, tool_call

tools = ToolSet()
_SECRET = "sk_live_SECRETVALUE_9f3d"


class StrictIn(BaseModel):
    ticker: str


class AliasIn(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    entity_id: str = Field(alias="entityId")


class AliasNoByNameIn(BaseModel):
    q: str
    sector: str | None = Field(None, alias="sectorCode")


class AllowIn(BaseModel):
    model_config = ConfigDict(extra="allow")
    ticker: str


@tools.tool(tier=1)
async def gh196_strict(inp: StrictIn) -> dict[str, Any]:
    """Strict tool."""
    return {"ticker": inp.ticker}


@tools.tool(tier=1)
async def gh196_alias(inp: AliasIn) -> dict[str, Any]:
    """Alias tool."""
    return {"id": inp.entity_id}


@tools.tool(tier=1)
async def gh196_alias_strict(inp: AliasNoByNameIn) -> dict[str, Any]:
    """Alias without populate_by_name."""
    return {"sector": inp.sector}


@tools.tool(tier=1)
async def gh196_allow_model(inp: AllowIn) -> dict[str, Any]:
    """Model allows extras."""
    return {"ticker": inp.ticker}


@tools.tool(tier=1, allow_extra_args=True)
async def gh196_optout(inp: StrictIn) -> dict[str, Any]:
    """Tool opted out."""
    return {"ticker": inp.ticker}


@tools.tool(tier=1)
async def gh196_noinput() -> dict[str, Any]:
    """No input."""
    return {}


@tools.tool(tier=1, allow_extra_args=True)
async def gh196_noinput_optout() -> dict[str, Any]:
    """No input, opted out."""
    return {}


REGISTRY = ToolRegistry([tools], {})


def _entry(name: str):
    return REGISTRY.get(name)


async def _loop_result(name: str, args: dict[str, Any]) -> ToolResultEvent:
    model = FakeModelClient([tool_call(name, args)])
    async for ev in run_loop(
        model=model,
        registry=REGISTRY,
        adapters={},
        system="t",
        messages=[{"role": "user", "content": [{"text": "go"}]}],
    ):
        if isinstance(ev, ToolResultEvent):
            return ev
    raise AssertionError("no tool result")


async def test_invoke_rejects_unknown_key():
    with pytest.raises(ToolInputValidationError):
        await _entry("gh196_strict").invoke({"ticker": "A", "tickr": _SECRET}, {})


async def test_invoke_gen_rejects_unknown_key():
    gen_tools = ToolSet()

    @gen_tools.tool(tier=1)
    async def gh196_gen(inp: StrictIn):
        """Gen."""
        yield {"ticker": inp.ticker}

    entry = ToolRegistry([gen_tools], {}).get("gh196_gen")
    with pytest.raises(ToolInputValidationError):
        async for _ in entry.invoke_gen({"ticker": "A", "bogus": 1}, {}):
            pass


async def test_loop_error_names_key_not_value():
    res = await _loop_result("gh196_strict", {"ticker": "A", "tickr": _SECRET})
    assert not res.ok
    assert "tickr" in res.error
    assert _SECRET not in res.error


async def test_correct_call_unchanged():
    res = await _loop_result("gh196_strict", {"ticker": "A"})
    assert res.ok


async def test_alias_and_field_name_accepted():
    assert (await _loop_result("gh196_alias", {"entityId": "1"})).ok
    assert (await _loop_result("gh196_alias", {"entity_id": "1"})).ok


async def test_aliased_field_name_rejected_without_populate_by_name():
    with pytest.raises(ToolInputValidationError) as ei:
        await _entry("gh196_alias_strict").invoke({"q": "a", "sector": "TECH"}, {})
    assert any(e["loc"] == ("sector",) for e in ei.value.validation_error.errors())
    assert (await _loop_result("gh196_alias_strict", {"q": "a", "sectorCode": "T"})).ok


async def test_model_extra_allow_succeeds():
    assert (await _loop_result("gh196_allow_model", {"ticker": "A", "x": 1})).ok


async def test_opt_out_succeeds():
    assert (await _loop_result("gh196_optout", {"ticker": "A", "x": 1})).ok


async def test_no_input_model_rejects_args():
    res = await _loop_result("gh196_noinput", {"x": 1})
    assert not res.ok
    assert "x" in res.error


async def test_no_input_model_opt_out_and_empty_args():
    assert (await _loop_result("gh196_noinput_optout", {"x": 1})).ok
    assert (await _loop_result("gh196_noinput", {})).ok


def test_schema_additional_properties():
    assert _entry("gh196_strict").input_schema()["additionalProperties"] is False
    assert _entry("gh196_allow_model").input_schema()["additionalProperties"] is True
    assert _entry("gh196_optout").input_schema()["additionalProperties"] is True
    assert _entry("gh196_noinput").input_schema()["additionalProperties"] is False
    assert _entry("gh196_noinput_optout").input_schema()["additionalProperties"] is True


def test_user_model_not_mutated():
    assert StrictIn.model_config.get("extra") is None
    assert "additionalProperties" not in StrictIn.model_json_schema()


@pytest.fixture
def gh196_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def gh196_client(gh196_app):
    async with gh196_app.router.lifespan_context(gh196_app):
        _, token = gh196_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gh196_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


async def _mcp(client: httpx.AsyncClient, name: str, args: dict[str, Any]) -> dict[str, Any]:
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    headers = {"MCP-Protocol-Version": "2025-06-18"}
    if r.headers.get("mcp-session-id"):
        headers["Mcp-Session-Id"] = r.headers["mcp-session-id"]
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        },
        headers=headers,
    )
    return r.json()["result"]


async def test_mcp_rejects_unknown_key(gh196_client):
    res = await _mcp(gh196_client, "gh196_strict", {"ticker": "A", "tickr": _SECRET})
    assert res["isError"] is True
    text = res["content"][0]["text"]
    assert "tickr" in text
    assert _SECRET not in text


async def test_mcp_extra_allow_and_opt_out_succeed(gh196_client):
    assert not (await _mcp(gh196_client, "gh196_allow_model", {"ticker": "A", "x": 1})).get("isError")
    assert not (await _mcp(gh196_client, "gh196_optout", {"ticker": "A", "x": 1})).get("isError")
    assert not (await _mcp(gh196_client, "gh196_strict", {"ticker": "A"})).get("isError")
