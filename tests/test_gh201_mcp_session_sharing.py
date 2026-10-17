"""GH-201: MCP sessions are shared-credential safe.

A successful initialize evicts only the session it replaces (the presented,
caller-owned Mcp-Session-Id); an identity holds at most
_max_sessions_per_identity() live sessions (LRU beyond that; default 200,
AGENT_SDK_MAX_MCP_SESSIONS_PER_IDENTITY overrides); a session-less
non-initialize request is dispatched normally. Reverses RTGA-010 evict-all and
the "Mcp-Session-Id required" 400.
Ruling: https://github.com/wailuen/a2a-sdk/issues/201#issuecomment-6234642337
Cap made a setting: https://github.com/wailuen/a2a-sdk/issues/201#issuecomment-6235185280
"""

from __future__ import annotations

import httpx
import pytest

from agent_sdk.routes import mcp as mcp_routes
from agent_sdk.routes.mcp import (
    _MAX_SESSIONS,
    _MAX_SESSIONS_PER_IDENTITY,
    _max_sessions_per_identity,
    _sessions,
)

_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
}
_LIST = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}


async def _init(c: httpx.AsyncClient, presented: str | None = None) -> str:
    headers = {"Mcp-Session-Id": presented} if presented else {}
    r = await c.post("/mcp", json=_INIT, headers=headers)
    assert r.status_code == 200, r.text
    return r.headers["mcp-session-id"]


async def _list(c: httpx.AsyncClient, sid: str | None) -> httpx.Response:
    headers = {"Mcp-Session-Id": sid} if sid else {}
    return await c.post("/mcp", json=_LIST, headers=headers)


def _other_client(client: httpx.AsyncClient) -> httpx.AsyncClient:
    app = client.app  # type: ignore[attr-defined]
    _, token = app.state.auth.api_keys.mint("other-caller", admin=True)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


_CAP = 4


@pytest.fixture
def small_cap(monkeypatch: pytest.MonkeyPatch) -> int:
    """Shrink the SDK default so cap behaviour is testable with a few inits."""
    monkeypatch.setattr(mcp_routes, "_MAX_SESSIONS_PER_IDENTITY", _CAP)
    return _CAP


def test_default_cap_admits_an_org(client: httpx.AsyncClient) -> None:
    # Sized like the per-identity stream cap: under an org-wide OAuth client or
    # shared API key the identity is the whole org (issuecomment-6235185280).
    assert _MAX_SESSIONS_PER_IDENTITY == 200
    assert _max_sessions_per_identity(client.app) == 200  # type: ignore[attr-defined]


def test_setting_overrides_and_is_clamped(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    settings = client.app.state.settings  # type: ignore[attr-defined]
    monkeypatch.setattr(settings, "max_mcp_sessions_per_identity", 7, raising=False)
    assert _max_sessions_per_identity(client.app) == 7  # type: ignore[attr-defined]
    monkeypatch.setattr(
        settings, "max_mcp_sessions_per_identity", _MAX_SESSIONS + 5, raising=False
    )
    assert _max_sessions_per_identity(client.app) == _MAX_SESSIONS  # type: ignore[attr-defined]


def test_setting_rejects_zero() -> None:
    # A 0 would read as "unlimited" but cap every identity at nothing; the
    # field is ge=1 like max_mcp_streams_per_identity.
    from agent_sdk.config import BaseAgentSettings

    field = BaseAgentSettings.model_fields["max_mcp_sessions_per_identity"]
    assert field.alias == "AGENT_SDK_MAX_MCP_SESSIONS_PER_IDENTITY"
    assert any(getattr(m, "ge", None) == 1 for m in field.metadata)


async def test_many_clients_on_one_key_coexist_under_default(
    client: httpx.AsyncClient,
) -> None:
    sids = [await _init(client) for _ in range(8)]
    for sid in sids:
        assert (await _list(client, sid)).status_code == 200


async def test_two_clients_same_key_both_keep_working(client: httpx.AsyncClient) -> None:
    a = await _init(client)
    b = await _init(client)
    assert a != b
    assert (await _list(client, a)).status_code == 200
    assert (await _list(client, b)).status_code == 200


async def test_fifth_initialize_evicts_only_lru(
    client: httpx.AsyncClient, small_cap: int
) -> None:
    sessions = _sessions(client.app)  # type: ignore[attr-defined]
    s1, s2, s3, s4 = [await _init(client) for _ in range(4)]
    assert (await _list(client, s1)).status_code == 200  # s1 now most recent
    s5 = await _init(client)
    assert s2 not in sessions
    for sid in (s1, s3, s4, s5):
        assert sid in sessions
        assert (await _list(client, sid)).status_code == 200
    assert (await _list(client, s2)).status_code == 404


async def test_reinitialize_evicts_only_presented_session(client: httpx.AsyncClient) -> None:
    sessions = _sessions(client.app)  # type: ignore[attr-defined]
    a = await _init(client)
    b = await _init(client)
    new = await _init(client, presented=a)
    assert a not in sessions
    assert b in sessions and new in sessions
    assert (await _list(client, b)).status_code == 200


async def test_other_identity_sessions_survive(
    client: httpx.AsyncClient, small_cap: int
) -> None:
    async with _other_client(client) as other:
        theirs = await _init(other)
        mine = [await _init(client) for _ in range(6)]
        await _init(client, presented=mine[-1])
        assert (await _list(other, theirs)).status_code == 200
        # presenting another identity's id on initialize never evicts it
        await _init(client, presented=theirs)
        assert (await _list(other, theirs)).status_code == 200
        # and a foreign id on a normal call is a plain 404
        assert (await _list(client, theirs)).status_code == 404


async def test_sessionless_request_with_live_sessions_dispatches(
    client: httpx.AsyncClient,
) -> None:
    await _init(client)
    r = await _list(client, None)
    assert r.status_code == 200, r.text
    assert "result" in r.json()


async def test_owner_at_cap_never_evicts_other_identity_at_global_cap(
    client: httpx.AsyncClient, monkeypatch: pytest.MonkeyPatch, small_cap: int
) -> None:
    monkeypatch.setattr(mcp_routes, "_MAX_SESSIONS", 6)
    async with _other_client(client) as other:
        theirs = [await _init(other) for _ in range(2)]
        for _ in range(small_cap):
            await _init(client)
        for _ in range(3):
            await _init(client)
        for sid in theirs:
            assert (await _list(other, sid)).status_code == 200
