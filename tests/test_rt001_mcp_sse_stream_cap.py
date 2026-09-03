"""RT-001 — GET /mcp/sse must share GET /mcp's admission cap, reject-not-evict.

Root cause (redteam finding on GH-143): GH-143's concurrency cap bounded only
GET /mcp. GET /mcp/sse (mcp_sse) is an identically-authenticated,
identically-indefinite text/event-stream held open on the same
single-process connection pool, but was left uncapped — bypassable by
changing one path segment. Its own eviction strategy (`_MAX_SSE_SESSIONS`
evict-oldest) only dropped the `_sse_queues()` bookkeeping entry; the
generator kept running its heartbeat loop until the client left, so eviction
never actually bounded live streams. Worse, evict-oldest was a cross-tenant
DoS: filling the cap popped the oldest entry regardless of owner, so another
tenant's still-open SSE session became permanently unroutable
(POST /mcp/messages -> 404 "session not found") while its connection stayed
open.

This module verifies:
- GET /mcp and GET /mcp/sse are admitted against ONE shared global budget.
- the per-identity cap applies to GET /mcp/sse the same way it applies to
  GET /mcp.
- once at capacity, a new GET /mcp/sse request is REJECTED (429) rather than
  evicting an existing session — and an existing session's route
  (POST /mcp/messages) keeps working after another caller is rejected.
- a disconnected GET /mcp/sse stream frees its slot for a new stream.
"""

from __future__ import annotations

import asyncio
import logging

import httpx
import pytest

from agent_sdk.routes import mcp as mcp_module
from agent_sdk.routes.mcp import _get_streams, _sse_queues


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_mcp_sse_429_headers(r: httpx.Response) -> None:
    """RT-006: mcp_sse's 429 must carry Retry-After (so a well-behaved
    client backs off instead of hot-looping). Unlike mcp_get, mcp_sse never
    negotiates MCP-Protocol-Version at all (it's a legacy transport with no
    ``_negotiated_version`` call anywhere in the route, on ANY of its
    responses — not just the 429s) — its deliberate absence here is pinned,
    not merely uncovered."""
    assert r.headers.get("Retry-After") == "5", (
        f"mcp_sse's 429 must carry Retry-After: 5; got {r.headers.get('Retry-After')!r}"
    )
    assert "MCP-Protocol-Version" not in r.headers, (
        "mcp_sse (legacy transport) deliberately never emits "
        "MCP-Protocol-Version — if this now fires, mcp_sse gained version "
        "negotiation and this assertion should be updated to match mcp_get's"
    )


async def _still_streaming(task: "asyncio.Task[httpx.Response]", timeout: float = 0.5) -> bool:
    """True when `task` has NOT completed within `timeout` — i.e. the GET
    call was admitted and is blocked in the infinite stream loop. Mirrors
    test_gh143_mcp_get_stream_cap.py's helper of the same name."""
    try:
        await asyncio.wait_for(asyncio.shield(task), timeout=timeout)
        return False
    except asyncio.TimeoutError:
        return True


async def _cancel(task: "asyncio.Task[httpx.Response]") -> None:
    if not task.done():
        task.cancel()
    try:
        await task
    except BaseException:
        pass


