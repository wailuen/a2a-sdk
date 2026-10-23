"""GH-221: tools/list drops pydantic auto-generated `title` keys from tool schemas."""

from __future__ import annotations

import gc
import json
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, Field

from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.testing.mcp import DEFAULT_SIZE_BUDGET, McpClient, _has_ref

anyof_tools = ToolSet()


class IdEither(BaseModel):
    model_config = {"json_schema_extra": {"anyOf": [{"required": ["a"]}, {"required": ["b"]}]}}

    a: str | None = Field(default=None, description="ID A")
    b: str | None = Field(default=None, description="ID B")
    title: str | None = Field(default=None, description="A field literally named title")


@anyof_tools.tool(tier=1, read_only=True)
async def gh221_id_either(inp: IdEither) -> str:
    """Look up by ID A or ID B."""
    return "ok"


def _size(tools: list[dict[str, Any]]) -> int:
    return len(json.dumps(tools, separators=(",", ":")).encode())


def _title_keys(node: Any, in_properties: bool = False) -> list[str]:
    found: list[str] = []
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "title" and not in_properties:
                found.append("title")
            found.extend(_title_keys(v, in_properties=(k == "properties" and not in_properties)))
    elif isinstance(node, list):
        for v in node:
            found.extend(_title_keys(v))
    return found


def _unstripped(app) -> list[dict[str, Any]]:
    tools = []
    for e in app.state.registry.tier1():
        t: dict[str, Any] = {"name": e.name, "description": e.description, "inputSchema": e.input_schema()}
        out = e.output_schema()
        if out is not None:
            t["outputSchema"] = out
        tools.append(t)
    return tools


@pytest.fixture
async def mcp_client(app, client, tmp_path):
    _, token = app.state.auth.api_keys.mint("gh221", admin=True)
    key_file = tmp_path / "key"
    key_file.write_text(token)
    c = McpClient("http://test", key_file=key_file, transport=httpx.ASGITransport(app=app))
    await c.initialize()
    return c


async def test_titles_stripped_and_smaller(app, mcp_client) -> None:
    before = _size(_unstripped(app))
    tools = await mcp_client.list_tools()
    after = _size(tools)
    assert after < before
    assert after <= DEFAULT_SIZE_BUDGET
    for t in tools:
        for key in ("inputSchema", "outputSchema"):
            assert _title_keys(t.get(key)) == [], (t["name"], key)


async def test_property_named_title_survives(mcp_client) -> None:
    tools = {t["name"]: t for t in await mcp_client.list_tools()}
    props = tools["demo_kpis"]["inputSchema"]["properties"]
    assert "title" in props
    assert props["title"]["description"] == "Title for the KPI card"
    assert "title" not in props["title"]


async def test_refs_unchanged_by_stripping(app, mcp_client) -> None:
    """Tool schemas keep whatever $ref/$defs pydantic emitted; stripping adds or
    removes none. Nested models in outputSchema may carry $defs (the gate's
    _has_ref only inspects inputSchema), so no gate failure follows."""
    tools = await mcp_client.list_tools()
    raw = {t["name"]: t for t in _unstripped(app)}
    for t in tools:
        for key in ("inputSchema", "outputSchema"):
            assert sorted(_has_ref(t.get(key))) == sorted(_has_ref(raw[t["name"]].get(key)))
        assert _has_ref(t["inputSchema"]) == []


async def test_title_keys_inside_defs_items_anyof_removed() -> None:
    from agent_sdk.routes.mcp import _strip_titles

    schema = {
        "title": "Root",
        "properties": {
            "title": {"title": "Title", "type": "string"},
            "xs": {"title": "Xs", "type": "array", "items": {"title": "Item", "type": "string"}},
            "u": {"anyOf": [{"title": "A", "type": "string"}, {"type": "null"}]},
        },
        "$defs": {"D": {"title": "D", "properties": {"title": {"title": "T", "type": "string"}}}},
    }
    out = _strip_titles(schema)
    assert _title_keys(out) == []
    assert "title" in out["properties"]
    assert "title" in out["$defs"]["D"]["properties"]


@pytest.fixture
async def anyof_client(settings, fake_model, tmp_path):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [anyof_tools]
    app = agent.build_app()
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("gh221", admin=True)
        key_file = tmp_path / "key2"
        key_file.write_text(token)
        c = McpClient("http://test", key_file=key_file, transport=httpx.ASGITransport(app=app))
        await c.initialize()
        yield c
    app.state.credential_store.close()
    gc.collect()


async def test_any_of_required_reaches_tools_list(anyof_client) -> None:
    tools = {t["name"]: t for t in await anyof_client.list_tools()}
    schema = tools["gh221_id_either"]["inputSchema"]
    assert schema["anyOf"] == [{"required": ["a"]}, {"required": ["b"]}]
    assert "title" in schema["properties"]
