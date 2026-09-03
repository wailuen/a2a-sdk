"""RT-001 — BackgroundTask release/abort closures must run on the event-loop
thread, not an AnyIO worker thread.

Starlette's ``BackgroundTask.__call__`` dispatches a plain ``def`` callable
via ``run_in_threadpool`` (an AnyIO worker thread) and only ``await``s an
``async def`` callable directly on the event loop. ``mcp_get``'s and
``mcp_sse``'s ``release()`` closures and ``a2a._open_stream``'s ``abort()``
mutate event-loop-owned state (``app.state.mcp_get_streams``,
``app.state.mcp_sse_queues``, ``record.subscriptions``) while the loop
concurrently iterates those very same containers (``_prune_get_streams``,
``InMemoryTaskStore.publish``). A plain-``def`` closure races that iteration
off-loop and can raise ``RuntimeError: ... mutated during iteration`` or
silently skip a live subscriber.

This module drives the same "disconnect before the stream body starts"
scenario ``tests/test_gh143_mcp_get_stream_cap.py`` already exercises
(``receive()`` reports disconnect immediately; ``send()`` suspends forever on
``http.response.start`` so Starlette's cancel scope absorbs the disconnect
and still awaits the response's ``BackgroundTask``, unlike a hard task
cancellation) and asserts the release/abort callable actually ran on
``threading.main_thread()``.
"""

from __future__ import annotations

import asyncio
import threading
from collections import OrderedDict
from typing import Any

import httpx
import pytest


async def _start_disconnect_before_body(
    app: Any, path: str, token: str, *, method: str = "GET"
) -> "asyncio.Task[Any]":
    """Drive a raw ASGI request whose ``receive()`` reports disconnect
    immediately and whose ``send()`` suspends forever on
    ``http.response.start``. Returns once that checkpoint is reached, with
    the driving task still running — the caller polls its own side effect
    then tears the task down."""

    async def receive() -> dict:
        return {"type": "http.disconnect"}

    sent: list[str] = []

    async def send(message: dict) -> None:
        sent.append(message["type"])
        if message["type"] == "http.response.start":
            await asyncio.Event().wait()

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
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
    for _ in range(50):
        if sent:
            return task
        await asyncio.sleep(0.1)
    task.cancel()
    pytest.fail(f"{method} {path} never reached send(http.response.start)")


async def _teardown(task: "asyncio.Task[Any]") -> None:
    if not task.done():
        task.cancel()
    try:
        await task
    except BaseException:
        pass


class _ThreadRecordingDict(OrderedDict):
    """Spy on the exact mutation ``release()``/``abort()`` performs, recording
    which thread called it."""

    def __init__(self) -> None:
        super().__init__()
        self.pop_threads: list[threading.Thread] = []

    def pop(self, key: Any, default: Any = None) -> Any:
        self.pop_threads.append(threading.current_thread())
        return super().pop(key, default)


async def _poll_until(predicate: Any, *, attempts: int = 50, interval: float = 0.1) -> bool:
    for _ in range(attempts):
        if predicate():
            return True
        await asyncio.sleep(interval)
    return False


# ---------------------------------------------------------------------------
# mcp_get — release() at mcp.py:866
# ---------------------------------------------------------------------------


async def test_mcp_get_release_runs_on_event_loop_thread(app) -> None:
    spy = _ThreadRecordingDict()
    app.state.mcp_get_streams = spy
    _, token = app.state.auth.api_keys.mint("rt001-thread-mcp-get")

    task = await _start_disconnect_before_body(app, "/mcp", token)
    try:
        assert await _poll_until(lambda: bool(spy.pop_threads)), (
            "release() was never invoked within the poll window"
        )
    finally:
        await _teardown(task)

    assert all(t is threading.main_thread() for t in spy.pop_threads), (
        "release() ran off the event-loop thread (Starlette dispatched a "
        f"plain `def` via run_in_threadpool): {[t.name for t in spy.pop_threads]}"
    )


# ---------------------------------------------------------------------------
# mcp_sse — release() at mcp.py:983
# ---------------------------------------------------------------------------


async def test_mcp_sse_release_runs_on_event_loop_thread(app) -> None:
    spy = _ThreadRecordingDict()
    app.state.mcp_get_streams = spy
    _, token = app.state.auth.api_keys.mint("rt001-thread-mcp-sse")

    task = await _start_disconnect_before_body(app, "/mcp/sse", token)
    try:
        assert await _poll_until(lambda: bool(spy.pop_threads)), (
            "release() was never invoked within the poll window"
        )
    finally:
        await _teardown(task)

    assert all(t is threading.main_thread() for t in spy.pop_threads), (
        "release() ran off the event-loop thread (Starlette dispatched a "
        f"plain `def` via run_in_threadpool): {[t.name for t in spy.pop_threads]}"
    )


# ---------------------------------------------------------------------------
# a2a._open_stream — abort() at a2a.py:324
# ---------------------------------------------------------------------------


async def test_a2a_abort_runs_on_event_loop_thread(app) -> None:
    _, token = app.state.auth.api_keys.mint("rt001-thread-a2a")
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
                    "messageId": "m-rt001-thread-a2a",
                    "parts": [{"kind": "text", "text": "hello"}],
                }
            },
        )
        assert r.status_code == 200, r.text
        task_id = r.json()["id"]

    store = app.state.task_store
    orig_unsubscribe = store.unsubscribe
    threads: list[threading.Thread] = []

    def spy_unsubscribe(task_id_arg: str, sub: Any) -> None:
        threads.append(threading.current_thread())
        return orig_unsubscribe(task_id_arg, sub)

    store.unsubscribe = spy_unsubscribe  # type: ignore[method-assign]

    task = await _start_disconnect_before_body(
        app, f"/v1/tasks/{task_id}:subscribe", token, method="POST"
    )
    try:
        assert await _poll_until(lambda: bool(threads)), (
            "abort() was never invoked within the poll window"
        )
    finally:
        await _teardown(task)

    assert all(t is threading.main_thread() for t in threads), (
        "abort() ran off the event-loop thread (Starlette dispatched a plain "
        f"`def` via run_in_threadpool): {[t.name for t in threads]}"
    )