def _make_client(app, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


# ---------------------------------------------------------------------------
# Shared global budget across both transports
# ---------------------------------------------------------------------------


async def test_global_cap_is_shared_between_get_mcp_and_get_mcp_sse(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS", 2)
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS_PER_IDENTITY", 1_000)
    streams = _get_streams(app)

    _, token_b = app.state.auth.api_keys.mint("rt001-shared-b")
    client_b = _make_client(app, token_b)
    t_get = None
    t_sse = None
    try:
        # One stream on each transport, different identities, fills the
        # shared global cap of 2.
        t_get = asyncio.create_task(client.get("/mcp"))
        assert await _still_streaming(t_get)
        t_sse = asyncio.create_task(client_b.get("/mcp/sse"))
        assert await _still_streaming(t_sse)
        assert len(streams) == 2, "GET /mcp and GET /mcp/sse must count against ONE shared budget"

        # A brand-new 3rd identity on EITHER transport must now be rejected.
        _, token_c = app.state.auth.api_keys.mint("rt001-shared-c")
        async with _make_client(app, token_c) as client_c:
            r = await asyncio.wait_for(client_c.get("/mcp/sse"), timeout=5)
            assert r.status_code == 429, (
                f"GET /mcp/sse must be rejected once the shared global cap "
                f"(exhausted partly by GET /mcp) is reached; got "
                f"{r.status_code}: {r.text}"
            )
            _assert_mcp_sse_429_headers(r)
        assert len(streams) == 2
    finally:
        if t_sse is not None:
            await _cancel(t_sse)
        if t_get is not None:
            await _cancel(t_get)
        await client_b.aclose()


# ---------------------------------------------------------------------------
# Per-identity cap applies to GET /mcp/sse
# ---------------------------------------------------------------------------


async def test_per_identity_cap_rejects_extra_sse_stream(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS_PER_IDENTITY", 2)
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS", 1_000)
    streams = _get_streams(app)

    tasks = [asyncio.create_task(client.get("/mcp/sse")) for _ in range(2)]
    try:
        for t in tasks:
            assert await _still_streaming(t), "expected SSE stream to be admitted (still open)"
        assert len(streams) == 2

        r3 = await asyncio.wait_for(client.get("/mcp/sse"), timeout=5)
        assert r3.status_code == 429, (
            f"3rd concurrent GET /mcp/sse from the same identity must be "
            f"rejected; got {r3.status_code}: {r3.text}"
        )
        _assert_mcp_sse_429_headers(r3)
        assert len(streams) == 2, "a rejected request must not register a stream"
    finally:
        for t in tasks:
            await _cancel(t)


# ---------------------------------------------------------------------------
# Reject-not-evict: another tenant's live session must survive a rejection
# ---------------------------------------------------------------------------


async def test_rejected_sse_request_does_not_evict_another_tenants_session(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """At capacity, a NEW caller must be rejected outright — the previously
    admitted tenant's session must stay live and routable, never silently
    evicted to make room (the cross-tenant DoS this finding closes)."""
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS", 1)
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS_PER_IDENTITY", 1_000)
    streams = _get_streams(app)
    queues = _sse_queues(app)

    _, token_b = app.state.auth.api_keys.mint("rt001-noevict-b")
    client_b = _make_client(app, token_b)
    t_a = asyncio.create_task(client.get("/mcp/sse"))
    try:
        assert await _still_streaming(t_a)
        assert len(streams) == 1
        (session_id_a,) = list(streams.keys())
        assert session_id_a in queues

        # A 2nd identity's stream must be rejected — not admitted by evicting A.
        r_b = await asyncio.wait_for(client_b.get("/mcp/sse"), timeout=5)
        assert r_b.status_code == 429, (
            f"identity B must be rejected once the global cap is reached, "
            f"never admitted by evicting identity A's session; got "
            f"{r_b.status_code}: {r_b.text}"
        )
        _assert_mcp_sse_429_headers(r_b)

        # Identity A's session must still be intact — both in the shared
        # admission tracker and in the legacy session router — and its
        # POST /mcp/messages route must still work (not 404).
        assert session_id_a in streams, "identity A's stream must not have been evicted"
        assert session_id_a in queues, "identity A's session must not have been evicted"

        r_msg = await client.post(
            "/mcp/messages",
            params={"session_id": session_id_a},
            json={"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}},
        )
        assert r_msg.status_code == 202, (
            f"identity A's session must still be routable after a rejected "
            f"3rd party request; got {r_msg.status_code}: {r_msg.text}"
        )
    finally:
        await _cancel(t_a)
        await client_b.aclose()


# ---------------------------------------------------------------------------
# Disconnected stream frees its slot
# ---------------------------------------------------------------------------


async def test_disconnected_sse_stream_frees_capacity_for_new_stream(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS_PER_IDENTITY", 1)
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS", 1_000)
    streams = _get_streams(app)
    queues = _sse_queues(app)

    t1 = asyncio.create_task(client.get("/mcp/sse"))
    assert await _still_streaming(t1)
    assert len(streams) == 1
    assert len(queues) == 1

    r_full = await asyncio.wait_for(client.get("/mcp/sse"), timeout=5)
    assert r_full.status_code == 429, r_full.text
    _assert_mcp_sse_429_headers(r_full)

    await _cancel(t1)
    assert len(streams) == 0, "cancelling the open SSE stream must deregister it"
    assert len(queues) == 0, "cancelling the open SSE stream must free its session router entry too"

    t2 = asyncio.create_task(client.get("/mcp/sse"))
    try:
        assert await _still_streaming(t2), "a new SSE stream must now be admitted after capacity was freed"
        assert len(streams) == 1
    finally:
        await _cancel(t2)


# ---------------------------------------------------------------------------
# RT-006 (SI-2) — a 429 rejection must not leak the caller's identity
# ---------------------------------------------------------------------------


async def test_429_rejection_does_not_leak_identity_or_bearer_token(
    app, monkeypatch: pytest.MonkeyPatch, sdk_caplog
) -> None:
    """SI-2 (workspace/todos/active/w040-gh-issues.md:40): ``_identity_key()``
    returns an OAuth subject or API-key id. That value, and the bearer token
    itself, must never appear in the cap-rejection response body or in any
    log line emitted by ``agent_sdk.routes.mcp`` while handling the
    rejection — a static message only. Mirrors mcp_get's equivalent test in
    test_gh143_mcp_get_stream_cap.py for the legacy SSE transport."""
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS_PER_IDENTITY", 1)
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS", 1_000)

    subject = "rt001-sse-si2-leak-canary-subject"
    _, token = app.state.auth.api_keys.mint(subject)
    async with _make_client(app, token) as leak_client:
        t1 = asyncio.create_task(leak_client.get("/mcp/sse"))
        try:
            assert await _still_streaming(t1)

            with sdk_caplog("agent_sdk.routes.mcp", logging.DEBUG) as records:
                r2 = await asyncio.wait_for(leak_client.get("/mcp/sse"), timeout=5)
            assert r2.status_code == 429, r2.text

            assert subject not in r2.text, (
                "the 429 body must never interpolate the caller's identity "
                f"subject (SI-2); got: {r2.text}"
            )
            assert token not in r2.text, (
                "the 429 body must never interpolate the caller's bearer "
                f"token (SI-2); got: {r2.text}"
            )
            for record in records:
                message = record.getMessage()
                assert subject not in message, (
                    f"a log line leaked the caller's identity subject (SI-2): {message!r}"
                )
                assert token not in message, (
                    f"a log line leaked the caller's bearer token (SI-2): {message!r}"
                )
        finally:
            await _cancel(t1)
