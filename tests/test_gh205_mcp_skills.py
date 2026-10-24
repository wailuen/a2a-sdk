"""GH-205: Agent(mcp_skills=None | "tool" | "prompts") exposes skills over MCP."""

from __future__ import annotations

import gc
import json
import logging
import re
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
    async with _running(app, tmp_path) as (_, c, t):
        _, token = app.state.auth.api_keys.mint("u", admin=True)
        for method in ("prompts/list", "prompts/get"):
            with pytest.raises(McpError):
                await c._rpc(method, {"name": "skill0"})
            r = await _raw(t, token, _rpc(method, {"name": "skill0"}))
            assert r.json()["error"]["code"] == -32601


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
    async with _running(app, tmp_path) as (_, c, t):
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
        _, token = app.state.auth.api_keys.mint("u", admin=True)
        r = await _raw(t, token, _rpc("prompts/get", {"name": "skill1"}))
        assert r.json()["error"]["code"] == -32602


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


# --- GH-236 ------------------------------------------------------------------

HOSTILE_VALUE = "ZZ-HOSTILE-VALUE-71c2"


async def test_load_skill_annotations_and_title(tmp_path):
    app = _agent(tmp_path, skills_dir=_skills(tmp_path), mcp_skills="tool").build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        (tool,) = [t for t in await c.list_tools() if t["name"] == "load_skill"]
        assert tool["annotations"] == {"readOnlyHint": True, "openWorldHint": False}
        assert tool["title"] == "Load skill"


async def test_load_skill_not_served_when_catalog_empty(tmp_path):
    app = _agent(
        tmp_path,
        skills_dir=_skills(tmp_path),
        mcp_skills="tool",
        exclude_from_catalog=["skill0", "skill1"],
    ).build_app()
    async with _running(app, tmp_path) as (_, c, t):
        assert [x["name"] for x in await c.list_tools()] == []
        _, token = app.state.auth.api_keys.mint("u", admin=True)
        r = await _raw(
            t, token, _rpc("tools/call", {"name": "load_skill", "arguments": {"name": "skill0"}})
        )
        assert r.json()["error"] == {"code": -32602, "message": "tool not found"}


@pytest.mark.parametrize(
    "arguments, expect",
    [
        ({"name": "skill0", "extra": HOSTILE_VALUE}, "extra"),
        ({"name": "skill0", "bad key <x>": HOSTILE_VALUE}, "<key>"),
        ({"name": HOSTILE_VALUE, "other": HOSTILE_VALUE}, "other"),
    ],
)
async def test_load_skill_argument_errors_use_registry_shape(tmp_path, arguments, expect):
    from agent_sdk.agent.loop import safe_validation_message
    from agent_sdk.agent.registry import _unknown_argument_error

    app = _agent(tmp_path, skills_dir=_skills(tmp_path), mcp_skills="tool").build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        res = await c.call_tool("load_skill", arguments)
    assert res["isError"] is True
    text = res["content"][0]["text"]
    assert text.startswith("tool 'load_skill' input invalid: ")
    assert expect in text
    assert HOSTILE_VALUE not in text
    keys = [expect] if expect != "<key>" else ["bad key <x>"]
    want = safe_validation_message(
        "load_skill", _unknown_argument_error(keys, tool_name="load_skill").validation_error, None
    )
    assert text == want


@pytest.mark.parametrize(
    "arguments, expect",
    [({}, "name — required field is missing"), ({"name": 5}, "name — expected a string")],
)
async def test_load_skill_missing_or_bad_name_says_required(tmp_path, arguments, expect):
    # A missing or non-string name is not an "unknown argument" (release gate M2).
    app = _agent(tmp_path, skills_dir=_skills(tmp_path), mcp_skills="tool").build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        res = await c.call_tool("load_skill", arguments)
    assert res["isError"] is True
    text = res["content"][0]["text"]
    assert text == f"tool 'load_skill' input invalid: {expect}"
    assert "unknown argument" not in text


