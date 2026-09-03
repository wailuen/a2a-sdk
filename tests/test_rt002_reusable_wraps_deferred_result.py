"""RT-002 (regression against LRN-120/LRN-122): a tool returning
``Reusable(value=DeferredResult(...))`` must be recognised as a deferred
handoff, not folded into the transcript as a SUCCESS result carrying the raw
``DeferredResult`` (and its unawaited coroutine handle).

Before the fix, ``agent/loop.py``'s ``isinstance(result, DeferredResult)``
checks (the coroutine branch and the async-generator branch) ran BEFORE the
``Reusable`` unwrap that happens later in ``run_loop`` — so a tool wrapping
its deferred handoff in ``Reusable`` (to mark the EVENTUAL resolved value
reusable via ``$ref:<kind>``) slipped past both checks: no ``DeferredEvent``
was emitted, the ``Reusable(value=DeferredResult(...))`` was cached and
folded into ``messages`` as a successful ``toolResult`` whose content was
``str(DeferredResult(...))`` — literally ``"DeferredResult(handle=<coroutine
object ... at 0x...>, estimated_seconds=None)"`` — and the deferred job's
side effect never ran (the handle was never awaited).

``agent/registry.py``'s ``ToolEntry.invoke_any`` had the mirror hole:
``resolve_deferred_result`` was called BEFORE the post-call ``Reusable``
unwrap, so it never even entered the nested-``DeferredResult`` resolution
loop (``isinstance(result, DeferredResult)`` was False — ``result`` was a
``Reusable``) — the raw unresolved ``DeferredResult`` was unwrapped to
``.value`` and returned verbatim, over MCP ``tools/call`` and the admin
try-tool endpoint.

Tests:
1. test_run_loop_emits_deferred_event_for_reusable_wrapped_coroutine_result
2. test_run_loop_emits_deferred_event_for_reusable_wrapped_generator_result
3. test_runner_resolves_reusable_wrapped_deferred_result_and_folds_marker
4. test_invoke_any_resolves_reusable_wrapped_deferred_result
5. test_mcp_tools_call_reusable_wrapped_deferred_result_resolves
6. test_admin_try_tool_reusable_wrapped_deferred_result_resolves
"""

from __future__ import annotations

import asyncio
import gc
from typing import Any, AsyncGenerator

import httpx
import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredEvent, DeferredResult
from agent_sdk.agent.events import DoneEvent, ToolResultEvent
from agent_sdk.agent.loop import LoopPolicies, run_loop
from agent_sdk.agent.registry import ToolDecl, ToolEntry, ToolRegistry, ToolSet
from agent_sdk.agent.reuse import Reusable, scan_resolved
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.example.agent import make_agent
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, tool_call

pytestmark = pytest.mark.asyncio

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])

reuse_deferred_tools = ToolSet()
_coro_side_effect = {"ran": False}
_gen_side_effect = {"ran": False}


async def _coro_job() -> str:
    await asyncio.sleep(0)
    _coro_side_effect["ran"] = True
    return "ENT_777"


@reuse_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def reusable_deferred_coro_tool() -> Any:
    """Coroutine tool that hands off a deferred job, marking the eventual
    resolved value reusable via $ref:entity_id."""
    return Reusable(value=DeferredResult(handle=_coro_job()), kind="entity_id", label="Acme Corp")


async def _gen_job() -> str:
    await asyncio.sleep(0)
    _gen_side_effect["ran"] = True
    return "ENT_888"


@reuse_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def reusable_deferred_gen_tool() -> AsyncGenerator[Any, None]:
    """Async-generator tool whose terminal yield is a Reusable wrapping a
    DeferredResult."""
    yield Reusable(value=DeferredResult(handle=_gen_job()), kind="entity_id", label="Beta Co")


REUSE_DEFERRED_REGISTRY = ToolRegistry([reuse_deferred_tools], {})


