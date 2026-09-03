"""RT-B-101: the GH-150 SI-2 acceptance criterion ("the synthetic toolResult
text is a fixed SDK-authored string and never embeds tool arguments, the tool
result payload, or an upstream exception string") landed with no regression
test pinning the exact constants or proving the leak-freedom claim.

Covers all three fixed repair/bridge strings the SDK appends to
``record.messages`` when it closes out a dangling assistant ``toolUse``
tail:

* ``routes/a2a.py``'s ``_CANCELLED_TOOL_RESULT_TEXT`` — ``tasks_cancel``.
* ``agent/runner.py``'s ``_TASK_FAILED_TOOL_RESULT_TEXT`` — the terminal
  ``except AgentError`` handler in ``run_task_worker`` (reached mid-turn via
  ``store.mark_interrupted``'s §5.2 cap, RT-A-002).
* ``agent/runner.py``'s ``_DEFERRED_SUCCESS_BRIDGE_TEXT`` — the bridge turn
  appended after a ``long_running`` (GH-87) tool's background success,
  RT-008.

Each test drives a tool with a distinctive name and a distinctive,
secret-shaped argument value through to the relevant terminal state, then
asserts the repaired/bridged text is *exactly* the module constant — not
merely non-empty — and contains neither the tool's name nor its argument
value anywhere.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.loop import LoopPolicies, ToolInterrupt
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import (
    _DEFERRED_SUCCESS_BRIDGE_TEXT,
    _TASK_FAILED_TOOL_RESULT_TEXT,
    new_task,
    run_task_worker,
)
from agent_sdk.auth.identity import Identity
from agent_sdk.example.agent import make_agent
from agent_sdk.models.a2a import TaskState
from agent_sdk.routes.a2a import _CANCELLED_TOOL_RESULT_TEXT
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, reply, tool_call

pytestmark = pytest.mark.asyncio

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])

# Distinctive enough that an accidental substring match in a fixed SDK
# string would be a real bug, not a coincidence.
_DISTINCTIVE_ARG_VALUE = "SECRET-ARG-VALUE-9f3a2b1c-zqx7"


def _tool_result_blocks(message: dict[str, Any]) -> list[dict[str, Any]]:
    return [b["toolResult"] for b in message.get("content", []) if "toolResult" in b]


def _assert_fixed_leak_free(text: str, expected: str, *, tool_name: str) -> None:
    assert text == expected, f"expected the fixed SDK constant {expected!r}, got {text!r}"
    assert tool_name not in text, f"tool name leaked into fixed SI-2 text: {text!r}"
    assert _DISTINCTIVE_ARG_VALUE not in text, f"argument value leaked into fixed SI-2 text: {text!r}"


# ── cancel path: routes/a2a.py tasks_cancel → _CANCELLED_TOOL_RESULT_TEXT ──

_CANCEL_TOOL_NAME = "gh150_si2_cancel_probe_tool"

_cancel_tools = ToolSet()


class _CancelProbeInput(BaseModel):
    secret_arg: str


class _CancelSignals:
    def __init__(self) -> None:
        self.started = asyncio.Event()
        self.release = asyncio.Event()


_cancel_signals = _CancelSignals()


@_cancel_tools.tool(tier=1)
async def gh150_si2_cancel_probe_tool(inp: _CancelProbeInput) -> dict[str, Any]:
    """Parks forever (until released) — a tool call still in flight when the
    task is cancelled."""
    _cancel_signals.started.set()
    await _cancel_signals.release.wait()
    return {"done": True, "secret_arg": inp.secret_arg}


@pytest.fixture
def reset_cancel_signals() -> _CancelSignals:
    _cancel_signals.started = asyncio.Event()
    _cancel_signals.release = asyncio.Event()
    return _cancel_signals


@pytest.fixture
def si2_cancel_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [_cancel_tools]
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


@pytest.fixture
async def si2_cancel_client(si2_cancel_app):
    async with si2_cancel_app.router.lifespan_context(si2_cancel_app):
        _, token = si2_cancel_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=si2_cancel_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as c:
            yield c


def _send_body(text: str) -> dict[str, Any]:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


async def test_cancel_synthetic_tool_result_text_is_fixed_and_leak_free(
    si2_cancel_client, fake_model, si2_cancel_app, reset_cancel_signals
):
    fake_model.script(
        tool_call(_CANCEL_TOOL_NAME, {"secret_arg": _DISTINCTIVE_ARG_VALUE})
    )
    r = await si2_cancel_client.post("/v1/message:send", json=_send_body("go slow"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    await asyncio.wait_for(reset_cancel_signals.started.wait(), timeout=2.0)

    r = await si2_cancel_client.post(f"/v1/tasks/{task_id}:cancel")
    assert r.status_code == 200, r.text
    assert r.json()["status"]["state"] == "canceled"

    record = si2_cancel_app.state.task_store.get(task_id)
    assert record is not None
    tool_use_msg, result_msg = record.messages[-3], record.messages[-2]
    assert tool_use_msg["role"] == "assistant"

    result_blocks = _tool_result_blocks(result_msg)
    assert result_blocks, "expected at least one synthetic toolResult block"
    for block in result_blocks:
        assert block["status"] == "error"
        text = block["content"][0].get("text", "")
        _assert_fixed_leak_free(text, _CANCELLED_TOOL_RESULT_TEXT, tool_name=_CANCEL_TOOL_NAME)


# ── FAILED path: run_task_worker's terminal except AgentError handler ──────
# (mark_interrupted's §5.2 max_interrupted cap, RT-A-002) → _TASK_FAILED_TOOL_RESULT_TEXT

_FAILED_TOOL_NAME = "gh150_si2_failed_probe_tool"

_failed_tools = ToolSet()


class _FailedProbeInput(BaseModel):
    secret_arg: str


@_failed_tools.tool(tier=2, title="Interrupt Probe Tool")
async def gh150_si2_failed_probe_tool(inp: _FailedProbeInput) -> dict[str, Any]:
    """Always interrupts — used to reach store.mark_interrupted mid-turn,
    whose §5.2 cap raises AgentError straight into run_task_worker's outer
    except AgentError handler."""
    raise ToolInterrupt(reason="confirmation", message=f"confirm {inp.secret_arg}?")


_FAILED_REGISTRY = ToolRegistry([_failed_tools], {})


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


async def test_agent_error_failed_tool_result_text_is_fixed_and_leak_free():
    store = InMemoryTaskStore(max_interrupted=0)
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(
        tool_call(_FAILED_TOOL_NAME, {"secret_arg": _DISTINCTIVE_ARG_VALUE}),
        reply("unreachable"),
    )

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=_FAILED_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )

    rec = store.get(task_id)
    assert rec is not None
    assert rec.task.status.state == TaskState.FAILED, (
        f"expected FAILED once the max_interrupted cap raises AgentError, "
        f"got {rec.task.status.state!r}"
    )

    tool_result_msg = rec.messages[-2]
    assert tool_result_msg["role"] == "user"
    result_blocks = _tool_result_blocks(tool_result_msg)
    assert result_blocks, "expected at least one synthetic toolResult block"
    for block in result_blocks:
        text = block["content"][0].get("text", "")
        _assert_fixed_leak_free(
            text, _TASK_FAILED_TOOL_RESULT_TEXT, tool_name=_FAILED_TOOL_NAME
        )


# ── deferred success path: _run_deferred_background → _DEFERRED_SUCCESS_BRIDGE_TEXT ─

_DEFERRED_TOOL_NAME = "gh150_si2_deferred_probe_tool"

_deferred_tools = ToolSet()


class _DeferredProbeInput(BaseModel):
    secret_arg: str


@_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def gh150_si2_deferred_probe_tool(inp: _DeferredProbeInput) -> DeferredResult:
    """Resolves quickly to a result that embeds the distinctive argument —
    only the trailing BRIDGE text (never the real toolResult content) must
    stay a fixed constant."""

    async def _job() -> str:
        await asyncio.sleep(0)
        return f"deferred-done:{inp.secret_arg}"

    return DeferredResult(handle=_job(), estimated_seconds=1.0)


@pytest.fixture
def si2_deferred_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [_deferred_tools]
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


@pytest.fixture
async def si2_deferred_client(si2_deferred_app):
    async with si2_deferred_app.router.lifespan_context(si2_deferred_app):
        _, token = si2_deferred_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=si2_deferred_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as c:
            yield c


async def test_deferred_success_bridge_text_is_fixed_and_leak_free(
    si2_deferred_client, fake_model, si2_deferred_app
):
    fake_model.script(
        tool_call(_DEFERRED_TOOL_NAME, {"secret_arg": _DISTINCTIVE_ARG_VALUE})
    )
    r = await si2_deferred_client.post("/v1/message:send", json=_send_body("go long"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]

    deadline = asyncio.get_event_loop().time() + 5.0
    while True:
        got = await si2_deferred_client.get(f"/v1/tasks/{task_id}")
        assert got.status_code == 200, got.text
        task = got.json()
        if task["status"]["state"] in ("completed", "failed"):
            break
        assert asyncio.get_event_loop().time() <= deadline, f"task never terminated: {task!r}"
        await asyncio.sleep(0.02)
    assert task["status"]["state"] == "completed", task

    record = si2_deferred_app.state.task_store.get(task_id)
    assert record is not None
    bridge_msg = record.messages[-1]
    assert bridge_msg["role"] == "assistant"
    text = bridge_msg["content"][0].get("text", "")
    _assert_fixed_leak_free(
        text, _DEFERRED_SUCCESS_BRIDGE_TEXT, tool_name=_DEFERRED_TOOL_NAME
    )
