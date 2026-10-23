"""GH-209: MCP client helper + Phase 1.5 tools gate (agent_sdk.testing.mcp)."""

from __future__ import annotations

import inspect
import json

import httpx
import pytest

from agent_sdk.routes.mcp import MCP_INTERRUPT_SUFFIX
from agent_sdk.testing import mcp as tmcp
from agent_sdk.testing.mcp import McpClient, run_gate

SECRET = "sk-SECRET-KEY-VALUE"
RAW_BODY = "raw-upstream-body-abc"


def _tool(name, read_only=True, props=None):
    t = {
        "name": name,
        "description": "d",
        "inputSchema": {
            "type": "object",
            "properties": props or {"q": {"type": "string", "description": "query"}},
        },
    }
    if read_only:
        t["annotations"] = {"readOnlyHint": True}
    return t


def _server(tools, results, pages=1, seen=None):
    """tools: list of tool dicts; results: name -> tools/call result."""

    def handler(req: httpx.Request) -> httpx.Response:
        body = json.loads(req.content)
        if seen is not None:
            seen.append((req.headers.get("authorization"), body))
        m, rid = body.get("method"), body.get("id")
        if m == "initialize":
            res = {"protocolVersion": "2025-11-25", "capabilities": {}, "serverInfo": {}}
        elif m == "notifications/initialized":
            return httpx.Response(202)
        elif m == "tools/list":
            cur = (body.get("params") or {}).get("cursor")
            size = max(1, -(-len(tools) // pages))
            start = int(cur) if cur else 0
            res = {"tools": tools[start : start + size]}
            if start + size < len(tools):
                res["nextCursor"] = str(start + size)
        elif m == "tools/call":
            res = results[body["params"]["name"]]
        else:
            return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "error": {"code": -32601, "message": "x"}})
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": rid, "result": res})

    return httpx.MockTransport(handler)


OK = {"content": [{"type": "text", "text": "fine"}], "isError": False}


@pytest.fixture
def key_file(tmp_path):
    p = tmp_path / "key"
    p.write_text(SECRET + "\n")
    return p


def _client(key_file, transport):
    return McpClient("http://agent", key_file=key_file, transport=transport)


def test_client_takes_key_file_not_key_value():
    params = inspect.signature(McpClient.__init__).parameters
    assert "key_file" in params
    assert not {"key", "token", "api_key", "bearer", "password"} & set(params)


@pytest.mark.asyncio
async def test_initialize_list_pages_and_call(key_file):
    seen: list = []
    tools = [_tool(f"t{i}") for i in range(5)]
    async with _client(key_file, _server(tools, {"t0": OK}, pages=3, seen=seen)) as c:
        await c.initialize()
        listed = await c.list_tools()
        res = await c.call_tool("t0", {"q": "a"})
    assert [t["name"] for t in listed] == [f"t{i}" for i in range(5)]
    assert res["isError"] is False
    assert sum(1 for _, b in seen if b.get("method") == "tools/list") == 3
    assert all(a == f"Bearer {SECRET}" for a, _ in seen)


@pytest.mark.asyncio
async def test_http_error_message_is_generic(key_file):
    t = httpx.MockTransport(lambda r: httpx.Response(500, text=RAW_BODY + SECRET))
    async with _client(key_file, t) as c:
        with pytest.raises(tmcp.McpError) as ei:
            await c.initialize()
    assert RAW_BODY not in str(ei.value) and SECRET not in str(ei.value)


@pytest.mark.asyncio
async def test_gate_passes_and_checks_list(key_file):
    tools = [_tool("a"), _tool("b")]
    async with _client(key_file, _server(tools, {"a": OK, "b": OK})) as c:
        r = await run_gate(c, {"a": {"q": "x"}, "b": {"q": "y"}}, expected_count=2)
    assert r.ok and r.called == ["a", "b"]