async def test_run_loop_emits_deferred_event_for_reusable_wrapped_coroutine_result() -> None:
    model = FakeModelClient().script(tool_call("reusable_deferred_coro_tool", {}))

    events = []
    async for event in run_loop(
        model=model,
        registry=REUSE_DEFERRED_REGISTRY,
        adapters={},
        system="test system prompt",
        messages=[{"role": "user", "content": [{"text": "go"}]}],
        skills=None,
        policies=LoopPolicies(),
        wait_resume=None,
    ):
        events.append(event)

    deferred_events = [e for e in events if isinstance(e, DeferredEvent)]
    assert len(deferred_events) == 1, (
        f"expected exactly one DeferredEvent for a Reusable-wrapped "
        f"DeferredResult, got {[type(e).__name__ for e in events]}"
    )
    ev = deferred_events[0]
    assert isinstance(ev.deferred, DeferredResult)
    assert ev.reuse_kind == "entity_id", (
        f"the ORIGINAL Reusable's kind must survive onto DeferredEvent so "
        f"the runner can fold the __resolved__ marker once the handle "
        f"resolves; got reuse_kind={ev.reuse_kind!r}"
    )
    assert ev.reuse_label == "Acme Corp"

    # Await here only so the test itself doesn't leak an unawaited-coroutine
    # warning; the runner's background awaiter owns this in production.
    resolved = await ev.deferred.handle
    assert resolved == "ENT_777"

    for event in events:
        if isinstance(event, ToolResultEvent):
            assert not isinstance(event.result, (DeferredResult, Reusable)), (
                f"a Reusable-wrapped DeferredResult leaked onto ToolResultEvent "
                f"instead of being handed off via DeferredEvent: {event.result!r}"
            )
    assert not any(isinstance(e, DoneEvent) for e in events), (
        "run_loop must not emit DoneEvent itself when handing off a "
        "Reusable-wrapped DeferredResult; the runner owns completion"
    )


async def test_run_loop_emits_deferred_event_for_reusable_wrapped_generator_result() -> None:
    model = FakeModelClient().script(tool_call("reusable_deferred_gen_tool", {}))

    events = []
    async for event in run_loop(
        model=model,
        registry=REUSE_DEFERRED_REGISTRY,
        adapters={},
        system="test system prompt",
        messages=[{"role": "user", "content": [{"text": "go"}]}],
        skills=None,
        policies=LoopPolicies(),
        wait_resume=None,
    ):
        events.append(event)

    deferred_events = [e for e in events if isinstance(e, DeferredEvent)]
    assert len(deferred_events) == 1, (
        f"expected exactly one DeferredEvent for a generator tool's "
        f"Reusable-wrapped terminal DeferredResult, got "
        f"{[type(e).__name__ for e in events]}"
    )
    ev = deferred_events[0]
    assert ev.reuse_kind == "entity_id"
    assert ev.reuse_label == "Beta Co"

    resolved = await ev.deferred.handle
    assert resolved == "ENT_888"

    for event in events:
        if isinstance(event, ToolResultEvent):
            assert not isinstance(event.result, (DeferredResult, Reusable))


def _make_store() -> InMemoryTaskStore:
    return InMemoryTaskStore()


def _make_record(store: InMemoryTaskStore) -> Any:
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    return record


async def _wait_for_state(
    store: InMemoryTaskStore,
    task_id: str,
    states: tuple[str, ...] = ("completed", "failed"),
    timeout: float = 5.0,
) -> str:
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        record = store.get(task_id)
        assert record is not None, "task record evicted during wait"
        state = record.task.status.state
        if state in states:
            return state
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(
                f"task stuck in state {state!r} after {timeout}s; expected one of {states}"
            )
        await asyncio.sleep(0.02)


