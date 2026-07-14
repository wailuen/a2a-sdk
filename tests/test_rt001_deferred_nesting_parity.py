"""RT-001: cross-surface parity for nested ``DeferredResult`` resolution.

Finding: ``ToolEntry.invoke_any`` (registry.py, used by MCP ``tools/call`` and
the admin try-tool endpoint) resolved one level of nested ``DeferredResult``
and returned the inner value as a success, while
``runner._run_deferred_background`` (the A2A/AG-UI deferred path) failed on
the FIRST nested ``DeferredResult`` — the identical ``long_running`` tool
contract therefore returned ``isError: false`` over MCP but produced a FAILED
A2A/AG-UI task for the same input. Fixed by routing both surfaces through the
shared ``agent_sdk.agent.registry.resolve_deferred_result`` helper.

This test drives the SAME ``ToolSet``/``ToolDecl`` objects through both
dispatch surfaces (a live MCP ``tools/call`` over the full ASGI app, and
``run_task_worker`` directly) and asserts an IDENTICAL success/failure
outcome for:
  - single-level nesting -> success on both surfaces
  - double-level nesting -> failure on both surfaces

No unittest.mock.patch / MagicMock / AsyncMock. Real FakeModelClient, real
registries, real ASGI app via httpx.ASGITransport.
"""

from __future__ import annotations

import asyncio
import gc
from typing import Any

import httpx
import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.example.agent import make_agent
from agent_sdk.models.a2a import TaskState
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, tool_call

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPABILITIES = A2uiCapabilities(tier="none", catalogs=[])

parity_tools = ToolSet()


async def _single_inner_job() -> str:
    await asyncio.sleep(0)
    return "parity-single-resolved"


async def _single_outer_job() -> DeferredResult:
    await asyncio.sleep(0)
    return DeferredResult(handle=_single_inner_job())


@parity_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def parity_single_nested_tool() -> DeferredResult:
    """Handle resolves to exactly one nested DeferredResult."""
    return DeferredResult(handle=_single_outer_job())


async def _double_inner_job() -> str:
    await asyncio.sleep(0)
    return "parity-should-never-surface"


async def _double_middle_job() -> DeferredResult:
    await asyncio.sleep(0)
    return DeferredResult(handle=_double_inner_job())


async def _double_outer_job() -> DeferredResult:
    await asyncio.sleep(0)
    return DeferredResult(handle=_double_middle_job())


@parity_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def parity_double_nested_tool() -> DeferredResult:
    """Handle resolves through TWO nested DeferredResults."""
    return DeferredResult(handle=_double_outer_job())


# Same ToolDecl objects (parity_tools.decls) back this registry AND the app
# built by the parity_app fixture below — the point of the test.
PARITY_REGISTRY = ToolRegistry([parity_tools], {})


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


async def _run_via_runner(tool_name: str) -> str:
    store = InMemoryTaskStore()
    task = new_task()
    record = store.create(task, _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})

    model = FakeModelClient().script(tool_call(tool_name, {}))
    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=PARITY_REGISTRY,
        adapters={},
        skills=None,
        system="test system prompt",
        capabilities=_CAPABILITIES,
        policies=LoopPolicies(),
    )
    return await _wait_for_state(store, task.id)


@pytest.fixture
def parity_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [parity_tools]
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


async def test_single_nested_deferred_result_identical_across_mcp_and_runner(
    parity_client,
) -> None:
    headers = await _mcp_init(parity_client)
    mcp_result = await asyncio.wait_for(
        _mcp_call(parity_client, headers, "parity_single_nested_tool"), timeout=5.0
    )
    runner_state = await asyncio.wait_for(
        _run_via_runner("parity_single_nested_tool"), timeout=5.0
    )

    assert mcp_result.get("isError") is False, (
        f"MCP surface: expected isError:false for single-level nesting, got {mcp_result}"
    )
    assert runner_state == TaskState.COMPLETED, (
        f"runner surface: expected COMPLETED for single-level nesting, got {runner_state!r}"
    )


async def test_double_nested_deferred_result_identical_across_mcp_and_runner(
    parity_client,
) -> None:
    headers = await _mcp_init(parity_client)
    mcp_result = await asyncio.wait_for(
        _mcp_call(parity_client, headers, "parity_double_nested_tool"), timeout=5.0
    )
    runner_state = await asyncio.wait_for(
        _run_via_runner("parity_double_nested_tool"), timeout=5.0
    )

    assert mcp_result.get("isError") is True, (
        f"MCP surface: expected isError:true for double-level nesting, got {mcp_result}"
    )
    assert runner_state == TaskState.FAILED, (
        f"runner surface: expected FAILED for double-level nesting, got {runner_state!r}"
    )
