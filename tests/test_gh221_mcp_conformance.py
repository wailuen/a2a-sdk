"""GH-221: MCP conformance — unknown tool -32602, POSTed JSON-RPC response -> 202,
GET /mcp applies the Mcp-Session-Id checks of POST /mcp."""

from __future__ import annotations

import asyncio
import time

import httpx

from agent_sdk.routes.mcp import _sessions

_V = {"MCP-Protocol-Version": "2025-06-18"}


async def _init(client: httpx.AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    assert r.status_code == 200, r.text
    return {**_V, "Mcp-Session-Id": r.headers["mcp-session-id"]}


def _foreign_session(app) -> str:
    sid = "f" * 32
    _sessions(app)[sid] = (time.time(), "someone-else", "2025-06-18")
    return sid


async def test_unknown_tool_is_invalid_params_without_echo(client) -> None:
    headers = await _init(client)
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
              "params": {"name": "zz_secret_name", "arguments": {}}},
        headers=headers,
    )
    err = r.json()["error"]
    assert err["code"] == -32602
    assert "zz_secret_name" not in r.text


async def test_tier2_tool_looks_like_unknown(client, app) -> None:
    headers = await _init(client)
    tier2 = [e for e in app.state.registry.all() if e.tier != 1]
    if not tier2:
        return
    name = tier2[0].name

    async def call(n: str) -> dict:
        r = await client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                  "params": {"name": n, "arguments": {}}},
            headers=headers,
        )
        return r.json()["error"]

    assert await call(name) == await call("nope_unknown")


async def test_posted_result_response_is_202(client) -> None:
    headers = await _init(client)
    r = await client.post(
        "/mcp", json={"jsonrpc": "2.0", "id": 7, "result": {}}, headers=headers
    )
    assert r.status_code == 202
    assert r.content == b""


async def test_posted_error_response_is_202(client) -> None:
    headers = await _init(client)
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": "a", "error": {"code": -32000, "message": "x"}},
        headers=headers,
    )
    assert r.status_code == 202
    assert r.content == b""


async def test_posted_response_unknown_session_is_404(client) -> None:
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 7, "result": {}},
        headers={**_V, "Mcp-Session-Id": "0" * 32},
    )
    assert r.status_code == 404


async def test_posted_response_other_owner_session_is_404(client, app) -> None:
    sid = _foreign_session(app)
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 7, "result": {}},
        headers={**_V, "Mcp-Session-Id": sid},
    )
    assert r.status_code == 404
    assert sid not in r.text


async def test_get_without_session_header_still_streams(client) -> None:
    task = asyncio.create_task(client.get("/mcp", headers=_V))
    await asyncio.sleep(0.5)
    assert not task.done()  # stream opened (200 SSE), not rejected
    task.cancel()


async def test_get_oversized_session_id_is_400_no_echo(client) -> None:
    sid = "a" * 65
    r = await asyncio.wait_for(client.get("/mcp", headers={**_V, "Mcp-Session-Id": sid}), timeout=3)
    assert r.status_code == 400
    assert sid not in r.text


async def test_get_unknown_and_other_owner_sessions_identical_404(client, app) -> None:
    unknown = await asyncio.wait_for(client.get("/mcp", headers={**_V, "Mcp-Session-Id": "0" * 32}), timeout=3)
    sid = _foreign_session(app)
    foreign = await asyncio.wait_for(client.get("/mcp", headers={**_V, "Mcp-Session-Id": sid}), timeout=3)
    assert unknown.status_code == foreign.status_code == 404
    assert unknown.content == foreign.content
    assert sid not in foreign.text and "0" * 32 not in unknown.text


async def test_get_expired_session_is_404(client, app) -> None:
    headers = await _init(client)
    sid = headers["Mcp-Session-Id"]
    rec = _sessions(app)[sid]
    _sessions(app)[sid] = (0.0, rec[1], rec[2])
    r = await asyncio.wait_for(client.get("/mcp", headers=headers), timeout=3)
    assert r.status_code == 404
