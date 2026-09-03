"""RT-002 (round 6, fresh-lens) — the ADMITTED path of the two MCP SSE verbs
must be asserted at the wire, not merely observed as "did not complete".

Root cause: ``routes/mcp.py``'s module docstring declares one invariant
load-bearing — "Returning 405 here breaks Claude.ai Desktop (pitchbook
LRN-053) — never" — and w040 then added two new early-return branches to
``mcp_get`` (the global and per-identity 429s) and rewrapped ``heartbeats()``
in a ``try/finally``. Every ``GET /mcp`` assertion in the suite covered a
REJECTION (429/400/403/401) or used ``_still_streaming()``
(``tests/test_gh143_mcp_get_stream_cap.py``), which only proves the request
did not complete — a 405, a 500, or a ``text/plain`` body would satisfy it
just as well. Nothing asserted the status code or the ``Content-Type`` of an
admitted stream, on either ``GET /mcp`` or ``GET /mcp/sse``, so a regression
turning the connection-critical verb into a non-200 or non-SSE response
passed the whole suite green (LRN-001: a wave touching a protocol route owes
TestClient-level header assertions).

Why raw ASGI rather than the ``client`` fixture: both streams are infinite by
design (no server-initiated close), and httpx's ``ASGITransport`` buffers the
full body before returning a response — so ``await client.get("/mcp")`` can
never yield a ``Response`` object to inspect. Driving the app directly lets us
read the ``http.response.start`` message (status + headers) and the first body
chunk while the stream is still open, then cancel. Same send-capture pattern
as ``test_gh143_mcp_get_stream_cap.py``'s disconnect test, inverted: that one
proves no body chunk is ever sent, this one proves the right one is.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from agent_sdk.routes.mcp import _get_streams


async def _open_sse(app, token: str, path: str) -> tuple[dict[str, Any], list[bytes]]:
    """Drive one authenticated GET at ``path`` through the raw ASGI interface.

    Returns the captured ``http.response.start`` (status + lower-cased header
    map) and every body chunk sent up to and including the first one. The
    request task is always cancelled before returning, so the admission slot
    it registered is freed for the next test.
    """
    start: dict[str, Any] = {}
    chunks: list[bytes] = []
    first_chunk = asyncio.Event()

    async def receive() -> dict:
        # Never disconnects: the client stays connected for the whole probe,
        # so the handler follows the ADMITTED path rather than an early unwind.
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def send(message: dict) -> None:
        if message["type"] == "http.response.start":
            start["status"] = message["status"]
            start["headers"] = {
                key.decode().lower(): value.decode() for key, value in message["headers"]
            }
        elif message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))
            first_chunk.set()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [(b"authorization", f"Bearer {token}".encode())],
        "server": ("test", 80),
        "client": ("test-client", 12345),
        "root_path": "",
    }

    call_task = asyncio.create_task(app(scope, receive, send))
    try:
        await asyncio.wait_for(first_chunk.wait(), timeout=5)
    except asyncio.TimeoutError:  # pragma: no cover - diagnostic path
        pytest.fail(
            f"GET {path} sent no body chunk within the deadline; captured "
            f"response start = {start or 'nothing'}"
        )
    finally:
        call_task.cancel()
        try:
            await call_task
        except BaseException:
            pass
    return start, chunks


def _assert_sse_200(start: dict[str, Any], path: str) -> None:
    assert start.get("status") == 200, (
        f"GET {path} must return 200 on the admitted path — a 405 specifically "
        f"breaks Claude.ai Desktop (LRN-053); got {start.get('status')!r}"
    )
    content_type = start.get("headers", {}).get("content-type", "")
    assert content_type.startswith("text/event-stream"), (
        f"GET {path} must return an SSE stream; got Content-Type {content_type!r}"
    )
    # SSE_HEADERS ride every admitted stream: without them a proxy may buffer
    # the channel and the client never observes it as established.
    assert start["headers"].get("cache-control") == "no-cache", start["headers"]
    assert start["headers"].get("x-accel-buffering") == "no", start["headers"]


async def test_mcp_get_admitted_stream_is_200_text_event_stream(
    client: httpx.AsyncClient, app
) -> None:
    """The happy path ``mcp_get``'s docstring calls connection-critical: an
    admitted GET /mcp answers 200 + text/event-stream and flushes the padding
    comment immediately, so the client marks the channel open."""
    _, token = app.state.auth.api_keys.mint("rt002-r6-mcp-get")

    start, chunks = await _open_sse(app, token, "/mcp")

    _assert_sse_200(start, "/mcp")
    assert chunks and chunks[0].startswith(b": "), (
        "the first chunk must be the padding comment that forces proxy buffers "
        f"to flush; got {chunks[0][:40]!r}"
    )
    assert chunks[0].endswith(b"\n\n"), "the padding comment is not a complete SSE frame"


async def test_mcp_sse_admitted_stream_is_200_with_endpoint_first_frame(
    client: httpx.AsyncClient, app
) -> None:
    """Legacy HTTP+SSE: an admitted GET /mcp/sse answers 200 +
    text/event-stream and its FIRST frame is the ``event: endpoint`` line
    announcing the session-bound messages URL — without it a legacy client has
    nowhere to POST and the session is dead on arrival."""
    _, token = app.state.auth.api_keys.mint("rt002-r6-mcp-sse")

    start, chunks = await _open_sse(app, token, "/mcp/sse")

    _assert_sse_200(start, "/mcp/sse")
    first = chunks[0].decode()
    assert first.startswith("event: endpoint\n"), (
        f"GET /mcp/sse's first frame must be the endpoint announcement; got {first!r}"
    )
    assert "data: /mcp/messages?session_id=" in first, (
        f"the endpoint frame must carry the session-bound messages URL; got {first!r}"
    )


async def test_admitted_probe_frees_its_slot(client: httpx.AsyncClient, app) -> None:
    """Guard against the two tests above passing while leaking budget: the
    probe cancels the request task, so both routes' release layers must have
    reclaimed the slot by the time it returns."""
    _, token = app.state.auth.api_keys.mint("rt002-r6-slot-hygiene")
    streams = _get_streams(app)

    for path in ("/mcp", "/mcp/sse"):
        await _open_sse(app, token, path)
        for _ in range(50):
            if len(streams) == 0:
                break
            await asyncio.sleep(0.05)
        assert len(streams) == 0, f"GET {path} leaked its admission slot: {dict(streams)}"
