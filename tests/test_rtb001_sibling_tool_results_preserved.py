"""RT-B-001: a mid-turn exit must not discard the results of the tool calls
in that turn that already COMPLETED.

Root cause: ``run_loop`` folds a turn's assistant ``toolUse`` message into
``record.messages`` BEFORE running that turn's per-tool-call loop, and appends
the matching ``user``/``toolResult`` message only after EVERY call in the turn
has finished. The per-turn ``result_blocks`` list was a ``run_loop`` local, so
any mid-turn exit destroyed it:

  * a ``DeferredEvent`` handoff (GH-87) ``return``s from inside the per-call
    loop — reachable with siblings, because ``run_loop`` iterates every tool
    call in the response and only hands off when it reaches the deferred one;
  * a cancellation (GH-150) or a raise that unwinds the generator frame
    (RT-A-002) destroys the frame outright.

``repair_dangling_tool_use`` then had no information about the completed
siblings and synthesised its blanket ``default_content`` error result for
every dangling ``toolUseId`` — so the next contextId continuation told the
model that a tool which actually SUCCEEDED, and whose real result had already
reached the client as a ``ToolResultEvent``, returned nothing.

Fix: the blocks live on ``TaskRecord.pending_tool_results`` (passed into
``run_loop`` as ``pending_results``), so every repair site can fold the real
result of a completed sibling.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest

from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.model_client import ModelResponse, ModelToolCall
from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent

from .conftest import wait_for_state

pytestmark = pytest.mark.asyncio


FAST_RESULT = "fast-sibling-real-result"
DEFERRED_RESULT = "deferred-real-result"

rtb001_tools = ToolSet()


@rtb001_tools.tool(tier=1, name="rtb001_fast")
async def rtb001_fast() -> str:
    """Completes immediately, in the same assistant turn as the deferred call."""
    return FAST_RESULT


async def _fast_job() -> str:
    await asyncio.sleep(0)
    return DEFERRED_RESULT


@rtb001_tools.tool(tier=1, name="rtb001_deferred", long_running=True, tool_timeout_override=10.0)
async def rtb001_deferred() -> DeferredResult:
    """Hands off to the runner's background awaiter."""
    return DeferredResult(handle=_fast_job(), estimated_seconds=1.0)


async def _blocking_job() -> str:
    await asyncio.sleep(9999)
    return "unreachable"


@rtb001_tools.tool(tier=1, name="rtb001_blocking")
async def rtb001_blocking() -> str:
    """Never returns — used to hold the turn open so it can be cancelled."""
    return await _blocking_job()


def two_call_turn(second_tool: str) -> ModelResponse:
    """One assistant turn calling ``rtb001_fast`` and then *second_tool*."""
    return ModelResponse(
        text_segments=[],
        tool_calls=[
            ModelToolCall(tool_call_id="tc_fast", name="rtb001_fast", arguments={}),
            ModelToolCall(tool_call_id="tc_second", name=second_tool, arguments={}),
        ],
        stop_reason="tool_use",
        input_tokens=10,
        output_tokens=10,
    )


@pytest.fixture
def rtb001_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [rtb001_tools]
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


@pytest.fixture
async def rtb001_client(rtb001_app):
    async with rtb001_app.router.lifespan_context(rtb001_app):
        _, token = rtb001_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rtb001_app),
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


def result_block(messages: list[dict[str, Any]], tool_use_id: str) -> dict[str, Any]:
    """The single ``toolResult`` block for *tool_use_id* across all messages."""
    found = [
        block["toolResult"]
        for message in messages
        for block in message.get("content", [])
        if isinstance(block, dict)
        and "toolResult" in block
        and block["toolResult"]["toolUseId"] == tool_use_id
    ]
    assert len(found) == 1, f"expected exactly one toolResult for {tool_use_id!r}: {found!r}"
    return found[0]


def block_text(block: dict[str, Any]) -> str:
    return "".join(
        str(c.get("text", "")) for c in block.get("content", []) if isinstance(c, dict)
    )


# ── AC: the deferred handoff keeps its sibling's real result ────────────────


async def test_deferred_handoff_preserves_completed_sibling_result(
    rtb001_client, fake_model, rtb001_app
):
    """A turn calling a normal tool AND a deferred tool must record the normal
    tool's REAL result — not the 'tool call result unavailable' default."""
    fake_model.script(two_call_turn("rtb001_deferred"))

    r = await rtb001_client.post("/v1/message:send", json=send_body("go"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    task = await wait_for_state(rtb001_client, task_id)
    assert task["status"]["state"] == "completed", task

    record = rtb001_app.state.task_store.get(task_id)
    assert record is not None
    messages = record.messages

    fast = result_block(messages, "tc_fast")
    assert fast["status"] == "success", (
        "the sibling tool ran and returned a real result; recording it as an "
        f"error tells the model a successful call failed: {fast!r}"
    )
    assert FAST_RESULT in block_text(fast), fast
    assert "tool call result unavailable" not in block_text(fast)

    deferred = result_block(messages, "tc_second")
    assert deferred["status"] == "success", deferred
    assert DEFERRED_RESULT in block_text(deferred), deferred


# ── AC: cancellation keeps the completed sibling's real result ──────────────


async def test_cancel_preserves_completed_sibling_result(
    rtb001_client, fake_model, rtb001_app
):
    """Cancelling mid-turn must not relabel a sibling that already succeeded."""
    fake_model.script(two_call_turn("rtb001_blocking"))

    r = await rtb001_client.post("/v1/message:send", json=send_body("go"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    # Wait until the blocking call is actually in flight (the fast sibling has
    # completed and its block is pending) before cancelling.
    record = rtb001_app.state.task_store.get(task_id)
    assert record is not None
    for _ in range(200):
        if any(
            b.get("toolResult", {}).get("toolUseId") == "tc_fast"
            for b in record.pending_tool_results
        ):
            break
        await asyncio.sleep(0.01)
    else:  # pragma: no cover - timing guard
        pytest.fail("fast sibling never completed; test cannot exercise the cancel path")

    c = await rtb001_client.post(f"/v1/tasks/{task_id}:cancel", json={"id": task_id})
    assert c.status_code == 200, c.text

    messages = record.messages
    fast = result_block(messages, "tc_fast")
    assert fast["status"] == "success", fast
    assert FAST_RESULT in block_text(fast), fast

    blocked = result_block(messages, "tc_second")
    assert blocked["status"] == "error", blocked


# ── AC: a normally-committed turn leaves nothing pending ────────────────────


async def test_completed_turn_leaves_no_stale_pending_results(
    rtb001_client, fake_model, rtb001_app
):
    """``pending_results`` must be cleared once a turn commits to ``messages``,
    or a later repair would replay a previous turn's already-folded results."""
    from agent_sdk.testing import reply, tool_call

    fake_model.script(tool_call("rtb001_fast", {}), reply("done"))

    r = await rtb001_client.post("/v1/message:send", json=send_body("go"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    task = await wait_for_state(rtb001_client, task_id)
    assert task["status"]["state"] == "completed", task

    record = rtb001_app.state.task_store.get(task_id)
    assert record is not None
    assert record.pending_tool_results == [], record.pending_tool_results

    # The committed turn still carries the real result exactly once.
    fast_blocks = [
        block["toolResult"]
        for message in record.messages
        for block in message.get("content", [])
        if isinstance(block, dict) and "toolResult" in block
    ]
    assert len(fast_blocks) == 1, fast_blocks
    assert FAST_RESULT in block_text(fast_blocks[0])
