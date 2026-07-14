"""RT-001 follow-up: ``POST /admin/api/tools/{name}/try`` now dispatches
through the same ``ToolEntry.invoke_any()`` helper ``routes/mcp.py`` uses, so
a ``long_running=True`` coroutine tool returning ``DeferredResult`` resolves
the handle inline instead of leaking the internal ``DeferredResult`` object
(previously unhandled by ``try_tool``'s bespoke dispatch).

Tests:
1. test_try_tool_deferred_result_resolves: the handle's resolved value is
   returned, never a raw DeferredResult / coroutine repr.
2. test_try_tool_deferred_result_timeout: a DeferredResult whose handle never
   resolves, under a small ``tool_timeout_override``, returns the existing
   timeout error shape promptly rather than hanging or leaking a repr.
"""

from __future__ import annotations

import asyncio
import gc

import httpx
import pytest

from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.routes import admin as admin_route

admin_deferred_tools = ToolSet()


@admin_deferred_tools.tool(tier=1, long_running=True, tool_timeout_override=10.0)
async def admin_deferred_tool() -> DeferredResult:
    """Long-running coroutine tool that returns a DeferredResult immediately."""

    async def _job() -> str:
        await asyncio.sleep(0)
        return "deferred-done"

    return DeferredResult(handle=_job())


@admin_deferred_tools.tool(tier=1, long_running=True)
async def admin_deferred_timeout_tool() -> DeferredResult:
    """DeferredResult whose handle never resolves."""
    return DeferredResult(handle=asyncio.sleep(9999))


@pytest.fixture
def admin_deferred_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [admin_deferred_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def admin_deferred_client(admin_deferred_app):
    async with admin_deferred_app.router.lifespan_context(admin_deferred_app):
        _, token = admin_deferred_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=admin_deferred_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as c:
            yield c


async def test_try_tool_deferred_result_resolves(admin_deferred_client) -> None:
    r = await admin_deferred_client.post("/admin/api/tools/admin_deferred_tool/try", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True, f"expected ok: True, got {body}"
    assert body["result"] == "deferred-done"


async def test_try_tool_deferred_result_timeout(admin_deferred_client, monkeypatch) -> None:
    # admin's try-tool timeout budget is a fixed per-tier table, independent
    # of any @tool tool_timeout_override — shrink it here so the never-
    # resolving handle times out promptly instead of at the real 130s budget.
    monkeypatch.setattr(admin_route, "_TRY_TIMEOUTS", {1: 0.05, 2: 0.05})
    r = await asyncio.wait_for(
        admin_deferred_client.post(
            "/admin/api/tools/admin_deferred_timeout_tool/try", json={}
        ),
        timeout=5.0,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is False, f"expected ok: False on timeout, got {body}"
    assert body["error"]["category"] == "timeout"
