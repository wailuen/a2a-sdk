"""GH-273: a present MCP-Protocol-Version header must match the version the
session negotiated at initialize; early exits echo the owned session's version.
Ruling: https://github.com/wailuen/a2a-sdk/issues/273#issuecomment-6398503498
"""

from __future__ import annotations

import httpx

from agent_sdk.routes.mcp import SUPPORTED_PROTOCOL_VERSIONS, _sessions

_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
}
_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
_NEWEST = SUPPORTED_PROTOCOL_VERSIONS[0]


async def _init(c: httpx.AsyncClient) -> str:
    r = await c.post("/mcp", json=_INIT)
    assert r.status_code == 200, r.text
    return r.headers["mcp-session-id"]


def _other_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    app = client.app  # type: ignore[attr-defined]
    _, token = app.state.auth.api_keys.mint("other-caller-273", admin=True)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


async def test_mismatched_header_is_400(client: httpx.AsyncClient) -> None:
    sid = await _init(client)
    r = await client.post(
        "/mcp",
        json=_LIST,
        headers={"Mcp-Session-Id": sid, "MCP-Protocol-Version": "2025-11-25"},
    )
    assert r.status_code == 400
    assert r.json() == {"error": "unsupported MCP-Protocol-Version"}
    assert r.headers["mcp-protocol-version"] == _NEWEST


async def test_matching_header_works(client: httpx.AsyncClient) -> None:
    sid = await _init(client)
    r = await client.post(
        "/mcp",
        json=_LIST,
        headers={"Mcp-Session-Id": sid, "MCP-Protocol-Version": "2025-06-18"},
    )
    assert r.status_code == 200, r.text
    assert r.headers["mcp-protocol-version"] == "2025-06-18"


async def test_absent_header_echoes_session_version(client: httpx.AsyncClient) -> None:
    sid = await _init(client)
    r = await client.post("/mcp", json=_LIST, headers={"Mcp-Session-Id": sid})
    assert r.status_code == 200, r.text
    assert r.headers["mcp-protocol-version"] == "2025-06-18"


async def test_early_exit_415_echoes_owned_session_version(
    client: httpx.AsyncClient,
) -> None:
    sid = await _init(client)
    r = await client.post(
        "/mcp",
        content=b"x",
        headers={"Mcp-Session-Id": sid, "Content-Type": "text/plain"},
    )
    assert r.status_code == 415
    assert r.headers["mcp-protocol-version"] == "2025-06-18"


async def test_early_exit_415_other_owner_session_echoes_newest(
    client: httpx.AsyncClient,
) -> None:
    sid = await _init(client)
    async with _other_client(client) as other:
        r = await other.post(
            "/mcp",
            content=b"x",
            headers={"Mcp-Session-Id": sid, "Content-Type": "text/plain"},
        )
    assert r.status_code == 415
    assert r.headers["mcp-protocol-version"] == _NEWEST


async def test_other_owner_session_never_gets_mismatch_400(
    client: httpx.AsyncClient,
) -> None:
    sid = await _init(client)
    async with _other_client(client) as other:
        for version in ("2025-06-18", "2025-11-25"):
            r = await other.post(
                "/mcp",
                json=_LIST,
                headers={"Mcp-Session-Id": sid, "MCP-Protocol-Version": version},
            )
            assert r.status_code == 404, r.text
            assert r.json() == {"error": "session not found"}


async def test_unknown_session_with_any_header_is_404(client: httpx.AsyncClient) -> None:
    for version in ("2025-06-18", "2025-11-25"):
        r = await client.post(
            "/mcp",
            json=_LIST,
            headers={"Mcp-Session-Id": "deadbeef", "MCP-Protocol-Version": version},
        )
        assert r.status_code == 404
        assert r.json() == {"error": "session not found"}


async def test_rejected_early_exit_does_not_refresh_last_seen(
    client: httpx.AsyncClient,
) -> None:
    sid = await _init(client)
    sessions = _sessions(client.app)  # type: ignore[attr-defined]
    last_seen, owner, ver = sessions[sid]
    old = last_seen - 100
    sessions[sid] = (old, owner, ver)
    r = await client.post(
        "/mcp",
        content=b"x",
        headers={"Mcp-Session-Id": sid, "Content-Type": "text/plain"},
    )
    assert r.status_code == 415
    assert sessions[sid][0] == old
