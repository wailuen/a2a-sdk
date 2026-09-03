"""RT-002: a ``long_running`` tool returning ``DeferredResult`` must not leave
a dangling ``toolUse`` block in ``record.messages`` on the COMPLETED path.

Root cause: ``run_loop`` folds the assistant ``toolUse`` message into
``record.messages`` (``agent/loop.py``) BEFORE invoking the tool; on a
``DeferredResult`` it yields ``DeferredEvent`` and returns immediately —
never appending the matching ``toolResult``. ``runner.py``'s
``_run_deferred_background`` then drives the task to COMPLETED (or FAILED)
without ever touching ``record.messages``, so the assistant ``toolUse``
message is left dangling. ``context_messages()`` (§3 contextId continuation)
replays that broken transcript verbatim on the next turn, which
Converse-API-shaped backends (Bedrock) reject outright.

Mirrors GH-150's cancel-path regression test (``test_gh150_cancel_dangling_tooluse.py``);
the fix reuses GH-150's shared repair helper (now ``agent_sdk.agent.runner.repair_dangling_tool_use``)
rather than a fourth inline copy.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest

from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient, reply, tool_call

from .conftest import wait_for_state

pytestmark = pytest.mark.asyncio


# ── deferred tool fixtures ──────────────────────────────────────────────────

rt002_tools = ToolSet()


async def _fast_job() -> str:
    await asyncio.sleep(0)
    return "deferred-done"


async def _never_job() -> str:
    await asyncio.sleep(9999)
    return "unreachable"


@rt002_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def rt002_long_running_tool() -> DeferredResult:
    """Resolves quickly to a plain string result."""
    return DeferredResult(handle=_fast_job(), estimated_seconds=1.0)


@rt002_tools.tool(tier=1, long_running=True, tool_timeout_override=0.05)
async def rt002_slow_tool() -> DeferredResult:
    """Handle never resolves within its short override timeout."""
    return DeferredResult(handle=_never_job())


@pytest.fixture
def rt002_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [rt002_tools]
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


@pytest.fixture
async def rt002_client(rt002_app):
    async with rt002_app.router.lifespan_context(rt002_app):
        _, token = rt002_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rt002_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as c:
            yield c


def send_body(text: str, *, context_id: str | None = None) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": uuid.uuid4().hex,
    }
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


# ── AC: a completed deferred task repairs the dangling toolUse ─────────────


async def test_deferred_success_repairs_dangling_tool_use(rt002_client, fake_model, rt002_app):
    fake_model.script(tool_call("rt002_long_running_tool", {}))
    r = await rt002_client.post("/v1/message:send", json=send_body("go long"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    task = await wait_for_state(rt002_client, task_id)
    assert task["status"]["state"] == "completed", task

    record = rt002_app.state.task_store.get(task_id)
    assert record is not None
    messages = record.messages

    # RT-004 (GH-147 AC3): the toolResult repair is itself a 'user' turn, so
    # the background awaiter bridges it with a synthetic assistant turn right
    # after — record.messages must never be left ending on 'user'.
    tool_use_msg, result_msg, bridge_msg = messages[-3], messages[-2], messages[-1]

    assert tool_use_msg["role"] == "assistant"
    tool_use_ids = _tool_use_ids(tool_use_msg)
    assert tool_use_ids, f"expected an assistant toolUse turn: {tool_use_msg!r}"

    assert result_msg["role"] == "user"
    result_blocks = [b["toolResult"] for b in result_msg["content"] if "toolResult" in b]
    assert {b["toolUseId"] for b in result_blocks} == tool_use_ids
    for b in result_blocks:
        assert b["status"] == "success"
        assert b["content"], "synthetic toolResult must carry content"

    assert bridge_msg["role"] == "assistant"

    assert_no_dangling_tool_use(messages)
    assert_alternates(messages)


async def test_deferred_timeout_repairs_dangling_tool_use(rt002_client, fake_model, rt002_app):
    fake_model.script(tool_call("rt002_slow_tool", {}))
    r = await rt002_client.post("/v1/message:send", json=send_body("go slow"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    task = await wait_for_state(rt002_client, task_id)
    assert task["status"]["state"] == "failed", task

    record = rt002_app.state.task_store.get(task_id)
    assert record is not None
    messages = record.messages

    tool_use_msg, result_msg, bridge_msg = messages[-3], messages[-2], messages[-1]

    assert tool_use_msg["role"] == "assistant"
    tool_use_ids = _tool_use_ids(tool_use_msg)
    assert tool_use_ids

    assert result_msg["role"] == "user"
    result_blocks = [b["toolResult"] for b in result_msg["content"] if "toolResult" in b]
    assert {b["toolUseId"] for b in result_blocks} == tool_use_ids
    for b in result_blocks:
        assert b["status"] == "error"
        assert b["content"], "synthetic toolResult must carry content"

    assert bridge_msg["role"] == "assistant"

    assert_no_dangling_tool_use(messages)
    assert_alternates(messages)


async def test_deferred_success_then_context_continuation_never_replays_dangling_tool_use(
    rt002_client, fake_model, rt002_app
):
    fake_model.script(tool_call("rt002_long_running_tool", {}))
    r = await rt002_client.post("/v1/message:send", json=send_body("go long"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    context_id = r.json()["contextId"]

    task = await wait_for_state(rt002_client, task_id)
    assert task["status"]["state"] == "completed", task

    fake_model.calls.clear()
    fake_model.script(reply("turn two after deferred completion"))
    r2 = await rt002_client.post(
        "/v1/message:send", json=send_body("turn two", context_id=context_id)
    )
    assert r2.status_code == 200, r2.text
    task2_id = r2.json()["id"]
    await wait_for_state(rt002_client, task2_id)

    assert fake_model.calls, "converse must have been called for turn 2"
    replayed = fake_model.calls[0]["messages"]
    assert_no_dangling_tool_use(replayed)
    # RT-004 (GH-147 AC3): full alternation of what the model is actually
    # sent, not just absence of a dangling toolUse — before the bridge fix,
    # the completed-deferred repair left record.messages ending on 'user',
    # colliding with _create_task_record's own appended 'user' continuation
    # turn (two consecutive 'user' messages, invisible to a toolUse-only check).
    assert_alternates(replayed)

    record2 = rt002_app.state.task_store.get(task2_id)
    assert record2 is not None
    assert_no_dangling_tool_use(record2.messages)
    assert_alternates(record2.messages)
