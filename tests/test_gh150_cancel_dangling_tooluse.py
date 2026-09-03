"""GH-150: cancelling a task mid-tool-call must not leave a dangling
``toolUse`` block in ``record.messages``.

Root cause: ``run_loop`` folds the assistant ``toolUse`` message into
``messages`` (``agent_sdk/agent/loop.py``) BEFORE running the per-tool-call
loop; the matching ``toolResult`` message is only appended after every tool
call in that turn finishes. A task cancelled while a tool call is still in
flight — whether blocked inside the tool's own execution, or parked awaiting
an interrupt's resume — therefore leaves ``record.messages`` ending on the
assistant ``toolUse`` message with no matching ``toolResult``.
``context_messages()`` then replays that broken transcript verbatim on the
next ``contextId`` continuation turn, which Converse-API-shaped backends
(Bedrock) reject outright.

Landed against GH-147's already-updated assistant-turn-fold logic in
``agent_sdk/agent/loop.py`` (w039 group:B — group:A landed GH-147 first).
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient, reply, tool_call

from .conftest import wait_for_state

pytestmark = pytest.mark.asyncio


# ── a tool that blocks until the test releases it ──────────────────────────


class _Signals:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()


signals = _Signals()

gh150_tools = ToolSet()


class SlowInput(BaseModel):
    pass


@gh150_tools.tool(tier=1)
async def slow_blocking_tool(inp: SlowInput) -> dict[str, Any]:
    """Parks forever (until released) — simulates a tool call still in
    flight when the task is cancelled."""
    signals.started.set()
    await signals.release.wait()
    return {"done": True}


@pytest.fixture
def reset_signals() -> _Signals:
    signals.started = asyncio.Event()
    signals.release = asyncio.Event()
    return signals


@pytest.fixture
def gh150_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [gh150_tools]
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


@pytest.fixture
async def gh150_client(gh150_app):
    async with gh150_app.router.lifespan_context(gh150_app):
        _, token = gh150_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gh150_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as c:
            yield c


def send_body(
    text: str, *, task_id: str | None = None, context_id: str | None = None
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": uuid.uuid4().hex,
    }
    if task_id:
        msg["taskId"] = task_id
    if context_id:
        msg["contextId"] = context_id
    return {"message": msg}


def _tool_use_ids(message: dict[str, Any]) -> set[str]:
    return {
        block["toolUse"]["toolUseId"]
        for block in message.get("content", [])
        if isinstance(block, dict) and "toolUse" in block
    }


def _tool_result_ids(message: dict[str, Any]) -> set[str]:
    return {
        block["toolResult"]["toolUseId"]
        for block in message.get("content", [])
        if isinstance(block, dict) and "toolResult" in block
    }


def assert_no_dangling_tool_use(messages: list[dict[str, Any]]) -> None:
    """Every assistant toolUse turn must be immediately followed by a
    message carrying a matching toolResult for every toolUseId — the
    Converse-API-shaped invariant contextId continuation replay depends on."""
    for i, message in enumerate(messages):
        ids = _tool_use_ids(message)
        if not ids:
            continue
        assert i + 1 < len(messages), (
            f"assistant toolUse turn at index {i} has no following message "
            f"(dangling toolUseId(s): {ids!r})"
        )
        result_ids = _tool_result_ids(messages[i + 1])
        missing = ids - result_ids
        assert not missing, (
            f"toolUseId(s) {missing!r} at index {i} have no matching "
            f"toolResult in the immediately-following message"
        )


def assert_alternates(messages: list[dict[str, Any]]) -> None:
    """GH-147 AC3 / RT-004: no two consecutive entries in ``messages`` may
    share a ``role`` — the exact shape Bedrock's Converse API rejects
    outright. Stricter than ``assert_no_dangling_tool_use``: two successive
    plain 'user' turns (no toolUse involved at all) pass that check but
    still violate alternation."""
    for prev, cur in zip(messages, messages[1:]):
        assert prev.get("role") != cur.get("role"), (
            f"two consecutive {cur.get('role')!r} messages: {prev!r} then {cur!r}"
        )


# ── AC: cancel mid-tool-call repairs record.messages ────────────────────────


async def test_cancel_mid_tool_call_repairs_dangling_tool_use(
    gh150_client, fake_model, gh150_app, reset_signals
):
    fake_model.script(tool_call("slow_blocking_tool", {}))
    r = await gh150_client.post("/v1/message:send", json=send_body("go slow"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    await asyncio.wait_for(reset_signals.started.wait(), timeout=2.0)

    r = await gh150_client.post(f"/v1/tasks/{task_id}:cancel")
    assert r.status_code == 200, r.text
    assert r.json()["status"]["state"] == "canceled"

    # RT-002: a cancel that reports "canceled" must durably commit — a
    # follow-up read has to observe the same state, and the task must no
    # longer accept a second cancel.
    r_get = await gh150_client.get(f"/v1/tasks/{task_id}")
    assert r_get.status_code == 200, r_get.text
    assert r_get.json()["status"]["state"] == "canceled"

    r_again = await gh150_client.post(f"/v1/tasks/{task_id}:cancel")
    assert (r_again.status_code, r_again.json()["error"]["code"]) == (409, -32002)

    record = gh150_app.state.task_store.get(task_id)
    assert record is not None
    messages = record.messages
    assert len(messages) >= 3

    # RT-004 (GH-147 AC3): the synthetic toolResult repair_dangling_tool_use
    # appends is itself a 'user' turn, so tasks_cancel bridges it with a
    # synthetic assistant turn right after — record.messages must never be
    # left ending on 'user'.
    tool_use_msg, result_msg, bridge_msg = messages[-3], messages[-2], messages[-1]

    assert tool_use_msg["role"] == "assistant"
    tool_use_ids = _tool_use_ids(tool_use_msg)
    assert tool_use_ids, f"expected an assistant toolUse turn: {tool_use_msg!r}"

    assert result_msg["role"] == "user"
    result_blocks = [b["toolResult"] for b in result_msg["content"] if "toolResult" in b]
    assert {b["toolUseId"] for b in result_blocks} == tool_use_ids
    for b in result_blocks:
        assert b["status"] == "error"
        assert b["content"], "synthetic toolResult must carry content"

    assert bridge_msg["role"] == "assistant"

    assert_no_dangling_tool_use(messages)
    assert_alternates(messages)


async def test_cancel_while_awaiting_interrupt_resume_also_repairs(
    client, fake_model
):
    """Same dangling-toolUse shape arises via a different path: a task
    cancelled while parked in input-required (awaiting a ToolInterrupt
    resume) never got a toolResult for that tool call either."""
    fake_model.script(tool_call("publish_note", {"note": "x"}))
    r = await client.post("/v1/message:send", json=send_body("publish"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, states=("input-required",))

    r = await client.post(f"/v1/tasks/{task_id}:cancel")
    assert r.status_code == 200, r.text
    assert r.json()["status"]["state"] == "canceled"

    # RT-002: same durable-commit contract as the mid-tool-call cancel above.
    r_get = await client.get(f"/v1/tasks/{task_id}")
    assert r_get.status_code == 200, r_get.text
    assert r_get.json()["status"]["state"] == "canceled"

    r_again = await client.post(f"/v1/tasks/{task_id}:cancel")
    assert (r_again.status_code, r_again.json()["error"]["code"]) == (409, -32002)

    record = client.app.state.task_store.get(task_id)
    assert record is not None
    assert_no_dangling_tool_use(record.messages)
    assert_alternates(record.messages)


# ── AC: contextId continuation never replays a dangling toolUse ────────────


async def test_cancel_then_context_continuation_never_replays_dangling_tool_use(
    gh150_client, fake_model, gh150_app, reset_signals
):
    fake_model.script(tool_call("slow_blocking_tool", {}))
    r = await gh150_client.post("/v1/message:send", json=send_body("go slow"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    context_id = r.json()["contextId"]

    await asyncio.wait_for(reset_signals.started.wait(), timeout=2.0)

    r = await gh150_client.post(f"/v1/tasks/{task_id}:cancel")
    assert r.status_code == 200, r.text
    assert r.json()["status"]["state"] == "canceled"

    # RT-002: durable-commit contract, checked before the context continues.
    r_get = await gh150_client.get(f"/v1/tasks/{task_id}")
    assert r_get.status_code == 200, r_get.text
    assert r_get.json()["status"]["state"] == "canceled"

    r_again = await gh150_client.post(f"/v1/tasks/{task_id}:cancel")
    assert (r_again.status_code, r_again.json()["error"]["code"]) == (409, -32002)

    fake_model.calls.clear()
    fake_model.script(reply("turn two after cancel"))
    r2 = await gh150_client.post(
        "/v1/message:send", json=send_body("turn two", context_id=context_id)
    )
    assert r2.status_code == 200, r2.text
    task2_id = r2.json()["id"]
    await wait_for_state(gh150_client, task2_id)

    assert fake_model.calls, "converse must have been called for turn 2"
    replayed = fake_model.calls[0]["messages"]
    assert_no_dangling_tool_use(replayed)
    # RT-004 (GH-147 AC3): the invariant that actually matters is full
    # alternation of what the model is sent on the continuation turn — not
    # just the absence of a dangling toolUse. Before the bridge fix, the
    # cancel repair left record.messages ending on 'user', and
    # _create_task_record's own appended 'user' turn landed right on top of
    # it: two consecutive 'user' messages, which assert_no_dangling_tool_use
    # alone would never catch (no toolUse block is involved).
    assert_alternates(replayed)

    record2 = gh150_app.state.task_store.get(task2_id)
    assert record2 is not None
    assert_no_dangling_tool_use(record2.messages)
    assert_alternates(record2.messages)
