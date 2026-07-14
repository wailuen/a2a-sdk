"""RT-001 (w034/RT-001): async-generator tools must hand off a terminal
``DeferredResult`` exactly like coroutine tools do.

Finding: ``run_loop``'s ``is_generator`` branch (agent/loop.py) drained
``invoke_gen`` and set ``result`` to the generator's terminal value, but never
ran the ``isinstance(result, DeferredResult)`` handoff that the coroutine
branch performs. A long-running ASYNC-GENERATOR tool whose final yield was a
``DeferredResult`` was therefore never recognised as deferred: no
``DeferredEvent`` was emitted, the raw ``DeferredResult`` (with its unawaited
coroutine handle) was folded into the model conversation and shipped on
``ToolResultEvent``, and the handle's background job never ran. The identical
tool dispatched over MCP (``ToolEntry.invoke_any`` -> ``resolve_deferred_result``)
worked correctly — a transport contract drift between the A2A/AG-UI streaming
surface and the MCP surface for the exact same tool contract.

Fixed by applying the same ``isinstance(result, DeferredResult)`` handoff to
the generator branch immediately after the drain completes.

Mirrors ``test_rt001_deferred_nesting_parity.py``'s pattern: drive the SAME
``ToolSet``/``ToolDecl`` through both the runner (A2A/AG-UI) and MCP surfaces
and assert identical, successful outcomes. No unittest.mock — real
FakeModelClient, real registries, real ASGI app via httpx.ASGITransport.
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
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.example.agent import make_agent
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])

gen_deferred_tools = ToolSet()
_side_effect = {"ran": False}


async def _gen_job() -> str:
    await asyncio.sleep(0)
    _side_effect["ran"] = True
    return "gen-deferred-resolved"


@gen_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def gen_terminal_deferred_tool() -> AsyncGenerator[Any, None]:
    """Async-generator tool whose FINAL yield is a DeferredResult.

    Python async generators cannot ``return`` a value — the terminal result
    (here, the DeferredResult itself) must be the last ``yield``.
    """
    yield DeferredResult(handle=_gen_job())


# RT-001 follow-up: the generator branch's DeferredEvent handoff (loop.py:480)
# only proved a SINGLE-level deferral resolves. The nested-resolution chain
# itself lives in the shared ``resolve_deferred_result`` (C-012), which the
# runner's background awaiter calls regardless of whether the DeferredEvent
# originated from a coroutine or an async-generator tool — but nothing drove
# a NESTED DeferredResult through the generator path end-to-end before. These
# tool pairs mirror test_rt001_deferred_nesting_parity.py's single/double
# depth exactly, so the same COMPLETED/FAILED contract is asserted for the
# generator tool shape, not just the coroutine shape.


async def _gen_nested_single_inner_job() -> str:
    await asyncio.sleep(0)
    return "gen-nested-single-resolved"


async def _gen_nested_single_outer_job() -> DeferredResult:
    await asyncio.sleep(0)
    return DeferredResult(handle=_gen_nested_single_inner_job())


@gen_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def gen_nested_single_deferred_tool() -> AsyncGenerator[Any, None]:
    """Async-generator tool whose terminal yield resolves through exactly
    ONE nested DeferredResult (supported depth)."""
    yield DeferredResult(handle=_gen_nested_single_outer_job())


async def _gen_nested_double_inner_job() -> str:
    await asyncio.sleep(0)
    return "gen-nested-double-should-never-surface"


async def _gen_nested_double_middle_job() -> DeferredResult:
    await asyncio.sleep(0)
    return DeferredResult(handle=_gen_nested_double_inner_job())


async def _gen_nested_double_outer_job() -> DeferredResult:
    await asyncio.sleep(0)
    return DeferredResult(handle=_gen_nested_double_middle_job())


@gen_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def gen_nested_double_deferred_tool() -> AsyncGenerator[Any, None]:
    """Async-generator tool whose terminal yield resolves through TWO
    nested DeferredResults — beyond the supported depth."""
    yield DeferredResult(handle=_gen_nested_double_outer_job())


async def test_run_loop_emits_deferred_event_for_generator_terminal_result() -> None:
    """Unit level: run_loop must yield a DeferredEvent, never a raw
    DeferredResult on ToolResultEvent, for a generator tool's terminal yield.
    """
    registry = ToolRegistry([gen_deferred_tools], {})
    model = FakeModelClient().script(tool_call("gen_terminal_deferred_tool", {}))

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
        f"expected exactly one DeferredEvent for the generator's terminal "
        f"DeferredResult, got {[type(e).__name__ for e in events]}"
    )
    assert isinstance(deferred_events[0].deferred, DeferredResult)
    # run_loop's contract is to hand off the handle, not await it — the
    # runner's background awaiter owns that. Await it here ourselves purely
    # so the test doesn't leak an unawaited-coroutine ResourceWarning; a
    # separate end-to-end test below covers the runner actually awaiting it.
    resolved = await deferred_events[0].deferred.handle
    assert resolved == "gen-deferred-resolved"

    # The raw DeferredResult must never be smuggled onto a ToolResultEvent —
    # that would fold `str(DeferredResult(handle=<coroutine ...>))` into the
    # model conversation and leak an unawaited-coroutine repr onto the wire.
    for event in events:
        if isinstance(event, ToolResultEvent):
            assert not isinstance(event.result, DeferredResult), (
                "raw DeferredResult leaked onto ToolResultEvent instead of "
                "being handed off via DeferredEvent"
            )

    # The loop must exit immediately after the DeferredEvent — the runner's
    # background awaiter takes over; no DoneEvent should follow it in the
    # SAME generator branch's turn.
    assert not any(isinstance(e, DoneEvent) for e in events), (
        "run_loop must not emit DoneEvent itself when handing off a "
        "generator-terminal DeferredResult; the runner's background "
        "awaiter owns task completion"
    )


async def _run_via_runner(tool_name: str) -> str:
    registry = ToolRegistry([gen_deferred_tools], {})
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
            return state
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"task stuck in state {state!r}")
        await asyncio.sleep(0.02)


async def test_runner_resolves_generator_terminal_deferred_result_to_completed() -> None:
    """End-to-end: run_task_worker must drive the task to COMPLETED and
    actually run the deferred handle's side effect — not leak it unawaited.
    """
    _side_effect["ran"] = False
    state = await asyncio.wait_for(
        _run_via_runner("gen_terminal_deferred_tool"), timeout=5.0
    )
    assert state == TaskState.COMPLETED, (
        f"expected COMPLETED once the generator's terminal DeferredResult is "
        f"resolved by the runner, got {state!r}"
    )
    assert _side_effect["ran"] is True, (
        "the deferred handle's side effect never ran — the handle was "
        "leaked unawaited (ResourceWarning: coroutine never awaited)"
    )


async def test_runner_resolves_generator_nested_single_deferred_result_to_completed() -> (
    None
):
    """End-to-end: a generator's terminal DeferredResult that itself
    resolves through ONE nested DeferredResult must still reach COMPLETED —
    the resolve_deferred_result chain (C-012) applies identically regardless
    of whether the DeferredEvent originated from a coroutine or generator
    tool.
    """
    state = await asyncio.wait_for(
        _run_via_runner("gen_nested_single_deferred_tool"), timeout=5.0
    )
    assert state == TaskState.COMPLETED, (
        f"expected COMPLETED for a single-level nested generator-terminal "
        f"DeferredResult, got {state!r}"
    )


async def test_runner_resolves_generator_nested_double_deferred_result_to_failed() -> None:
    """End-to-end: nesting beyond the supported depth must FAIL the task for
    a generator-terminal DeferredResult exactly as it does for a coroutine
    tool's terminal DeferredResult.
    """
    state = await asyncio.wait_for(
        _run_via_runner("gen_nested_double_deferred_tool"), timeout=5.0
    )
    assert state == TaskState.FAILED, (
        f"expected FAILED once nesting exceeds the supported depth for a "
        f"generator-terminal DeferredResult, got {state!r}"
    )


@pytest.fixture
def parity_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [gen_deferred_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def parity_client(parity_app):
    async with parity_app.router.lifespan_context(parity_app):
        _, token = parity_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=parity_app),
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


async def test_generator_terminal_deferred_result_parity_across_mcp_and_runner(
    parity_client,
) -> None:
    """The SAME async-generator tool contract must resolve identically
    (success) whether dispatched via MCP tools/call or the A2A/AG-UI runner —
    the exact transport drift RT-001 (w034) found.
    """
    headers = await _mcp_init(parity_client)
    mcp_result = await asyncio.wait_for(
        _mcp_call(parity_client, headers, "gen_terminal_deferred_tool"), timeout=5.0
    )
    runner_state = await asyncio.wait_for(
        _run_via_runner("gen_terminal_deferred_tool"), timeout=5.0
    )

    assert mcp_result.get("isError") is False, (
        f"MCP surface: expected isError:false, got {mcp_result}"
    )
    assert runner_state == TaskState.COMPLETED, (
        f"runner surface: expected COMPLETED, got {runner_state!r}"
    )


async def test_generator_nested_single_deferred_result_parity_across_mcp_and_runner(
    parity_client,
) -> None:
    """Same nested-DeferredResult depth as
    test_rt001_deferred_nesting_parity.py's single-level case, but for a
    generator tool: MCP and the runner must agree (success on both).
    """
    headers = await _mcp_init(parity_client)
    mcp_result = await asyncio.wait_for(
        _mcp_call(parity_client, headers, "gen_nested_single_deferred_tool"),
        timeout=5.0,
    )
    runner_state = await asyncio.wait_for(
        _run_via_runner("gen_nested_single_deferred_tool"), timeout=5.0
    )

    assert mcp_result.get("isError") is False, (
        f"MCP surface: expected isError:false for single-level nested "
        f"generator-terminal DeferredResult, got {mcp_result}"
    )
    assert runner_state == TaskState.COMPLETED, (
        f"runner surface: expected COMPLETED for single-level nested "
        f"generator-terminal DeferredResult, got {runner_state!r}"
    )


async def test_generator_nested_double_deferred_result_parity_across_mcp_and_runner(
    parity_client,
) -> None:
    """Same nested-DeferredResult depth as
    test_rt001_deferred_nesting_parity.py's double-level case, but for a
    generator tool: MCP and the runner must agree (failure on both).
    """
    headers = await _mcp_init(parity_client)
    mcp_result = await asyncio.wait_for(
        _mcp_call(parity_client, headers, "gen_nested_double_deferred_tool"),
        timeout=5.0,
    )
    runner_state = await asyncio.wait_for(
        _run_via_runner("gen_nested_double_deferred_tool"), timeout=5.0
    )

    assert mcp_result.get("isError") is True, (
        f"MCP surface: expected isError:true for double-level nested "
        f"generator-terminal DeferredResult, got {mcp_result}"
    )
    assert runner_state == TaskState.FAILED, (
        f"runner surface: expected FAILED for double-level nested "
        f"generator-terminal DeferredResult, got {runner_state!r}"
    )