async def test_load_skill_catalog_cut_at_whole_entries(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    for i in range(40):
        (d / f"skill{i:02d}.md").write_text(
            f"---\nname: skill{i:02d}\ndescription: {'d' * 70} number {i:02d}\n---\nBody.\n",
            encoding="utf-8",
        )
    app = _agent(tmp_path, skills_dir=d, mcp_skills="tool").build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        (tool,) = [t for t in await c.list_tools() if t["name"] == "load_skill"]
    prefix = "Load the full instructions of a listed skill by name. Skills: "
    catalog = tool["description"][len(prefix) :]
    assert len(catalog) <= 2048
    body, _, tail = catalog.rpartition("; ")
    assert re.fullmatch(r"…and \d+ more", tail)
    left_out = int(re.search(r"\d+", tail).group())
    entries = body.split("; ")
    assert len(entries) + left_out == 40
    assert all(re.fullmatch(r"skill\d\d: d{70} number \d\d", e) for e in entries)
    assert entries[0].startswith("skill00")


async def test_load_skill_small_catalog_has_no_more_suffix(tmp_path):
    app = _agent(tmp_path, skills_dir=_skills(tmp_path), mcp_skills="tool").build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        (tool,) = [t for t in await c.list_tools() if t["name"] == "load_skill"]
    assert "more" not in tool["description"].split("Skills:")[1]


def _bad_cursors():
    import base64

    return [
        base64.b64encode(b"-1").decode(),
        base64.b64encode(b"-9999").decode(),
        "!!notbase64" + HOSTILE_VALUE,
        base64.b64encode(HOSTILE_VALUE.encode()).decode(),
        HOSTILE_VALUE,
    ]


@pytest.mark.parametrize("method, mode", [("tools/list", "tool"), ("prompts/list", "prompts")])
async def test_bad_cursor_is_invalid_params_without_echo(tmp_path, method, mode):
    app = _agent(tmp_path, skills_dir=_skills(tmp_path), mcp_skills=mode).build_app()
    async with _running(app, tmp_path) as (_, c, t):
        _, token = app.state.auth.api_keys.mint("u", admin=True)
        for cursor in _bad_cursors():
            r = await _raw(t, token, _rpc(method, {"cursor": cursor}))
            err = r.json()["error"]
            assert err["code"] == -32602
            assert err["message"] == "invalid cursor"
            assert HOSTILE_VALUE not in r.text and cursor not in r.text
        r = await _raw(t, token, _rpc(method, {"cursor": 5}))
        assert r.json()["error"]["code"] == -32602
        r = await _raw(t, token, _rpc(method, {"cursor": ""}))
        assert "result" in r.json()


@pytest.mark.parametrize(
    "flag", ["mcp_skills", "reserved", "unknown_exclude", "tool_without_skills_dir"]
)
def test_boot_checks_run_before_credential_store(tmp_path, monkeypatch, flag):
    opened: list[bool] = []
    original = Agent._build_credential_store

    def spy(self):
        opened.append(True)
        return original(self)

    monkeypatch.setattr(Agent, "_build_credential_store", spy)
    if flag == "mcp_skills":
        agent = _agent(tmp_path, skills_dir=_skills(tmp_path), mcp_skills="both")
    elif flag == "unknown_exclude":
        agent = _agent(
            tmp_path, skills_dir=_skills(tmp_path), exclude_from_catalog=["no-such-skill"]
        )
    elif flag == "tool_without_skills_dir":
        agent = _agent(tmp_path, mcp_skills="tool", skills_dir=None)
    else:
        ts = ToolSet()

        @ts.tool(tier=1)
        async def load_skill(inp: In) -> str:
            """clash"""
            return "x"

        agent = _agent(tmp_path, skills_dir=_skills(tmp_path), toolsets=[ts])
    with pytest.raises(ValueError) as info:
        agent.build_app()
    assert opened == []
    assert str(tmp_path) not in str(info.value)


async def test_load_skill_catalog_skips_long_entry_and_lists_later_short_ones(tmp_path):
    d = tmp_path / "skills"
    d.mkdir()
    (d / "aaa.md").write_text(
        f"---\nname: aaa\ndescription: {'L' * 2200}\n---\nBody.\n", encoding="utf-8"
    )
    for n in ("bbb", "ccc"):
        (d / f"{n}.md").write_text(
            f"---\nname: {n}\ndescription: short {n}\n---\nBody.\n", encoding="utf-8"
        )
    app = _agent(tmp_path, skills_dir=d, mcp_skills="tool").build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        (tool,) = [t for t in await c.list_tools() if t["name"] == "load_skill"]
    catalog = tool["description"].split("Skills: ", 1)[1]
    assert "bbb: short bbb" in catalog
    assert "ccc: short ccc" in catalog
    assert "L" * 50 not in catalog
    assert catalog.endswith("…and 1 more")


async def test_load_skill_success_carries_is_error_false(tmp_path):
    app = _agent(tmp_path, skills_dir=_skills(tmp_path), mcp_skills="tool").build_app()
    async with _running(app, tmp_path) as (_, c, _t):
        res = await c.call_tool("load_skill", {"name": "skill0"})
    assert res["isError"] is False
    assert res["content"][0]["text"].startswith("Body of skill 0")
