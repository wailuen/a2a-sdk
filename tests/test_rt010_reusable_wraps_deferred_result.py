"""RT-010: the REVERSE nesting order of GH-148/RT-001 — a tool returns
``Reusable(value=DeferredResult(...))`` rather than a ``DeferredResult`` that
later resolves to a ``Reusable``.

Finding: ``agent/loop.py`` checked ``isinstance(result, DeferredResult)``
immediately after invoking the tool (both the coroutine branch and the
async-generator branch), BEFORE the ``Reusable`` unwrap that happens later in
the same function. A ``Reusable``-wrapped ``DeferredResult`` was therefore
never recognised as deferred: it fell through to the ``Reusable`` unwrap,
which produced a raw, unawaited ``DeferredResult`` as ``result`` — folded into
``fold_result_content`` (stringified into ``messages``) and shipped on
``ToolResultEvent`` under ``ok: True``. ``agent/registry.py``'s
``ToolEntry.invoke_any`` had the mirror gap: it only unwraps ``Reusable``
AFTER ``resolve_deferred_result``, whose own loop only recognises a bare
``DeferredResult`` — so the identical wrapped shape leaked a ``DeferredResult``
repr onto the MCP wire under ``isError: false``.

Only the reverse order (a ``DeferredResult`` resolving to a ``Reusable``) was
previously covered — see ``test_rt001_deferred_reusable_unwrap.py`` (runner)
and ``test_rt002_invoke_any_reusable_unwrap.py`` (registry).

Fix: unwrap a ``Reusable`` wrapping a ``DeferredResult`` BEFORE the deferred
check, on every dispatch surface — ``agent/loop.py`` (both the coroutine and
async-generator branches) and ``agent/registry.py``'s ``resolve_deferred_result``
(so ``invoke_any`` and ``runner._run_deferred_background`` both get it, since
both route through that one helper).

On the loop.py/runner.py surface, the pre-resolution wrapper's ``kind``/
``label`` are captured and threaded onto ``DeferredEvent`` (new
``reuse_kind``/``reuse_label`` fields, ``agent/deferred.py``) — run_loop
exits at the deferred handoff before it would otherwise reach its own
``Reusable`` unwrap, so the ONLY place left to capture them is here, before
the check that triggers the handoff. Once the runner's background awaiter
resolves the handle, it folds the ORIGINAL label against the NOW-known value
into the same ``__resolved__`` marker mechanism GH-148 already uses for the
opposite order — so this nesting order is fully supported, not merely
tolerated, and a value citable via ``$ref:<kind>`` from a plain
``Reusable``-then-resolve stays exactly as citable when the wrapping and the
deferral are the other way around.

On the registry.py surface (``invoke_any`` — MCP ``tools/call``, admin
try-tool, the commitments executor), there is no ``messages`` transcript to
fold a marker into for ANY ``Reusable`` shape (by design — see
``ToolEntry.invoke_any``'s own docstring), so the peeled wrapper's
``kind``/``label`` are simply discarded there, consistent with how that
surface already treats every other ``Reusable`` case.

No unittest.mock.patch / MagicMock / AsyncMock. Real FakeModelClient, real
registries, real ASGI app via httpx.ASGITransport — mirrors
test_rt001_deferred_reusable_unwrap.py, test_rt002_invoke_any_reusable_unwrap.py,
and test_rt001_gen_tool_terminal_deferred_result.py's patterns.
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


# ── shared job bodies ────────────────────────────────────────────────────────


async def _job() -> str:
    await asyncio.sleep(0)
    return "RT010_RESOLVED"


# ── 1: unit-level, run_loop — coroutine tool ────────────────────────────────

coro_tools = ToolSet()


@coro_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def reusable_wraps_deferred_tool() -> Reusable:
    """Returns Reusable(value=DeferredResult(...)) — the unhandled order."""
    return Reusable(value=DeferredResult(handle=_job()), kind="entity_id", label="Pending")


async def test_run_loop_emits_deferred_event_for_reusable_wrapped_deferred_result() -> None:
    registry = ToolRegistry([coro_tools], {})
    model = FakeModelClient().script(tool_call("reusable_wraps_deferred_tool", {}))

    events = []
    async for event in run_loop(
        model=model,
        registry=registry,
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
    assert isinstance(deferred_events[0].deferred, DeferredResult)
    resolved = await deferred_events[0].deferred.handle
    assert resolved == "RT010_RESOLVED"

    for event in events:
        if isinstance(event, ToolResultEvent):
            assert not isinstance(event.result, DeferredResult), (
                "raw DeferredResult leaked onto ToolResultEvent instead of "
                "being handed off via DeferredEvent"
            )
            assert not isinstance(event.result, Reusable), (
                "raw Reusable wrapper leaked onto ToolResultEvent"
            )

    assert not any(isinstance(e, DoneEvent) for e in events), (
        "run_loop must not emit DoneEvent itself when handing off a "
        "Reusable-wrapped DeferredResult; the runner's background awaiter "
        "owns task completion"
    )


# ── 2: unit-level, run_loop — async-generator tool ──────────────────────────

gen_tools = ToolSet()


@gen_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def reusable_wraps_deferred_gen_tool() -> AsyncGenerator[Any, None]:
    """Async-generator whose terminal yield is Reusable(value=DeferredResult(...))."""
    yield Reusable(value=DeferredResult(handle=_job()), kind="entity_id", label="Pending")


async def test_run_loop_emits_deferred_event_for_reusable_wrapped_deferred_result_generator() -> (
    None
):
    registry = ToolRegistry([gen_tools], {})
    model = FakeModelClient().script(tool_call("reusable_wraps_deferred_gen_tool", {}))

    events = []
    async for event in run_loop(
        model=model,
        registry=registry,
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
    resolved = await deferred_events[0].deferred.handle
    assert resolved == "RT010_RESOLVED"

    for event in events:
        if isinstance(event, ToolResultEvent):
            assert not isinstance(event.result, (DeferredResult, Reusable))


# ── 3: end-to-end runner — coroutine and generator tools reach COMPLETED ────


async def _run_via_runner(registry: ToolRegistry, tool_name: str) -> tuple[str, Any]:
    store = InMemoryTaskStore()
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})

    model = FakeModelClient().script(tool_call(tool_name, {}))
    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=registry,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )
    deadline = asyncio.get_running_loop().time() + 5.0
    while True:
        rec = store.get(task.id)
        assert rec is not None, "task record evicted during wait"
        state = rec.task.status.state
        if state in (TaskState.COMPLETED, TaskState.FAILED):
            return state, rec
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"task stuck in state {state!r}")
        await asyncio.sleep(0.02)


async def test_runner_resolves_reusable_wrapped_deferred_result_to_completed() -> None:
    registry = ToolRegistry([coro_tools], {})
    state, rec = await asyncio.wait_for(
        _run_via_runner(registry, "reusable_wraps_deferred_tool"), timeout=5.0
    )
    assert state == TaskState.COMPLETED, f"expected COMPLETED, got {state!r}"

    assert "DeferredResult(" not in repr(rec.messages), (
        "raw DeferredResult repr leaked into the transcript"
    )
    assert "Reusable(" not in repr(rec.messages), (
        "raw Reusable repr leaked into the transcript"
    )

    tool_result_msgs = [
        block["toolResult"]
        for msg in rec.messages
        if msg.get("role") == "user"
        for block in msg.get("content") or []
        if isinstance(block, dict) and "toolResult" in block
    ]
    assert len(tool_result_msgs) == 1, f"expected exactly one toolResult, got {rec.messages}"
    result_block = tool_result_msgs[0]
    assert result_block["status"] == "success"
    assert result_block["content"][0] == {"text": "RT010_RESOLVED"}

    # The pre-resolution label is honoured once the handle resolves: the
    # runner threads the ORIGINAL wrapper's kind/label (captured by loop.py
    # before the deferred handoff, since run_loop exits before its own
    # Reusable unwrap would otherwise see them) onto the now-known value.
    index = scan_resolved(rec.messages)
    assert index == {"entity_id": [("Pending", "RT010_RESOLVED")]}, (
        f"expected the pre-resolution label folded against the resolved "
        f"value once the deferred handle completes: {index}"
    )

    assert rec.task.artifacts, "expected a terminal artifact"
    artifact_wire = rec.task.artifacts[-1].wire()
    assert "DeferredResult(" not in repr(artifact_wire)
    assert "Reusable(" not in repr(artifact_wire)


async def test_runner_resolves_reusable_wrapped_deferred_result_generator_to_completed() -> (
    None
):
    registry = ToolRegistry([gen_tools], {})
    state, rec = await asyncio.wait_for(
        _run_via_runner(registry, "reusable_wraps_deferred_gen_tool"), timeout=5.0
    )
    assert state == TaskState.COMPLETED, f"expected COMPLETED, got {state!r}"
    assert "DeferredResult(" not in repr(rec.messages)
    assert "Reusable(" not in repr(rec.messages)


# ── 4: unit-level, registry.py invoke_any ───────────────────────────────────


async def test_invoke_any_resolves_reusable_wrapped_deferred_result():
    async def _fn() -> Reusable:
        return Reusable(
            value=DeferredResult(handle=_job()), kind="entity_id", label="Pending"
        )

    decl = ToolDecl(
        fn=_fn,
        name="rt010_reusable_wraps_deferred_unit_tool",
        description="reusable wraps deferred",
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
        f"invoke_any must unwrap the pre-resolution Reusable wrapper: {result!r}"
    )
    assert not isinstance(result, DeferredResult), (
        f"invoke_any must resolve the nested DeferredResult, not return it "
        f"verbatim: {result!r}"
    )
    assert result == "RT010_RESOLVED"


# ── 5: end-to-end MCP tools/call + admin try-tool ───────────────────────────

e2e_tools = ToolSet()


@e2e_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def rt010_e2e_reusable_deferred_tool() -> Reusable:
    """Reusable(value=DeferredResult(...)) dispatched via MCP/admin."""
    return Reusable(value=DeferredResult(handle=_job()), kind="entity_id", label="Pending")


@pytest.fixture
def rt010_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [e2e_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def rt010_client(rt010_app):
    async with rt010_app.router.lifespan_context(rt010_app):
        _, token = rt010_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rt010_app),
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


async def _mcp_call(
    client: httpx.AsyncClient, headers: dict[str, str], name: str
) -> dict[str, Any]:
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "result" in body, f"expected a JSON-RPC result, got {body}"
    return body["result"]


async def test_mcp_tools_call_reusable_wrapped_deferred_result_resolves(
    rt010_client,
) -> None:
    headers = await _mcp_init(rt010_client)
    result = await asyncio.wait_for(
        _mcp_call(rt010_client, headers, "rt010_e2e_reusable_deferred_tool"), timeout=5.0
    )

    assert result.get("isError") is False, (
        f"expected a clean isError:false, never a leaked DeferredResult/"
        f"Reusable repr under isError:false: {result}"
    )
    text = result["content"][0]["text"]
    assert text == "RT010_RESOLVED", f"expected the fully-resolved value, got {text!r}"
    assert "DeferredResult(" not in text and "Reusable(" not in text


async def test_admin_try_tool_reusable_wrapped_deferred_result_resolves(
    rt010_client,
) -> None:
    r = await rt010_client.post(
        "/admin/api/tools/rt010_e2e_reusable_deferred_tool/try", json={}
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True, body
    assert body["result"] == "RT010_RESOLVED", (
        f"expected the fully-resolved value, not a wrapper's raw fields: {body}"
    )


async def test_reusable_wrapped_deferred_result_parity_across_mcp_and_runner(
    rt010_client,
) -> None:
    """The SAME tool contract must succeed identically over MCP and the
    A2A/AG-UI runner — the exact §5.6 parity theme every other GH-148/RT-001
    fix in this codebase locks down.
    """
    headers = await _mcp_init(rt010_client)
    mcp_result = await asyncio.wait_for(
        _mcp_call(rt010_client, headers, "rt010_e2e_reusable_deferred_tool"), timeout=5.0
    )
    registry = ToolRegistry([e2e_tools], {})
    runner_state, _ = await asyncio.wait_for(
        _run_via_runner(registry, "rt010_e2e_reusable_deferred_tool"), timeout=5.0
    )

    assert mcp_result.get("isError") is False, (
        f"MCP surface: expected isError:false, got {mcp_result}"
    )
    assert runner_state == TaskState.COMPLETED, (
        f"runner surface: expected COMPLETED, got {runner_state!r}"
    )
