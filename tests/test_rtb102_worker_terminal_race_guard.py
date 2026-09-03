"""RT-B-102: run_task_worker's own terminal transitions — the DoneEvent
branch and the `else:` clause's terminal publish — must carry the same
already-terminal bail-out ``_run_deferred_background`` already has (its
``_fail()`` entry guard and its post-await success check), or a cancellation
whose ``asyncio.CancelledError`` never reaches ``run_task_worker`` (swallowed
by third-party tool code, or lost to an ``asyncio.wait_for`` cancel-vs-timeout
race) lets the synchronous worker keep running to a normal ``DoneEvent`` and
revert a task ``tasks_cancel`` already committed CANCELED for — flipping it
back to COMPLETED and publishing a second terminal frame onto streams
``tasks_cancel`` already closed.

Mirrors ``tests/test_rtb001_cancel_deferred_bg_task.py``'s HTTP-level AC1,
adapted for the synchronous (non-deferred) worker: the in-flight tool call
itself swallows ``CancelledError`` instead of letting it propagate, so
``tasks_cancel``'s own ``record.worker.cancel()`` does not actually stop the
worker — it keeps running the turn to completion.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.registry import ToolSet
from agent_sdk.agent.reuse import Reusable
from agent_sdk.agent.runner import StreamItem
from agent_sdk.example.agent import make_agent
from agent_sdk.models.a2a import TaskState
from agent_sdk.testing import tool_call, reply

pytestmark = pytest.mark.asyncio


class _Signals:
    def __init__(self) -> None:
        self.started = asyncio.Event()


signals = _Signals()

rtb102_tools = ToolSet()


class _EmptyInput(BaseModel):
    pass


@rtb102_tools.tool(tier=1)
async def rtb102_swallows_cancel(inp: _EmptyInput) -> dict[str, Any]:
    """Parks until cancelled, then SWALLOWS the CancelledError instead of
    letting it propagate — the exact third-party-tool-code shape the finding
    describes. ``asyncio.Task.cancel()`` therefore fails to actually stop
    this coroutine: it wakes at the cancellation, discards it, and returns a
    normal successful result as if nothing happened."""
    signals.started.set()
    try:
        await asyncio.Event().wait()  # never set — only wakes via cancel()
    except asyncio.CancelledError:
        pass
    return {"ok": True}


class _RaisesOnStr:
    """RT-001: str(...) raises, so pydantic_core.to_jsonable_python's
    ``fallback=str`` (loop.py's ``jsonable_reuse_value``) propagates the
    exception uncaught — the exact live repro from the finding."""

    def __str__(self) -> str:
        raise RuntimeError("boom")


@rtb102_tools.tool(tier=1)
async def rtb102_swallows_cancel_then_raises(inp: _EmptyInput) -> Reusable:
    """Same swallowed-cancellation shape as ``rtb102_swallows_cancel``, but
    the tool call itself succeeds and returns a ``Reusable`` whose value
    blows up JSON-safing it — raising OUTSIDE the per-tool-call try/except
    in ``loop.py`` (at ``jsonable_reuse_value``, line ~1182), so the
    exception escapes ``run_loop`` as a raw ``RuntimeError`` instead of
    becoming a ``ToolResultEvent(ok=False)``."""
    signals.started.set()
    try:
        await asyncio.Event().wait()  # never set — only wakes via cancel()
    except asyncio.CancelledError:
        pass
    return Reusable(value=_RaisesOnStr(), kind="rtb102_bad", label="x")


@pytest.fixture
def reset_signals() -> _Signals:
    signals.started = asyncio.Event()
    return signals


@pytest.fixture
def rtb102_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [rtb102_tools]
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


@pytest.fixture
async def rtb102_client(rtb102_app):
    async with rtb102_app.router.lifespan_context(rtb102_app):
        _, token = rtb102_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rtb102_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as c:
            yield c


def send_body(text: str) -> dict[str, Any]:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


def assert_alternates(messages: list[dict[str, Any]]) -> None:
    for prev, cur in zip(messages, messages[1:]):
        assert prev.get("role") != cur.get("role"), (
            f"two consecutive {cur.get('role')!r} messages: {prev!r} then {cur!r}"
        )


async def test_swallowed_cancel_never_reverts_completed_over_canceled(
    rtb102_client, fake_model, rtb102_app, reset_signals
):
    fake_model.script(tool_call("rtb102_swallows_cancel", {}), reply("turn complete"))

    r = await rtb102_client.post("/v1/message:send", json=send_body("go"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    await asyncio.wait_for(signals.started.wait(), timeout=2.0)

    record = rtb102_app.state.task_store.get(task_id)
    assert record is not None
    sub = rtb102_app.state.task_store.subscribe(task_id)

    c = await rtb102_client.post(f"/v1/tasks/{task_id}:cancel")
    assert c.status_code == 200, c.text
    assert c.json()["status"]["state"] == "canceled"

    # RT-B-102: the tool swallowed CancelledError, so record.worker was NOT
    # actually stopped by the cancel above — let it keep running to its own
    # (would-be) normal DoneEvent completion.
    assert record.worker is not None
    await asyncio.wait_for(record.worker, timeout=2.0)

    got = await rtb102_client.get(f"/v1/tasks/{task_id}")
    assert got.status_code == 200
    body = got.json()
    assert body["status"]["state"] == "canceled", (
        "a worker whose swallowed cancellation let it run to a normal "
        f"DoneEvent must never revert an already-CANCELED task; got "
        f"{body['status']['state']!r}"
    )
    assert not body.get("artifacts")

    # Exactly one terminal frame reached the subscriber (tasks_cancel's own
    # publish) followed by the normal close sentinel — never a second
    # final:true frame from the worker's own (guarded-off) DoneEvent branch.
    first = await asyncio.wait_for(sub.get(), timeout=2.0)
    assert isinstance(first, StreamItem) and first.final is True
    second = await asyncio.wait_for(sub.get(), timeout=2.0)
    assert second is None, f"expected the close sentinel, got {second!r}"
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.get(), timeout=0.2)

    # The transcript tasks_cancel repaired-and-bridged stays intact: no
    # second toolResult/user turn appended on top by the worker's own
    # DoneEvent branch, and full role alternation holds throughout.
    result_blocks = [
        block["toolResult"]
        for message in record.messages
        for block in message.get("content", [])
        if isinstance(block, dict) and "toolResult" in block
    ]
    assert len(result_blocks) == 1, (
        f"expected exactly one toolResult for the cancelled call, got {result_blocks!r}"
    )
    assert result_blocks[0]["status"] == "error", result_blocks[0]
    assert_alternates(record.messages)


async def test_swallowed_cancel_exception_never_reverts_canceled_to_failed(
    rtb102_client, fake_model, rtb102_app, reset_signals
):
    """RT-001: the ``except Exception`` handler in ``run_task_worker`` needs
    the same already-terminal bail-out as the ``DoneEvent`` branch above —
    an exception that escapes ``run_loop`` AFTER a concurrent
    ``tasks_cancel`` has already committed CANCELED must not overwrite it
    with FAILED. Live repro: ``jsonable_reuse_value`` (loop.py) raises from
    OUTSIDE the per-tool-call try/except when a ``Reusable.value``'s
    ``__str__`` raises."""
    fake_model.script(tool_call("rtb102_swallows_cancel_then_raises", {}), reply("unreachable"))

    r = await rtb102_client.post("/v1/message:send", json=send_body("go"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    await asyncio.wait_for(signals.started.wait(), timeout=2.0)

    record = rtb102_app.state.task_store.get(task_id)
    assert record is not None
    sub = rtb102_app.state.task_store.subscribe(task_id)

    c = await rtb102_client.post(f"/v1/tasks/{task_id}:cancel")
    assert c.status_code == 200, c.text
    assert c.json()["status"]["state"] == "canceled"

    # RT-B-102: the tool swallowed CancelledError, so record.worker keeps
    # running — through to the (would-be) uncaught RuntimeError from
    # jsonable_reuse_value, which the `except Exception` handler must not
    # let flip an already-CANCELED task to FAILED.
    assert record.worker is not None
    await asyncio.wait_for(record.worker, timeout=2.0)

    got = await rtb102_client.get(f"/v1/tasks/{task_id}")
    assert got.status_code == 200
    body = got.json()
    assert body["status"]["state"] == "canceled", (
        "a worker whose swallowed cancellation let it run to an uncaught "
        f"exception must never revert an already-CANCELED task; got "
        f"{body['status']['state']!r}"
    )
    assert not body.get("artifacts")

    # Exactly one terminal frame reached the subscriber (tasks_cancel's own
    # publish) followed by the normal close sentinel — never a second
    # final:true frame from the worker's own (guarded-off) except-handler.
    first = await asyncio.wait_for(sub.get(), timeout=2.0)
    assert isinstance(first, StreamItem) and first.final is True
    second = await asyncio.wait_for(sub.get(), timeout=2.0)
    assert second is None, f"expected the close sentinel, got {second!r}"
    with pytest.raises(asyncio.TimeoutError):
        await asyncio.wait_for(sub.get(), timeout=0.2)

    # The transcript tasks_cancel repaired-and-bridged stays intact: no
    # second toolResult/user turn appended on top by the worker's own
    # (guarded-off) except-handler, and full role alternation holds
    # throughout.
    result_blocks = [
        block["toolResult"]
        for message in record.messages
        for block in message.get("content", [])
        if isinstance(block, dict) and "toolResult" in block
    ]
    assert len(result_blocks) == 1, (
        f"expected exactly one toolResult for the cancelled call, got {result_blocks!r}"
    )
    assert result_blocks[0]["status"] == "error", result_blocks[0]
    assert_alternates(record.messages)
