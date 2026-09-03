"""GH-51: A2A multi-turn task continuation via contextId.

Spec-correct approach (A2A §3): after a task completes, a client starts a new
task in the same conversation by sending a message with contextId but NO taskId.
The SDK loads prior conversation history via TaskStore.context_messages() and
prepends it to the new task's model-context messages list.

Sending taskId pointing to a terminal task is always -32004 (UnsupportedOperation)
per A2A §6 item 14 — the terminal-task guard is never bypassed.
"""

from __future__ import annotations

import uuid

import pytest

from agent_sdk.testing import reply, tool_call

from .conftest import sse_frames, wait_for_state


def send_body(
    text: str,
    task_id: str | None = None,
    context_id: str | None = None,
) -> dict:
    msg: dict = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": uuid.uuid4().hex,
    }
    if task_id:
        msg["taskId"] = task_id
    if context_id:
        msg["contextId"] = context_id
    return {"message": msg}


async def _complete_task(client, fake_model, text: str = "hello") -> dict:
    """Submit a task that uses a tool (so assistant+tool messages land in record.messages)."""
    fake_model.script(
        tool_call("echo", {"text": text}),
        reply("done"),
    )
    r = await client.post("/v1/message:send", json=send_body(text))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    return await wait_for_state(client, task_id)


# ── spec-correct path: contextId continuation ─────────────────────────────────


async def test_context_continuation_inherits_history(client, fake_model):
    """Turn 2 sent with contextId (no taskId) creates a new task that carries
    prior messages into the model's converse call."""
    fake_model.calls.clear()
    completed = await _complete_task(client, fake_model, "first turn")
    ctx = completed["contextId"]
    turn1_call_count = len(fake_model.calls)

    # Turn 2: same contextId, no taskId
    fake_model.script(reply("second reply"))
    r = await client.post("/v1/message:send", json=send_body("second turn", context_id=ctx))
    assert r.status_code == 200, r.text
    body = r.json()

    # New task in the same conversation context
    assert body["id"] != completed["id"]
    assert body["contextId"] == ctx

    # Wait for Turn 2 to complete so converse() was called
    await wait_for_state(client, body["id"])

    # The first converse call for Turn 2 must include the prior user+assistant messages
    assert len(fake_model.calls) > turn1_call_count
    turn2_messages = fake_model.calls[turn1_call_count]["messages"]
    roles = [m["role"] for m in turn2_messages]
    # prior user turn, prior assistant turn, then current user turn
    assert roles.count("user") >= 2
    assert "assistant" in roles


async def test_context_continuation_stream(client, fake_model):
    """message/stream with contextId continuation creates a new task and streams it."""
    completed = await _complete_task(client, fake_model, "first turn")
    ctx = completed["contextId"]

    fake_model.script(
        tool_call("echo", {"text": "t2"}),
        reply("streamed continuation"),
    )
    async with client.stream(
        "POST", "/v1/message:stream", json=send_body("turn 2", context_id=ctx)
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = (await r.aread()).decode()

    frames = sse_frames(body)
    # first frame is a Task snapshot for the NEW task
    assert frames[0]["id"] != completed["id"]
    assert frames[0]["contextId"] == ctx
    # stream ends with final=True
    assert frames[-1].get("final") is True


async def test_fresh_context_no_prior_history(client, fake_model):
    """Turn 1 with a brand-new contextId carries no prior messages — only the user turn."""
    fake_model.calls.clear()
    fake_model.script(reply("fresh reply"))
    new_ctx = uuid.uuid4().hex
    r = await client.post("/v1/message:send", json=send_body("hello", context_id=new_ctx))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    assert len(fake_model.calls) >= 1
    messages = fake_model.calls[-1]["messages"]
    assert len(messages) == 1
    assert messages[0]["role"] == "user"


# ── spec-correct rejection: terminal taskId ───────────────────────────────────


async def test_send_terminal_taskid_returns_unsupported(client, fake_model):
    """message/send with taskId pointing to a completed task → -32004 (UnsupportedOperation).
    A2A §6 item 14: MUST return error, MUST NOT start a new task."""
    completed = await _complete_task(client, fake_model)
    task_id = completed["id"]

    r = await client.post("/v1/message:send", json=send_body("turn 2", task_id=task_id))
    assert r.status_code in (400, 501), r.text
    assert r.json()["error"]["code"] == -32004


async def test_stream_terminal_taskid_returns_unsupported(client, fake_model):
    """message/stream with taskId pointing to a completed task → -32004
    (UnsupportedOperation), matching message/send's behavior for the same
    input (GH-144). The task exists — it is merely terminal — so -32001
    (TaskNotFound) would misrepresent the failure; no SSE stream is opened."""
    completed = await _complete_task(client, fake_model)
    task_id = completed["id"]

    r = await client.post(
        "/v1/message:stream", json=send_body("turn 2", task_id=task_id)
    )
    assert r.status_code == 501, r.text
    assert not r.headers["content-type"].startswith("text/event-stream")
    assert r.json()["error"]["code"] == -32004


async def test_interrupted_taskid_routes_to_resume(client, fake_model):
    """taskId in input-required state → routes to resume, not a new task."""
    fake_model.script(
        tool_call("publish_note", {"note": "hello"}),
        reply("published!"),
    )
    r = await client.post("/v1/message:send", json=send_body("publish hello"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, states=("input-required",))

    # Resume the SAME task — same task id in response
    r = await client.post("/v1/message:send", json=send_body("approved", task_id=task_id))
    assert r.status_code == 200, r.text
    assert r.json()["id"] == task_id


# ── identity isolation ────────────────────────────────────────────────────────


async def test_stream_terminal_taskid_foreign_identity_returns_not_found(client, fake_model):
    """message/stream with taskId pointing to ANOTHER identity's terminal task
    → -32001 TaskNotFound/404 (identity-scoped store.get() sees no such task
    for this caller), never -32004 UnsupportedOperation/501 (RT-002/GH-144).
    The terminal-state check at a2a.py:335 must stay strictly downstream of
    the identity-scoped lookup at a2a.py:332 — a foreign identity's terminal
    task must not leak "this task exists" via a differentiated error code."""
    completed = await _complete_task(client, fake_model)
    task_id = completed["id"]

    _, other_token = client.app.state.auth.api_keys.mint("other-user-rt002", admin=False)

    r = await client.post(
        "/v1/message:stream",
        json=send_body("turn 2", task_id=task_id),
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert r.status_code == 404, r.text
    assert not r.headers["content-type"].startswith("text/event-stream")
    body = r.json()
    assert body["error"]["code"] == -32001
    assert body["error"]["code"] != -32004


async def test_context_continuation_isolated_per_identity(client, fake_model):
    """Different identity cannot see prior context messages from another user."""
    completed = await _complete_task(client, fake_model, "secret data")
    ctx = completed["contextId"]

    _, other_token = client.app.state.auth.api_keys.mint("other-user", admin=False)

    fake_model.calls.clear()
    fake_model.script(reply("other user reply"))
    r = await client.post(
        "/v1/message:send",
        json=send_body("turn 2", context_id=ctx),
        headers={"Authorization": f"Bearer {other_token}"},
    )
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    # Other user gets a fresh context — no prior messages from the first user
    assert len(fake_model.calls) >= 1
    messages = fake_model.calls[-1]["messages"]
    # Only the Turn 2 user message — no inherited history from other identity
    assert len(messages) == 1
    assert messages[0]["role"] == "user"
