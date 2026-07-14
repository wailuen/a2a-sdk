"""Admin ``POST /admin/api/tools/{name}/try`` must dispatch async-generator
Tier-1 tools via ``invoke_gen()``, mirroring the ``entry.decl.is_generator``
branch already present in ``routes/mcp.py`` (GH-115) and ``agent/loop.py``.

Before the fix, ``try_tool`` unconditionally called ``entry.invoke()``, which
raises ``TypeError`` for a generator tool (registry.py's ``invoke()``
docstring: "raises TypeError when called on a generator tool"). The blanket
``except Exception`` in ``try_tool`` swallowed that into a generic
``{"category": "internal", "message": "tool raised an unexpected error"}``,
identical to the LRN-116 symptom this wave's Prevention clause calls out.

Tests:
1. test_try_tool_generator_tool_succeeds: a `long_running=True`
   async-generator Tier-1 tool must return ``ok: True`` with the terminal
   result's fields, not the generic internal-error shape.
2. test_try_tool_coroutine_tool_unchanged: an ordinary coroutine tool on the
   same app continues to behave exactly as before (regression guard).
"""

from __future__ import annotations

import gc
from typing import Any, AsyncGenerator

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.events import ToolProgressEvent
from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent


class _GenResult(BaseModel):
    data_type: str = "gen_result"
    value: str = "gen-done"


gen_tools = ToolSet()


@gen_tools.tool(tier=1, emits=_GenResult, long_running=True)
async def admin_gen_tool() -> AsyncGenerator[Any, None]:
    """Async-generator Tier-1 tool: interim progress then a terminal result."""
    yield ToolProgressEvent(message="working", tool_name="admin_gen_tool")
    yield _GenResult(value="gen-done")


@pytest.fixture
def gen_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [gen_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def gen_client(gen_app):
    async with gen_app.router.lifespan_context(gen_app):
        _, token = gen_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=gen_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


async def test_try_tool_generator_tool_succeeds(gen_client) -> None:
    """A long_running=True async-generator tool must NOT raise TypeError inside
    invoke() — try_tool must return ok: True carrying the terminal result."""
    r = await gen_client.post("/admin/api/tools/admin_gen_tool/try", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True, f"expected ok: True, got {body}"
    assert body["result"] == {"data_type": "gen_result", "value": "gen-done"}


async def test_try_tool_coroutine_tool_unchanged(gen_client) -> None:
    """Regression guard: an ordinary coroutine tool (echo, built into the
    example agent) must keep working exactly as before on the same app."""
    r = await gen_client.post("/admin/api/tools/echo/try", json={"text": "hi"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is True, f"expected ok: True, got {body}"
