"""RT-008: a deferred (GH-87) tool that completes SUCCESSFULLY must not bridge
its trailing toolResult turn with the fixed "(no response)" literal.

Root cause: ``_run_deferred_background``'s success path called
``repair_dangling_tool_use(..., overrides={...: (content_blocks, "success")})``,
which appends the real toolResult and then unconditionally calls
``bridge_trailing_user`` with no override — always appending
``{"role": "assistant", "content": [{"text": "(no response)"}]}``. On the
next contextId continuation the model is replayed its own prior turn as
"(no response)" immediately after a long-running tool that actually
succeeded and produced a terminal artifact.

Fix: ``bridge_trailing_user`` (agent/loop.py) and ``repair_dangling_tool_use``
(agent/runner.py) both take an optional bridge-text override; the deferred
success path passes its own fixed, SDK-authored string
(``_DEFERRED_SUCCESS_BRIDGE_TEXT``, "(tool completed in background)") instead
of falling through to the "(no response)" default. Every failure/cancel
caller (timeout, tool exception, task cancellation, mid-turn AgentError)
leaves the default untouched — those exits really did produce no response.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest

from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.loop import bridge_trailing_user
from agent_sdk.agent.registry import ToolSet
from agent_sdk.agent.runner import repair_dangling_tool_use
from agent_sdk.example.agent import make_agent
from agent_sdk.models.a2a import Task, TaskState, TaskStatus
from agent_sdk.tasks.store import TaskRecord
from agent_sdk.testing import FakeModelClient, reply, tool_call

from .conftest import wait_for_state


# ── unit: bridge_trailing_user / repair_dangling_tool_use accept an override ─


def _record(messages: list[dict[str, Any]]) -> TaskRecord:
    task = Task(id="t1", contextId="c1", status=TaskStatus(state=TaskState.COMPLETED))
    record = TaskRecord(task=task, identity=("api_key", "test"), created_at=0.0, updated_at=0.0)
    record.messages = messages
    return record


def test_bridge_trailing_user_default_text_is_no_response():
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "hi"}]}]
    bridge_trailing_user(messages)
    assert messages[-1] == {"role": "assistant", "content": [{"text": "(no response)"}]}


def test_bridge_trailing_user_accepts_custom_text():
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "hi"}]}]
    bridge_trailing_user(messages, "(tool completed in background)")
    assert messages[-1] == {
        "role": "assistant",
        "content": [{"text": "(tool completed in background)"}],
    }


def test_repair_dangling_tool_use_default_bridge_text_unchanged():
    record = _record(
        [
            {"role": "user", "content": [{"text": "go"}]},
            {
                "role": "assistant",
                "content": [
                    {"toolUse": {"toolUseId": "tu1", "name": "echo", "input": {}}}
                ],
            },
        ]
    )
    repair_dangling_tool_use(
        record,
        default_content=[{"text": "cancelled"}],
        overrides={"tu1": ([{"text": "cancelled"}], "error")},
    )
    assert record.messages[-1]["content"] == [{"text": "(no response)"}]


def test_repair_dangling_tool_use_bridge_text_override():
    record = _record(
        [
            {"role": "user", "content": [{"text": "go"}]},
            {
                "role": "assistant",
                "content": [
                    {"toolUse": {"toolUseId": "tu1", "name": "echo", "input": {}}}
                ],
            },
        ]
    )
    repair_dangling_tool_use(
        record,
        default_content=[{"text": "unused"}],
        overrides={"tu1": ([{"text": "done"}], "success")},
        bridge_text="(tool completed in background)",
    )
    assert record.messages[-1] == {
        "role": "assistant",
        "content": [{"text": "(tool completed in background)"}],
    }


# ── route level: the deferred (GH-87) success path uses the new text ───────

rt008_tools = ToolSet()


async def _fast_job() -> str:
    await asyncio.sleep(0)
    return "deferred-done"


async def _never_job() -> str:
    await asyncio.sleep(9999)
    return "unreachable"


@rt008_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def rt008_long_running_tool() -> DeferredResult:
    """Resolves quickly to a plain string result."""
    return DeferredResult(handle=_fast_job(), estimated_seconds=1.0)


@rt008_tools.tool(tier=1, long_running=True, tool_timeout_override=0.05)
async def rt008_slow_tool() -> DeferredResult:
    """Handle never resolves within its short override timeout."""
    return DeferredResult(handle=_never_job())


@pytest.fixture
def rt008_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [rt008_tools]
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


@pytest.fixture
async def rt008_client(rt008_app):
    async with rt008_app.router.lifespan_context(rt008_app):
        _, token = rt008_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rt008_app),
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


@pytest.mark.asyncio
async def test_deferred_success_bridges_with_completed_not_no_response(
    rt008_client, fake_model, rt008_app
):
    fake_model.script(tool_call("rt008_long_running_tool", {}))
    r = await rt008_client.post("/v1/message:send", json=send_body("go long"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    task = await wait_for_state(rt008_client, task_id)
    assert task["status"]["state"] == "completed", task

    record = rt008_app.state.task_store.get(task_id)
    assert record is not None
    bridge_msg = record.messages[-1]

    assert bridge_msg["role"] == "assistant"
    assert bridge_msg["content"] == [{"text": "(tool completed in background)"}]
    assert bridge_msg["content"] != [{"text": "(no response)"}]


@pytest.mark.asyncio
async def test_deferred_success_replayed_transcript_never_says_no_response(
    rt008_client, fake_model, rt008_app
):
    """The misleading turn is what gets replayed to the model on the next
    contextId continuation — assert on the payload actually sent upstream,
    not just the stored record."""
    fake_model.script(tool_call("rt008_long_running_tool", {}))
    r = await rt008_client.post("/v1/message:send", json=send_body("go long"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    context_id = r.json()["contextId"]
    await wait_for_state(rt008_client, task_id)

    fake_model.calls.clear()
    fake_model.script(reply("turn two after deferred completion"))
    r2 = await rt008_client.post(
        "/v1/message:send", json=send_body("turn two", context_id=context_id)
    )
    assert r2.status_code == 200, r2.text
    await wait_for_state(rt008_client, r2.json()["id"])

    assert fake_model.calls, "converse must have been called for turn 2"
    replayed = fake_model.calls[0]["messages"]
    assert not any(
        m.get("role") == "assistant" and m.get("content") == [{"text": "(no response)"}]
        for m in replayed
    ), f"deferred success turn replayed as '(no response)': {replayed!r}"


@pytest.mark.asyncio
async def test_deferred_timeout_still_bridges_with_no_response(
    rt008_client, fake_model, rt008_app
):
    """RT-008 scope: only the SUCCESS path changes. A genuinely-failed
    deferred call (timeout) really did produce no response, so it must keep
    the original "(no response)" bridge text."""
    fake_model.script(tool_call("rt008_slow_tool", {}))
    r = await rt008_client.post("/v1/message:send", json=send_body("go slow"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    task = await wait_for_state(rt008_client, task_id)
    assert task["status"]["state"] == "failed", task

    record = rt008_app.state.task_store.get(task_id)
    assert record is not None
    assert record.messages[-1]["content"] == [{"text": "(no response)"}]
