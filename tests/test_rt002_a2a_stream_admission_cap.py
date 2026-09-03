"""RT-002 (GH-143 follow-up) — A2A SSE streams must be admission-capped like
GET /mcp already is.

Root cause: ``POST /v1/tasks/{task_id}:subscribe`` and ``POST
/v1/message:stream``'s taskId-resume branch both return an authenticated,
indefinitely-held ``text/event-stream`` on the SAME single-process
connection pool GET /mcp's cap (``routes/mcp.py``'s ``_get_streams()``,
GH-143) already protects — capping only that surface left this one
reachable. ``tasks_resubscribe`` could be invoked unboundedly against ONE
task, each call appending a ``Subscription`` onto ``record.subscriptions``
— the unbounded list ``store.publish`` walks for every frame that
``_open_stream``'s own docstring names as the harm.

This module verifies:
- a bounded app-state tracking structure exists (``_a2a_streams``), mirroring
  ``routes/mcp.py``'s ``_get_streams()`` accessor pattern.
- cap constants gate ``_open_stream`` (shared by both routes), enforced both
  globally and per-``record.task.id``, BEFORE ``store.subscribe()`` /the
  ``StreamingResponse`` is created.
- one task's open streams never count against another task's quota.
- the rejection rides the standard A2A error envelope (429, ``Retry-After``).
- a completed/cancelled stream frees its slot for a new one.
"""

from __future__ import annotations

import asyncio

import httpx
import pytest

from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.routes import a2a as a2a_module
from agent_sdk.routes.a2a import _a2a_streams


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_open_task(app) -> str:
    """A fresh SUBMITTED-state task with no worker attached: subscribing to
    it blocks forever (never terminal, nothing ever published) — the A2A
    equivalent of GET /mcp's idle heartbeat loop, used so an admitted stream
    can be reliably distinguished from a rejected one by "did it complete
    within a short timeout" (mirrors tests/test_gh143_mcp_get_stream_cap.py's
    `_still_streaming`)."""
    return _make_open_task_for(app, Identity(kind="api_key", subject="rt002-task-owner"))


def _make_open_task_for(app, identity: Identity) -> str:
    task = new_task()
    record = app.state.task_store.create(task, identity)
    return record.task.id


def _make_client(app, token: str) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _still_streaming(task: "asyncio.Task[httpx.Response]", timeout: float = 0.5) -> bool:
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


def _assert_429_envelope(r: httpx.Response) -> None:
    assert r.status_code == 429, r.text
    assert r.headers.get("Retry-After") == "5", (
        f"the admission rejection must carry Retry-After: 5; got {r.headers.get('Retry-After')!r}"
    )
    body = r.json()
    assert "error" in body, f"429 on /v1/* must use the A2A error envelope; got {body}"
    assert isinstance(body["error"].get("code"), int)
    assert isinstance(body["error"].get("message"), str) and body["error"]["message"]


# ---------------------------------------------------------------------------
# Structural checks
# ---------------------------------------------------------------------------


def test_stream_cap_constants_are_set() -> None:
    assert isinstance(a2a_module._MAX_A2A_STREAMS, int)
    assert isinstance(a2a_module._MAX_A2A_STREAMS_PER_TASK, int)
    assert isinstance(a2a_module._MAX_A2A_STREAMS_PER_IDENTITY, int)
    assert 0 < a2a_module._MAX_A2A_STREAMS_PER_TASK <= a2a_module._MAX_A2A_STREAMS
    assert 0 < a2a_module._MAX_A2A_STREAMS_PER_IDENTITY <= a2a_module._MAX_A2A_STREAMS


def test_a2a_streams_accessor_mirrors_mcp_get_streams_pattern(app) -> None:
    streams = _a2a_streams(app)
    assert streams is app.state.a2a_streams
    assert dict(streams) == {}
    assert _a2a_streams(app) is streams


# ---------------------------------------------------------------------------
# Live enforcement — per-identity cap (RT-001)
# ---------------------------------------------------------------------------


