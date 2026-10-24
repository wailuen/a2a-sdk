"""GH-205: Agent(mcp_skills=None | "tool" | "prompts") exposes skills over MCP."""

from __future__ import annotations

import gc
import json
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk import BaseAgentSettings
from agent_sdk.agent.registry import ToolSet
from agent_sdk.app import Agent
from agent_sdk.testing import FakeModelClient
from agent_sdk.testing.mcp import McpClient, McpError, McpTestClient

MARKER = "ZZ-MARKER-9f3a"


class In(BaseModel):
    x: str = ""


def _skills(tmp_path: Path, n: int = 2) -> Path:
    d = tmp_path / "skills"
    d.mkdir()
    for i in range(n):
        (d / f"skill{i}.md").write_text(
            f"---\nname: skill{i}\ndescription: Does thing {i}\n---\nBody of skill {i}.\n",
            encoding="utf-8",
        )
    return d


def _agent(tmp_path: Path, **kw) -> Agent:
    kw.setdefault("persona", "p")
    return Agent(
        settings=BaseAgentSettings(
            DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent"
        ),
        model_client=FakeModelClient(),
        **kw,
    )


@asynccontextmanager
async def _running(app, tmp_path: Path):
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        _, token = app.state.auth.api_keys.mint("t", admin=True)
        key_file = tmp_path / "key"
        key_file.write_text(token)
        async with McpClient("http://test", key_file=key_file, transport=transport) as c:
            yield app, c, transport
    app.state.credential_store.close()
    gc.collect()


async def _raw(transport, token, body, session=None):
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    if session:
        headers["Mcp-Session-Id"] = session
        headers["MCP-Protocol-Version"] = "2025-06-18"
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        return await c.post("/mcp", json=body, headers=headers)


def _rpc(method, params=None, id_=1):
    return {"jsonrpc": "2.0", "id": id_, "method": method, "params": params or {}}


def test_alias():
    assert McpTestClient is McpClient


# --- boot validation -------------------------------------------------------


def test_invalid_value_fails_boot(tmp_path):
    with pytest.raises(ValueError, match="mcp_skills"):
        _agent(tmp_path, skills_dir=_skills(tmp_path), mcp_skills="both").build_app()


@pytest.mark.parametrize("mode", ["tool", "prompts"])
def test_mode_without_skills_dir_fails_boot(tmp_path, mode):
    with pytest.raises(ValueError, match="mcp_skills"):
        _agent(tmp_path, mcp_skills=mode).build_app()


@pytest.mark.parametrize("mode", [None, "tool", "prompts"])
def test_reserved_tool_name_fails_boot(tmp_path, mode):
    ts = ToolSet()

    @ts.tool(tier=1)
    async def load_skill(inp: In) -> str:
        """clash"""
        return "x"

    with pytest.raises(ValueError, match="load_skill"):
        _agent(
            tmp_path, skills_dir=_skills(tmp_path), toolsets=[ts], mcp_skills=mode
        ).build_app()


# --- default byte identity -------------------------------------------------


async def test_default_is_byte_identical(tmp_path):
    with_skills = _agent(tmp_path, skills_dir=_skills(tmp_path)).build_app()
    async with _running(with_skills, tmp_path) as (_, c, _t):
        init_a = await c.initialize()
        tools_a = await c.list_tools()
    (tmp_path / "b").mkdir()
    plain = _agent(tmp_path / "b").build_app()
    async with _running(plain, tmp_path / "b") as (_, c, _t):
        init_b = await c.initialize()
        tools_b = await c.list_tools()
    assert json.dumps(init_a, sort_keys=True) == json.dumps(init_b, sort_keys=True)
    assert tools_a == tools_b == []
    assert "prompts" not in init_a["capabilities"]


async def test_default_prompts_method_not_found(tmp_path):
    app = _agent(tmp_path, skills_dir=_skills(tmp_path)).build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        for method in ("prompts/list", "prompts/get"):
            with pytest.raises(McpError):
                await c._rpc(method, {"name": "skill0"})


# --- "tool" mode -----------------------------------------------------------


async def test_tool_mode_lists_and_calls(tmp_path):
    app = _agent(
        tmp_path, skills_dir=_skills(tmp_path), mcp_skills="tool", exclude_from_catalog=["skill1"]
    ).build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        init = await c.initialize()
        assert "prompts" not in init["capabilities"]
        tools = await c.list_tools()
        (tool,) = [t for t in tools if t["name"] == "load_skill"]
        assert "skill0" in tool["description"] and "Does thing 0" in tool["description"]
        assert "skill1" not in tool["description"]
        schema = tool["inputSchema"]
        assert schema["required"] == ["name"]
        assert schema["properties"]["name"]["type"] == "string"
        assert tool["annotations"]["readOnlyHint"] is True
        res = await c.call_tool("load_skill", {"name": "skill0"})
        assert res["content"][0]["text"] == "Body of skill 0."
        assert not res.get("isError")
        for bad in ("skill1", "nope"):
            res = await c.call_tool("load_skill", {"name": bad})
            assert res["isError"] is True
            assert bad not in res["content"][0]["text"]


async def test_tool_mode_missing_name_is_error(tmp_path):
    app = _agent(tmp_path, skills_dir=_skills(tmp_path), mcp_skills="tool").build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        res = await c.call_tool("load_skill", {})
        assert res["isError"] is True
        res = await c.call_tool("load_skill", {"name": 5})
        assert res["isError"] is True