async def test_runner_resolves_reusable_wrapped_deferred_result_and_folds_marker() -> None:
    _coro_side_effect["ran"] = False
    store = _make_store()
    record = _make_record(store)
    task_id = record.task.id

    model = FakeModelClient().script(tool_call("reusable_deferred_coro_tool", {}))

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=REUSE_DEFERRED_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )

    final_state = await asyncio.wait_for(_wait_for_state(store, task_id), timeout=5.0)
    assert final_state == TaskState.COMPLETED, (
        f"expected COMPLETED once the deferred handle resolves, got {final_state!r}"
    )
    assert _coro_side_effect["ran"] is True, (
        "the deferred handle's side effect never ran — the handle was leaked "
        "unawaited behind the Reusable wrapper"
    )

    rec = store.get(task_id)
    assert rec is not None

    transcript_repr = repr(rec.messages)
    assert "DeferredResult(" not in transcript_repr, (
        f"raw DeferredResult repr leaked into the transcript: {transcript_repr}"
    )
    assert "coroutine object" not in transcript_repr, (
        f"unawaited coroutine repr leaked into the transcript: {transcript_repr}"
    )
    assert "Reusable(" not in transcript_repr

    tool_result_msgs = [
        block["toolResult"]
        for msg in rec.messages
        if msg.get("role") == "user"
        for block in msg.get("content") or []
        if isinstance(block, dict) and "toolResult" in block
    ]
    assert len(tool_result_msgs) == 1, f"expected exactly one toolResult message, got {rec.messages}"
    result_block = tool_result_msgs[0]
    assert result_block["status"] == "success"
    content = result_block["content"]
    assert content[0] == {"text": "ENT_777"}, (
        f"expected the deferred job's resolved value as plain text, got {content[0]!r}"
    )

    marker_blocks = [
        b for b in content if isinstance(b.get("json"), dict) and "__resolved__" in b["json"]
    ]
    assert len(marker_blocks) == 1, f"expected exactly one __resolved__ marker, got {content}"
    marker = marker_blocks[0]["json"]["__resolved__"]
    assert marker == {"kind": "entity_id", "label": "Acme Corp", "value": "ENT_777"}

    index = scan_resolved(rec.messages)
    assert index == {"entity_id": [("Acme Corp", "ENT_777")]}

    assert rec.task.artifacts, "expected a terminal artifact"
    artifact_wire = rec.task.artifacts[-1].wire()
    assert "DeferredResult(" not in repr(artifact_wire)
    assert "coroutine object" not in repr(artifact_wire)


async def test_invoke_any_resolves_reusable_wrapped_deferred_result() -> None:
    async def _job() -> str:
        await asyncio.sleep(0)
        return "ENT_9001"

    async def _fn() -> Any:
        return Reusable(value=DeferredResult(handle=_job()), kind="entity_id", label="Other Co")

    decl = ToolDecl(
        fn=_fn,
        name="rt002_reusable_deferred_unit_tool",
        description="reusable-wrapped deferred tool",
        tier=1,
        emits=None,
        sample=None,
        input_model=None,
        adapter_params={},
        long_running=True,
    )
    entry = ToolEntry(decl=decl)
    result = await entry.invoke_any({}, {})

    assert not isinstance(result, Reusable), (
        f"invoke_any must unwrap the outer Reusable, not return the wrapper: {result!r}"
    )
    assert not isinstance(result, DeferredResult), (
        f"invoke_any must resolve the inner DeferredResult, not return it "
        f"unawaited: {result!r}"
    )
    assert result == "ENT_9001"


@pytest.fixture
def reuse_deferred_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [reuse_deferred_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def reuse_deferred_client(reuse_deferred_app):
    async with reuse_deferred_app.router.lifespan_context(reuse_deferred_app):
        _, token = reuse_deferred_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=reuse_deferred_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as c:
            yield c


async def _mcp_init(client: httpx.AsyncClient) -> dict[str, str]:
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    assert r.status_code == 200, r.text
    session = r.headers.get("mcp-session-id")
    headers: dict[str, str] = {"MCP-Protocol-Version": "2025-06-18"}
    if session:
        headers["Mcp-Session-Id"] = session
    return headers


async def test_mcp_tools_call_reusable_wrapped_deferred_result_resolves(
    reuse_deferred_client,
) -> None:
    headers = await _mcp_init(reuse_deferred_client)
    r = await reuse_deferred_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "reusable_deferred_coro_tool", "arguments": {}},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "result" in body, f"expected a JSON-RPC result, got {body}"
    result = body["result"]

    assert result.get("isError") is False, (
        f"a Reusable-wrapped DeferredResult must resolve successfully over "
        f"MCP tools/call, not leak an internal-error/coercion failure: {result}"
    )
    text = result["content"][0]["text"]
    assert text == "ENT_777", f"expected the resolved value on the wire, got {text!r}"
    assert "DeferredResult(" not in text
    assert "coroutine object" not in text


async def test_admin_try_tool_reusable_wrapped_deferred_result_resolves(
    reuse_deferred_client,
) -> None:
    r = await reuse_deferred_client.post(
        "/admin/api/tools/reusable_deferred_coro_tool/try", json={}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True, body
    assert body["result"] == "ENT_777", (
        f"expected the resolved value, not the Reusable/DeferredResult "
        f"wrapper's internals; got {body['result']!r}"
    )