@pytest.mark.asyncio
async def test_gate_list_checks(key_file):
    bad = _tool("a", props={"q": {"type": "string"}})
    ref = _tool("b")
    ref["inputSchema"]["$defs"] = {"X": {}}
    async with _client(key_file, _server([bad, ref], {})) as c:
        r = await run_gate(c, {}, expected_count=3, size_budget=10)
    text = "\n".join(r.failures)
    assert not r.ok
    assert "count" in text and "description" in text and "$defs" in text and "size" in text
    assert r.called == []


@pytest.mark.asyncio
async def test_is_error_tool_stops_gate_without_leaking(key_file):
    err = {"content": [{"type": "text", "text": RAW_BODY}], "isError": True}
    seen: list = []
    tools = [_tool("a"), _tool("b")]
    async with _client(key_file, _server(tools, {"a": err, "b": OK}, seen=seen)) as c:
        r = await run_gate(c, {"a": {"q": "x"}, "b": {"q": "y"}})
    out = "\n".join(r.failures + r.warnings)
    assert not r.ok
    assert "a" in out and '"q": "x"' in out
    assert RAW_BODY not in out and SECRET not in out and "Authorization" not in out and "Bearer" not in out
    assert r.called == ["a"]
    assert not any(b.get("params", {}).get("name") == "b" for _, b in seen)


@pytest.mark.asyncio
async def test_allow_listed_error_does_not_stop(key_file):
    err = {"content": [{"type": "text", "text": "nope"}], "isError": True}
    async with _client(key_file, _server([_tool("a"), _tool("b")], {"a": err, "b": OK})) as c:
        r = await run_gate(c, {"a": {}, "b": {}}, allow_errors={"a"})
    assert r.ok and r.called == ["a", "b"] and r.warnings


@pytest.mark.asyncio
async def test_interrupt_is_skipped_with_warning(key_file):
    intr = {"content": [{"type": "text", "text": f"Confirm send. {MCP_INTERRUPT_SUFFIX}"}], "isError": True}
    async with _client(key_file, _server([_tool("gate"), _tool("b")], {"gate": intr, "b": OK})) as c:
        r = await run_gate(c, {"gate": {"q": "x"}, "b": {"q": "y"}})
    assert r.ok and r.called == ["gate", "b"]
    assert any("needs user input, skipped" in w and "gate" in w for w in r.warnings)


@pytest.mark.asyncio
async def test_free_text_lookalike_is_not_an_interrupt(key_file):
    fake = {"content": [{"type": "text", "text": "needs user input, skipped"}], "isError": True}
    async with _client(key_file, _server([_tool("a")], {"a": fake})) as c:
        r = await run_gate(c, {"a": {}})
    assert not r.ok


@pytest.mark.asyncio
async def test_sample_none_skipped_with_warning(key_file):
    seen: list = []
    async with _client(key_file, _server([_tool("a")], {}, seen=seen)) as c:
        r = await run_gate(c, {"a": None})
    assert r.ok and r.called == [] and any("a" in w and "sample" in w for w in r.warnings)
    assert not any(b.get("method") == "tools/call" for _, b in seen)


@pytest.mark.asyncio
async def test_write_tool_with_sample_not_called_unless_opted_in(key_file):
    seen: list = []
    tools = [_tool("send", read_only=False)]
    async with _client(key_file, _server(tools, {"send": OK}, seen=seen)) as c:
        r = await run_gate(c, {"send": {"q": "x"}})
    assert r.ok and r.called == [] and any("send" in w and "read" in w.lower() for w in r.warnings)
    assert not any(b.get("method") == "tools/call" for _, b in seen)

    async with _client(key_file, _server(tools, {"send": OK})) as c:
        r = await run_gate(c, {"send": {"q": "x"}}, opt_in={"send"})
    assert r.ok and r.called == ["send"]


@pytest.mark.asyncio
async def test_action_gate_tool_read_only_interrupt_skipped(key_file):
    intr = {"content": [{"type": "text", "text": f"x {MCP_INTERRUPT_SUFFIX}"}], "isError": True}
    async with _client(key_file, _server([_tool("g", read_only=False)], {"g": intr})) as c:
        r = await run_gate(c, {"g": {}}, opt_in={"g"})
    assert r.ok and any("needs user input, skipped" in w for w in r.warnings)