async def test_tool_mode_paginates_with_many_tools(tmp_path):
    ts = ToolSet()

    for i in range(64):
        async def fn(inp: In) -> str:
            return "x"

        fn.__name__ = f"t{i}"
        fn.__doc__ = "d"
        ts.tool(tier=1)(fn)
    app = _agent(
        tmp_path, skills_dir=_skills(tmp_path), toolsets=[ts], mcp_skills="tool"
    ).build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        first = await c._rpc("tools/list", {})
        assert len(first["tools"]) == 64 and first["nextCursor"]
        names = [t["name"] for t in await c.list_tools()]
        assert len(names) == 65 and names[-1] == "load_skill"


# --- "prompts" mode --------------------------------------------------------


async def test_prompts_mode(tmp_path):
    app = _agent(
        tmp_path, skills_dir=_skills(tmp_path), mcp_skills="prompts", exclude_from_catalog=["skill1"]
    ).build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        init = await c.initialize()
        assert init["capabilities"]["prompts"] == {"listChanged": False}
        assert await c.list_tools() == []
        prompts = await c.list_prompts()
        assert prompts == [{"name": "skill0", "description": "Does thing 0"}]
        got = await c.get_prompt("skill0")
        (msg,) = got["messages"]
        assert msg["role"] == "user"
        assert msg["content"] == {"type": "text", "text": "Body of skill 0."}
        with pytest.raises(McpError):
            await c.get_prompt("skill1")


async def test_prompts_mode_load_skill_not_a_tool(tmp_path):
    app = _agent(tmp_path, skills_dir=_skills(tmp_path), mcp_skills="prompts").build_app()
    async with _running(app, tmp_path) as (_, c, t):
        _, token = app.state.auth.api_keys.mint("u", admin=True)
        r = await _raw(t, token, _rpc("tools/call", {"name": "load_skill", "arguments": {"name": "skill0"}}))
        assert r.json()["error"]["code"] == -32602


async def test_prompts_pagination(tmp_path):
    app = _agent(tmp_path, skills_dir=_skills(tmp_path, 70), mcp_skills="prompts").build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        first = await c._rpc("prompts/list", {})
        assert len(first["prompts"]) == 64 and first["nextCursor"]
        assert len(await c.list_prompts()) == 70


async def test_prompts_get_errors_never_echo_name(tmp_path, sdk_caplog):
    app = _agent(
        tmp_path, skills_dir=_skills(tmp_path), mcp_skills="prompts", exclude_from_catalog=["skill1"]
    ).build_app()
    async with _running(app, tmp_path) as (_, c, t):
        _, token = app.state.auth.api_keys.mint("u", admin=True)
        with sdk_caplog("agent_sdk", logging.DEBUG) as records:
            logging.getLogger("agent_sdk.routes.mcp").warning("probe")
            for name in (MARKER, "skill1"):
                r = await _raw(t, token, _rpc("prompts/get", {"name": name + "x"}))
                assert r.json()["error"]["code"] == -32602
                assert MARKER not in r.text
            r = await _raw(t, token, _rpc("prompts/get", {"name": MARKER}))
            assert MARKER not in r.text
            r = await _raw(t, token, _rpc("prompts/get", {}))
            assert r.json()["error"]["code"] == -32602
    assert any(r.getMessage() == "probe" for r in records)
    assert MARKER not in "\n".join(r.getMessage() for r in records)


async def test_tool_call_errors_never_echo_name(tmp_path, sdk_caplog):
    app = _agent(tmp_path, skills_dir=_skills(tmp_path), mcp_skills="tool").build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        with sdk_caplog("agent_sdk", logging.DEBUG) as records:
            logging.getLogger("agent_sdk.routes.mcp").warning("probe")
            res = await c.call_tool("load_skill", {"name": MARKER})
            assert res["isError"] is True
            assert MARKER not in json.dumps(res)
    assert any(r.getMessage() == "probe" for r in records)
    assert MARKER not in "\n".join(r.getMessage() for r in records)


# --- SI-5 ------------------------------------------------------------------


async def test_unauthenticated_prompts_401(tmp_path):
    app = _agent(tmp_path, skills_dir=_skills(tmp_path), mcp_skills="prompts").build_app()
    async with _running(app, tmp_path) as (_, c, t):
        for body in (_rpc("prompts/list"), _rpc("prompts/get", {"name": "skill0"})):
            assert (await _raw(t, None, body)).status_code == 401


async def test_prompts_on_foreign_session_refused_like_tools(tmp_path):
    app = _agent(tmp_path, skills_dir=_skills(tmp_path), mcp_skills="prompts").build_app()
    async with _running(app, tmp_path) as (_, c, t):
        _, a = app.state.auth.api_keys.mint("a", admin=False)
        _, b = app.state.auth.api_keys.mint("b", admin=False)
        init = await _raw(t, a, _rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {}}))
        sid = init.headers["Mcp-Session-Id"]
        ok = await _raw(t, a, _rpc("prompts/list"), session=sid)
        assert ok.status_code == 200 and ok.json()["result"]["prompts"]
        tools = await _raw(t, b, _rpc("tools/list"), session=sid)
        lst = await _raw(t, b, _rpc("prompts/list"), session=sid)
        get = await _raw(t, b, _rpc("prompts/get", {"name": "skill0"}), session=sid)
        assert tools.status_code == lst.status_code == get.status_code == 404
