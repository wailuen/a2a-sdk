"""RT-001 (round 4) — a stream slot's FULL release surface must be reclaimed
when the owning ASGI request task is hard-cancelled.

Root cause: both routers register per-stream state BEFORE the
``StreamingResponse`` exists, then rely on the generator body's ``finally`` to
release it. That ``finally`` is not a lifecycle hook — it never runs when the
request task is cancelled at Starlette's ``send(http.response.start)``
checkpoint, before ``stream_response`` pulls the first chunk. Unlike a client
disconnect (which Starlette absorbs inside the StreamingResponse cancel scope,
so ``await self.background()`` still runs), a hard cancellation of the request
task skips the BackgroundTask too.

That left two leaks:

* ``mcp_sse`` registers TWO structures under one key — its ``_get_streams()``
  admission slot and its ``_sse_queues()`` session-router record — but
  ``_prune_get_streams`` reclaimed only the first. Because the slot half
  self-healed, the admission cap never throttled repetition, so every
  cancelled request pinned an ``asyncio.Queue(maxsize=256)`` for the process
  lifetime. (The old ``_MAX_SSE_SESSIONS`` hard bound had been deleted in the
  same change that introduced the shared cap.)
* ``a2a._open_stream`` never unsubscribed at all, growing the unbounded
  ``record.subscriptions`` list that ``store.publish`` walks per frame.

This module pins the invariant both fixes establish.
"""

from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from agent_sdk.common.admission import StreamSlot
from agent_sdk.routes import mcp as mcp_module
from agent_sdk.routes.mcp import _get_streams, _sse_queues


# ---------------------------------------------------------------------------
# Raw-ASGI driver: suspend at send(http.response.start), never disconnect
# ---------------------------------------------------------------------------


async def _suspended_request(
    app: Any, path: str, token: str, method: str = "GET", body: bytes = b""
) -> "tuple[asyncio.Task[None], list[str]]":
    """Drive a raw ASGI request whose ``send()`` suspends forever on
    ``http.response.start`` and whose ``receive()`` never reports a
    disconnect. Returns once that checkpoint is reached, so the caller can
    hard-cancel the request task from outside — the one unwind path that
    skips BOTH the generator ``finally`` and the BackgroundTask."""
    body_sent = False

    async def receive() -> dict:
        nonlocal body_sent
        if not body_sent:
            body_sent = True
            return {"type": "http.request", "body": body, "more_body": False}
        await asyncio.Event().wait()  # never disconnects
        return {"type": "http.disconnect"}

    sent: list[str] = []

    async def send(message: dict) -> None:
        sent.append(message["type"])
        if message["type"] == "http.response.start":
            await asyncio.Event().wait()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},  # no spec_version -> Starlette's <2.4 path
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (b"authorization", f"Bearer {token}".encode()),
            (b"content-type", b"application/json"),
        ],
        "server": ("test", 80),
        "client": ("test-client", 12345),
        "root_path": "",
    }
    task = asyncio.create_task(app(scope, receive, send))
    for _ in range(100):
        if sent:
            return task, sent
        await asyncio.sleep(0.02)
    task.cancel()
    pytest.fail(f"{method} {path} never reached send(http.response.start)")


async def _hard_cancel(task: "asyncio.Task[Any]") -> None:
    task.cancel()
    try:
        await task
    except BaseException:
        pass
    await asyncio.sleep(0.05)


# ---------------------------------------------------------------------------
# MCP — the backstop must reclaim BOTH structures mcp_sse registers
# ---------------------------------------------------------------------------


async def test_sse_hard_cancel_frees_both_slot_and_session_queue(app) -> None:
    streams = _get_streams(app)
    queues = _sse_queues(app)
    assert len(streams) == 0 and len(queues) == 0

    _, token = app.state.auth.api_keys.mint("rt001-r4-sse-cancel")

    task, sent = await _suspended_request(app, "/mcp/sse", token)
    assert sent == ["http.response.start"], (
        f"stream()'s body must never have been entered; got {sent}"
    )
    assert len(streams) == 1 and len(queues) == 1

    await _hard_cancel(task)

    # Layer 3 — exactly how mcp_get/mcp_sse invoke it on the next admission.
    await mcp_module._prune_get_streams(streams)

    assert len(streams) == 0, "the admission slot must be reclaimed"
    assert len(queues) == 0, (
        "the session-router entry registered under the SAME key must be "
        "reclaimed by the same backstop — reclaiming only the slot leaves an "
        "asyncio.Queue pinned for the process lifetime while the self-healed "
        "slot lets the leak repeat without ever hitting the admission cap"
    )