async def test_per_identity_cap_rejects_extra_stream(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_IDENTITY", 2)
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS", 1_000)
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_TASK", 1_000)
    streams = _a2a_streams(app)

    tasks = [
        asyncio.create_task(client.post(f"/v1/tasks/{_make_open_task(app)}:subscribe"))
        for _ in range(2)
    ]
    try:
        for t in tasks:
            assert await _still_streaming(t), "expected subscription to be admitted (still open)"
        assert len(streams) == 2

        task3 = _make_open_task(app)
        r3 = await asyncio.wait_for(client.post(f"/v1/tasks/{task3}:subscribe"), timeout=5)
        _assert_429_envelope(r3)
        assert len(streams) == 2, "a rejected request must not register a stream"
    finally:
        for t in tasks:
            await _cancel(t)


async def test_per_identity_cap_does_not_count_against_other_identity(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RT-001: one authenticated identity holding its full share of the
    stream budget must never lock a DIFFERENT identity out of
    message:stream/tasks:subscribe — the exact cross-tenant harm
    routes/mcp.py's per-identity cap (GH-143) already prevents on GET /mcp."""
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_IDENTITY", 1)
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS", 1_000)
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_TASK", 1_000)
    streams = _a2a_streams(app)

    task_a = _make_open_task(app)
    t_a = asyncio.create_task(client.post(f"/v1/tasks/{task_a}:subscribe"))
    try:
        assert await _still_streaming(t_a)
        assert len(streams) == 1

        # Identity A (the default admin client) is now at its own cap — a 2nd
        # subscription from A, even on a DIFFERENT task, must 429.
        task_a2 = _make_open_task(app)
        r_a2 = await asyncio.wait_for(client.post(f"/v1/tasks/{task_a2}:subscribe"), timeout=5)
        _assert_429_envelope(r_a2)

        # A fresh, different identity B must NOT be blocked by identity A's quota.
        key_b, token_b = app.state.auth.api_keys.mint("rt001-a2a-identity-b")
        identity_b = Identity(kind="api_key", subject=key_b)
        task_b = _make_open_task_for(app, identity_b)
        async with _make_client(app, token_b) as client_b:
            t_b = asyncio.create_task(client_b.post(f"/v1/tasks/{task_b}:subscribe"))
            try:
                assert await _still_streaming(t_b), (
                    "a different identity's stream must be admitted despite "
                    "identity A's cap"
                )
                assert len(streams) == 2
            finally:
                await _cancel(t_b)
    finally:
        await _cancel(t_a)


# ---------------------------------------------------------------------------
# Live enforcement — per-task cap
# ---------------------------------------------------------------------------


async def test_per_task_cap_rejects_extra_subscriber(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_TASK", 2)
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS", 1_000)
    streams = _a2a_streams(app)
    task_id = _make_open_task(app)

    tasks = [
        asyncio.create_task(client.post(f"/v1/tasks/{task_id}:subscribe"))
        for _ in range(2)
    ]
    try:
        for t in tasks:
            assert await _still_streaming(t), "expected subscription to be admitted (still open)"
        assert len(streams) == 2

        r3 = await asyncio.wait_for(client.post(f"/v1/tasks/{task_id}:subscribe"), timeout=5)
        _assert_429_envelope(r3)
        assert len(streams) == 2, "a rejected request must not register a stream"
    finally:
        for t in tasks:
            await _cancel(t)


async def test_per_task_cap_does_not_count_against_other_task(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_TASK", 1)
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS", 1_000)
    streams = _a2a_streams(app)

    task_a = _make_open_task(app)
    task_b = _make_open_task(app)

    t_a = asyncio.create_task(client.post(f"/v1/tasks/{task_a}:subscribe"))
    try:
        assert await _still_streaming(t_a)
        assert len(streams) == 1

        # Task A is now at its own cap — a 2nd subscriber on A must 429.
        r_a2 = await asyncio.wait_for(client.post(f"/v1/tasks/{task_a}:subscribe"), timeout=5)
        _assert_429_envelope(r_a2)

        # A different task must NOT be blocked by A's quota.
        t_b = asyncio.create_task(client.post(f"/v1/tasks/{task_b}:subscribe"))
        try:
            assert await _still_streaming(t_b), (
                "a different task's subscription must be admitted despite task A's cap"
            )
            assert len(streams) == 2
        finally:
            await _cancel(t_b)
    finally:
        await _cancel(t_a)


# ---------------------------------------------------------------------------
# Live enforcement — global cap
# ---------------------------------------------------------------------------


async def test_global_cap_rejects_once_reached_across_tasks(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS", 2)
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_TASK", 1_000)
    streams = _a2a_streams(app)

    task_a = _make_open_task(app)
    task_b = _make_open_task(app)
    task_c = _make_open_task(app)

    t_a = asyncio.create_task(client.post(f"/v1/tasks/{task_a}:subscribe"))
    t_b = None
    try:
        assert await _still_streaming(t_a)

        t_b = asyncio.create_task(client.post(f"/v1/tasks/{task_b}:subscribe"))
        assert await _still_streaming(t_b)
        assert len(streams) == 2, "global cap reached: exactly 2 streams tracked"

        # A brand-new 3rd task — with no prior subscribers of its own — must
        # still be rejected once the GLOBAL cap is reached.
        r_c = await asyncio.wait_for(client.post(f"/v1/tasks/{task_c}:subscribe"), timeout=5)
        _assert_429_envelope(r_c)
        assert len(streams) == 2
    finally:
        if t_b is not None:
            await _cancel(t_b)
        await _cancel(t_a)


# ---------------------------------------------------------------------------
# message:stream's taskId-resume branch shares the same budget
# ---------------------------------------------------------------------------


async def test_message_stream_resume_branch_is_admission_capped_too(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both callers of _open_stream (tasks_resubscribe AND message_stream's
    taskId branch) must share the SAME budget — a cap only one of them
    enforces is trivially bypassed by calling the other, exactly like
    GET /mcp vs GET /mcp/sse (GH-143)."""
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_TASK", 1)
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS", 1_000)
    streams = _a2a_streams(app)
    task_id = _make_open_task(app)

    t1 = asyncio.create_task(client.post(f"/v1/tasks/{task_id}:subscribe"))
    try:
        assert await _still_streaming(t1)
        assert len(streams) == 1

        r2 = await asyncio.wait_for(
            client.post(
                "/v1/message:stream",
                json={
                    "message": {
                        "kind": "message",
                        "role": "user",
                        "messageId": "rt002-resume-msg",
                        "taskId": task_id,
                        "parts": [{"kind": "text", "text": "hello"}],
                    }
                },
            ),
            timeout=5,
        )
        _assert_429_envelope(r2)
    finally:
        await _cancel(t1)


# ---------------------------------------------------------------------------
# Disconnected stream frees its slot
# ---------------------------------------------------------------------------


async def test_disconnected_stream_frees_capacity_for_new_stream(
    client: httpx.AsyncClient, app, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_TASK", 1)
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS", 1_000)
    streams = _a2a_streams(app)
    task_id = _make_open_task(app)

    t1 = asyncio.create_task(client.post(f"/v1/tasks/{task_id}:subscribe"))
    assert await _still_streaming(t1)
    assert len(streams) == 1

    r_full = await asyncio.wait_for(client.post(f"/v1/tasks/{task_id}:subscribe"), timeout=5)
    _assert_429_envelope(r_full)

    # Simulate a client disconnect: cancel the open stream's task.
    await _cancel(t1)
    assert len(streams) == 0, (
        "cancelling/disconnecting the open stream must deregister it via "
        "release(), freeing its capacity slot"
    )

    record = app.state.task_store.get(task_id)
    assert record is not None
    assert len(record.subscriptions) == 0, (
        "release() must also unsubscribe from the task store, not just pop "
        "the admission slot"
    )

    t2 = asyncio.create_task(client.post(f"/v1/tasks/{task_id}:subscribe"))
    try:
        assert await _still_streaming(t2), "a new stream must now be admitted after capacity was freed"
        assert len(streams) == 1
    finally:
        await _cancel(t2)
