"""GH-187: a retry in the same contextId must not inherit a failed task's
transcript. ``context_messages()`` / ``context_reusable_messages()`` only
consider COMPLETED tasks."""

from __future__ import annotations

import uuid

import pytest

from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState, TaskStatus
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import reply, tool_call

from .conftest import wait_for_state

_OWNER = Identity(kind="api_key", subject="owner", admin=False)


def _text(role: str, text: str) -> dict:
    return {"role": role, "content": [{"text": text}]}


def _task(store, ctx, state, messages, identity=_OWNER):
    record = store.create(new_task(ctx), identity)
    record.messages.extend(messages)
    record.task.status = TaskStatus(state=state)
    return record


def test_failed_task_is_skipped_for_seed():
    store = InMemoryTaskStore()
    _task(store, "c", TaskState.COMPLETED, [_text("user", "one"), _text("assistant", "A")])
    _task(store, "c", TaskState.FAILED, [_text("user", "two"), _text("assistant", "B")])
    seed = store.context_messages("c", _OWNER)
    assert [m["content"][0]["text"] for m in seed] == ["one", "A"]


@pytest.mark.parametrize(
    "state", [TaskState.FAILED, TaskState.CANCELED, TaskState.REJECTED]
)
def test_only_non_completed_prior_tasks_give_empty_seed(state):
    store = InMemoryTaskStore()
    _task(store, "c", state, [_text("user", "x"), _text("assistant", "y")])
    assert list(store.context_messages("c", _OWNER)) == []
    assert list(store.context_reusable_messages("c", _OWNER)) == []


def test_reusable_markers_skip_non_completed():
    store = InMemoryTaskStore()
    ok = _task(store, "c", TaskState.COMPLETED, [_text("user", "good")])
    bad = _task(store, "c", TaskState.FAILED, [_text("user", "bad")])
    from agent_sdk.tasks import memory

    seen: list = []
    orig = memory.extract_resolved_markers
    memory.extract_resolved_markers = lambda msgs: (seen.append(msgs), [])[1]
    try:
        store.context_reusable_messages("c", _OWNER)
    finally:
        memory.extract_resolved_markers = orig
    assert [m[0]["content"][0]["text"] for m in seen] == ["good"]
    assert ok is not bad


def user_msg(text: str, ctx: str) -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
            "contextId": ctx,
        }
    }


async def test_retry_after_failed_turn_runs_tool_again(client, fake_model):
    ctx = uuid.uuid4().hex

    fake_model.script(reply("hello"))
    r1 = await client.post("/v1/message:send", json=user_msg("hi", ctx))
    assert (await wait_for_state(client, r1.json()["id"]))["status"]["state"] == "completed"

    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}))
    r2 = await client.post("/v1/message:send", json=user_msg("kpis", ctx))
    assert (await wait_for_state(client, r2.json()["id"]))["status"]["state"] == "failed"

    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    n_calls = len(fake_model.calls)
    r3 = await client.post("/v1/message:send", json=user_msg("try again", ctx))
    done = await wait_for_state(client, r3.json()["id"])
    assert done["status"]["state"] == "completed"

    first_call = fake_model.calls[n_calls]["messages"]
    assert "toolResult" not in str(first_call)
    assert "toolUse" not in str(first_call)
    assert "hello" in str(first_call)
    assert done["artifacts"], "turn 3 must emit its own artifact"
