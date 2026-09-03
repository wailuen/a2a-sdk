"""GH-143 — GET /mcp heartbeat streams must be bounded (global + per-identity).

Root cause: mcp_get returns an authenticated, indefinitely-held
text/event-stream heartbeat with no tracking of concurrent open streams, per-
identity or global. The server is single-process/single-worker by design, so
an unbounded number of open heartbeat streams degrades the whole process for
every tenant.

This module verifies:
- a bounded app-state tracking structure exists (`_get_streams`), mirroring
  the `_sse_queues()` accessor pattern.
- a cap constant gates `mcp_get`, enforced both globally and per-identity,
  BEFORE the StreamingResponse is created.
- the stream is deregistered on disconnect/cancellation, freeing capacity.
- one identity's open streams never count against another identity's quota.
- RT-001: a slot registered before the StreamingResponse exists is released
  even when heartbeats()'s generator body never starts (Starlette's
  spec_version<2.4 path cancelling stream_response() at the
  send(http.response.start) checkpoint).
"""

from __future__ import annotations

import asyncio
import logging
import time

import httpx
import pytest

from agent_sdk.routes import mcp as mcp_module
from agent_sdk.routes.mcp import SUPPORTED_PROTOCOL_VERSIONS, _get_streams


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_mcp_get_429_headers(r: httpx.Response) -> None:
    """RT-006: mcp_get's 429 must carry Retry-After (so a well-behaved client
    backs off instead of hot-looping) and MCP-Protocol-Version (mirroring
    every other mcp_get response, per GH-111 — a client needs it to retry
    with a recognized version)."""
    assert r.headers.get("Retry-After") == "5", (
        f"mcp_get's 429 must carry Retry-After: 5; got {r.headers.get('Retry-After')!r}"
    )
    assert r.headers.get("MCP-Protocol-Version") == SUPPORTED_PROTOCOL_VERSIONS[0], (
        "mcp_get's 429 must carry MCP-Protocol-Version; got "
        f"{r.headers.get('MCP-Protocol-Version')!r}"
    )


async def _still_streaming(task: "asyncio.Task[httpx.Response]", timeout: float = 0.5) -> bool:
    """True when `task` has NOT completed within `timeout` — i.e. the GET /mcp
    call was admitted and is blocked in the infinite heartbeat loop, mirroring
    the wait_for-based detection already used in test_http_protocol.py (the
    ASGI test transport buffers the full body, so a completed call always
    means the stream ended/was-rejected, never "still open")."""
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
# Structural checks
# ---------------------------------------------------------------------------


def test_get_stream_cap_constants_are_set() -> None:
    from agent_sdk.routes.mcp import (
        _MAX_GET_STREAMS,
        _MAX_GET_STREAMS_PER_IDENTITY,
        _MAX_SESSIONS,
    )

    assert isinstance(_MAX_GET_STREAMS, int)
    assert isinstance(_MAX_GET_STREAMS_PER_IDENTITY, int)
    assert 0 < _MAX_GET_STREAMS_PER_IDENTITY <= _MAX_GET_STREAMS <= _MAX_SESSIONS


def test_get_streams_accessor_mirrors_sse_queues_pattern(app) -> None:
    """`_get_streams(app)` lazily initializes `app.state.mcp_get_streams` and
    returns the SAME object on subsequent calls — the exact accessor pattern
    `_sse_queues()` uses for the legacy SSE transport."""
    streams = _get_streams(app)
    assert streams is app.state.mcp_get_streams
    assert dict(streams) == {}
    assert _get_streams(app) is streams


# ---------------------------------------------------------------------------
# Live enforcement — per-identity cap
# ---------------------------------------------------------------------------