async def test_repeated_hard_cancels_never_accumulate_sse_queue_entries(app) -> None:
    """The leak's severity came from repetition: the slot half self-healed, so
    the cap never throttled it. Six cycles must leave nothing behind."""
    streams = _get_streams(app)
    queues = _sse_queues(app)
    _, token = app.state.auth.api_keys.mint("rt001-r4-sse-repeat")

    for _ in range(6):
        task, _sent = await _suspended_request(app, "/mcp/sse", token)
        await _hard_cancel(task)
        await mcp_module._prune_get_streams(streams)

    assert len(queues) == 0, f"leaked {len(queues)} orphaned session queues"
    assert len(streams) == 0


async def test_sse_queues_is_a_subset_of_get_streams_while_live(
    client: httpx.AsyncClient, app
) -> None:
    """The structural invariant that makes a separate ``_MAX_SSE_SESSIONS``
    bound unnecessary: every ``_sse_queues()`` key is also a live
    ``_get_streams()`` key, so ``_sse_queues()`` is bounded by
    ``_MAX_GET_STREAMS`` by construction."""
    streams = _get_streams(app)
    queues = _sse_queues(app)

    tasks = [asyncio.create_task(client.get("/mcp/sse")) for _ in range(3)]
    try:
        for _ in range(50):
            if len(queues) == 3:
                break
            await asyncio.sleep(0.02)
        assert set(queues).issubset(set(streams)), (
            "every session-router entry must be backed by a live admission slot"
        )
    finally:
        for t in tasks:
            await _hard_cancel(t)


async def test_prune_reclaims_via_the_records_own_release_callable(app) -> None:
    """Pins the mechanism, not just the outcome: the backstop must reclaim by
    invoking the slot's own release, so a route that registers additional
    state under its key cannot drift out of the reaper's reach again."""
    streams = _get_streams(app)
    calls: list[str] = []

    done_task = asyncio.create_task(asyncio.sleep(0))
    await done_task
    assert done_task.done()

    async def release() -> None:
        calls.append("released")
        streams.pop("sentinel", None)

    streams["sentinel"] = StreamSlot(
        owner="api_key:someone", owning_task=done_task, release=release
    )
    await mcp_module._prune_get_streams(streams)

    assert calls == ["released"], "prune must call the record's release callable"
    assert "sentinel" not in streams


# ---------------------------------------------------------------------------
# A2A — the same defect class on the task-store subscription
# ---------------------------------------------------------------------------


async def test_a2a_stream_hard_cancel_does_not_leak_a_subscription(app) -> None:
    # The raw-ASGI request below must run as the SAME identity that owns the
    # task, or :subscribe answers 404 and never reaches _open_stream — which
    # would make this test pass vacuously (the suspended send() cannot tell a
    # JSONResponse's http.response.start from a StreamingResponse's).
    _, token = app.state.auth.api_keys.mint("rt001-r4-a2a-cancel")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as owner_client:
        r = await owner_client.post(
            "/v1/message:send",
            json={
                "message": {
                    "kind": "message",
                    "role": "user",
                    "messageId": "m-rt001-r4",
                    "parts": [{"kind": "text", "text": "hello"}],
                }
            },
        )
        assert r.status_code == 200, r.text
        task_id = r.json()["id"]

    record = app.state.task_store._records[task_id]
    baseline = len(record.subscriptions)

    for i in range(8):
        t, sent = await _suspended_request(
            app, f"/v1/tasks/{task_id}:subscribe", token, method="POST", body=b"{}"
        )
        # Anti-vacuity, and the actual regression assertion: the list must not
        # grow with repetition. Before the fix this climbed 1, 2, 3, ... — each
        # hard-cancelled request pinning a Subscription that store.publish()
        # would walk for every subsequent frame. The count here proves the
        # request reached _open_stream AND that the previous iteration's orphan
        # was reclaimed by the liveness-keyed backstop in store.subscribe().
        assert len(record.subscriptions) == baseline + 1, (
            f"iteration {i}: expected exactly one live subscription; got "
            f"{len(record.subscriptions)} — either :subscribe never reached "
            f"_open_stream (vacuous test) or hard-cancelled subscriptions are "
            f"accumulating on record.subscriptions"
        )
        assert sent == ["http.response.start"], (
            f"gen()'s body must never have been entered; got {sent}"
        )
        await _hard_cancel(t)

    # At most the final iteration's orphan may remain — it is reclaimed by the
    # next subscribe(), so the list is bounded rather than monotonically
    # growing. Prove that reclamation explicitly.
    assert len(record.subscriptions) <= baseline + 1, (
        f"record.subscriptions must stay bounded across repeated hard-cancels; "
        f"got {len(record.subscriptions)}"
    )
    store = app.state.task_store
    sub = store.subscribe(task_id)
    try:
        assert len(record.subscriptions) == baseline + 1, (
            "the next subscribe() must reclaim every orphan whose owning "
            "request task has finished"
        )
    finally:
        store.unsubscribe(task_id, sub)
    assert len(record.subscriptions) == baseline