async def test_per_identity_cap_rejects_extra_stream(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS_PER_IDENTITY", 2)
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS", 1_000)
    streams = _get_streams(app)

    tasks = [asyncio.create_task(client.get("/mcp")) for _ in range(2)]
    try:
        for t in tasks:
            assert await _still_streaming(t), "expected stream to be admitted (still open)"
        assert len(streams) == 2

        r3 = await asyncio.wait_for(client.get("/mcp"), timeout=5)
        assert r3.status_code == 429, (
            f"3rd concurrent GET /mcp from the same identity must be rejected; got {r3.status_code}: {r3.text}"
        )
        _assert_mcp_get_429_headers(r3)
        assert len(streams) == 2, "a rejected request must not register a stream"
    finally:
        for t in tasks:
            await _cancel(t)


async def test_per_identity_cap_does_not_count_against_other_identity(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS_PER_IDENTITY", 1)
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS", 1_000)
    streams = _get_streams(app)

    t_a = asyncio.create_task(client.get("/mcp"))
    try:
        assert await _still_streaming(t_a)
        assert len(streams) == 1

        # Identity A is now at its own cap — a 2nd request from A must 429.
        r_a2 = await asyncio.wait_for(client.get("/mcp"), timeout=5)
        assert r_a2.status_code == 429, r_a2.text
        _assert_mcp_get_429_headers(r_a2)

        # A fresh identity B must NOT be blocked by A's quota.
        _, token_b = app.state.auth.api_keys.mint("gh143-identity-b")
        async with _make_client(app, token_b) as client_b:
            t_b = asyncio.create_task(client_b.get("/mcp"))
            try:
                assert await _still_streaming(t_b), (
                    "a different identity's stream must be admitted despite identity A's cap"
                )
                assert len(streams) == 2
            finally:
                await _cancel(t_b)
    finally:
        await _cancel(t_a)


# ---------------------------------------------------------------------------
# Live enforcement — global cap
# ---------------------------------------------------------------------------


async def test_global_cap_rejects_once_reached_across_identities(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS", 2)
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS_PER_IDENTITY", 1_000)
    streams = _get_streams(app)

    _, token_b = app.state.auth.api_keys.mint("gh143-identity-global-b")
    client_b = _make_client(app, token_b)
    t_a = asyncio.create_task(client.get("/mcp"))
    t_b = None
    try:
        assert await _still_streaming(t_a)

        t_b = asyncio.create_task(client_b.get("/mcp"))
        assert await _still_streaming(t_b)
        assert len(streams) == 2, "global cap reached: exactly 2 streams tracked"

        # A brand-new 3rd identity — with NO prior streams of its own — must
        # still be rejected once the GLOBAL cap is reached.
        _, token_c = app.state.auth.api_keys.mint("gh143-identity-global-c")
        async with _make_client(app, token_c) as client_c:
            r_c = await asyncio.wait_for(client_c.get("/mcp"), timeout=5)
            assert r_c.status_code == 429, (
                f"a 3rd stream must be rejected once the global cap is reached; got {r_c.status_code}: {r_c.text}"
            )
            _assert_mcp_get_429_headers(r_c)
        assert len(streams) == 2
    finally:
        if t_b is not None:
            await _cancel(t_b)
        await _cancel(t_a)
        await client_b.aclose()


# ---------------------------------------------------------------------------
# Disconnected stream frees its slot
# ---------------------------------------------------------------------------


async def test_disconnected_stream_frees_capacity_for_new_stream(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS_PER_IDENTITY", 1)
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS", 1_000)
    streams = _get_streams(app)

    t1 = asyncio.create_task(client.get("/mcp"))
    assert await _still_streaming(t1)
    assert len(streams) == 1

    r_full = await asyncio.wait_for(client.get("/mcp"), timeout=5)
    assert r_full.status_code == 429, r_full.text
    _assert_mcp_get_429_headers(r_full)

    # Simulate a client disconnect: cancel the open stream's task.
    await _cancel(t1)
    assert len(streams) == 0, (
        "cancelling/disconnecting the open stream must deregister it in the "
        "heartbeats() finally block, freeing its capacity slot"
    )

    t2 = asyncio.create_task(client.get("/mcp"))
    try:
        assert await _still_streaming(t2), "a new stream must now be admitted after capacity was freed"
        assert len(streams) == 1
    finally:
        await _cancel(t2)


# ---------------------------------------------------------------------------
# RT-001 — slot released even when heartbeats()'s generator body never starts
# ---------------------------------------------------------------------------


async def test_get_disconnect_before_stream_body_starts_still_frees_slot(
    client: httpx.AsyncClient, app
) -> None:
    """Drives a raw ASGI GET /mcp whose ``send()`` suspends indefinitely on
    ``http.response.start`` (the checkpoint uvicorn suspends at on a real
    disconnect) while ``receive()`` reports the client already gone. This
    exercises Starlette's spec_version<2.4 path (the default when no
    ``asgi.spec_version`` is present in scope, as with httpx's ASGITransport
    used elsewhere in this module): ``stream_response()`` is cancelled at the
    ``send(http.response.start)`` await point, so ``heartbeats()``'s frame is
    never entered — proven here by asserting no body chunk is ever sent — and
    its ``finally`` never runs. The registered slot must still be released —
    via the StreamingResponse's BackgroundTask, which this test proves fires
    — not leaked for the process lifetime."""
    streams = _get_streams(app)
    assert len(streams) == 0

    _, token = app.state.auth.api_keys.mint("gh143-rt001-disconnect")

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    sent_message_types: list[str] = []

    async def send(message: dict) -> None:
        sent_message_types.append(message["type"])
        if message["type"] == "http.response.start":
            # Never resolves on its own — only cancellation (triggered by
            # listen_for_disconnect observing the disconnect above) ends
            # this await, mirroring uvicorn's send() drain checkpoint.
            await asyncio.Event().wait()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/mcp",
        "raw_path": b"/mcp",
        "query_string": b"",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "server": ("test", 80),
        "client": ("test-client", 12345),
        "root_path": "",
    }

    call_task = asyncio.create_task(app(scope, receive, send))
    try:
        for _ in range(50):
            if sent_message_types:
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail(
                "mcp_get never reached send(http.response.start) within the "
                "poll window — test setup did not exercise the target path"
            )

        for _ in range(50):
            if len(streams) == 0:
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail("stream slot was never released within the poll window")

        assert sent_message_types == ["http.response.start"], (
            "heartbeats()'s body must never have been entered — no body chunk "
            f"may have been sent; got {sent_message_types}"
        )
    finally:
        call_task.cancel()
        try:
            await call_task
        except BaseException:
            pass

    assert len(streams) == 0, (
        "a stream slot registered before the StreamingResponse existed leaked "
        "past a disconnect that pre-empted the generator body ever starting"
    )


# ---------------------------------------------------------------------------
# RT-001 — the TTL backstop must never reclaim a still-live slot
# ---------------------------------------------------------------------------


async def test_prune_never_evicts_a_still_open_stream_regardless_of_elapsed_time(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RT-001: a slot backing a stream whose owning task is still running
    must never be reclaimed by ``_prune_get_streams``, no matter how much
    wall-clock time has elapsed since it last touched its entry — e.g. its
    ``send()`` is backpressured, or its heartbeat ``asyncio.sleep`` overshoots
    under event-loop congestion, exactly the load ``_MAX_GET_STREAMS`` exists
    to bound. Reclaiming must be driven by a liveness fact (the owning task
    having actually finished), never a timing heuristic, so
    ``len(streams)`` can never exceed the cap while the stream is still
    open — verified here by asserting a same-identity request over the
    (now nominally 'expired') cap is still rejected with 429, not admitted."""
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS", 1)
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS_PER_IDENTITY", 1_000)
    streams = _get_streams(app)

    t1 = asyncio.create_task(client.get("/mcp"))
    try:
        assert await _still_streaming(t1)
        assert len(streams) == 1

        # Simulate the exact scenario the TTL backstop mishandled: wall-clock
        # time advances far past any plausible TTL window while the stream is
        # still open and its owning task is still running (no re-touch needed
        # or attempted).
        real_monotonic = time.monotonic
        monkeypatch.setattr(mcp_module.time, "monotonic", lambda: real_monotonic() + 10_000)

        t2 = asyncio.create_task(client.get("/mcp"))
        try:
            if await _still_streaming(t2):
                pytest.fail(
                    "a still-open stream's slot was reclaimed by wall-clock "
                    "pruning, freeing capacity and admitting a 2nd stream "
                    "over the cap instead of rejecting it with 429"
                )
            r2 = t2.result()
            assert r2.status_code == 429, (
                "a still-open stream's slot must never be reclaimed by "
                f"wall-clock pruning; got {r2.status_code}: {r2.text}"
            )
            _assert_mcp_get_429_headers(r2)
        finally:
            await _cancel(t2)
        assert len(streams) == 1, "the live stream's slot must still be tracked"
    finally:
        await _cancel(t1)


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
    rejection — a static message only."""
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS_PER_IDENTITY", 1)
    monkeypatch.setattr(mcp_module, "_MAX_GET_STREAMS", 1_000)

    subject = "gh143-si2-leak-canary-subject"
    _, token = app.state.auth.api_keys.mint(subject)
    async with _make_client(app, token) as leak_client:
        t1 = asyncio.create_task(leak_client.get("/mcp"))
        try:
            assert await _still_streaming(t1)

            with sdk_caplog("agent_sdk.routes.mcp", logging.DEBUG) as records:
                r2 = await asyncio.wait_for(leak_client.get("/mcp"), timeout=5)
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
