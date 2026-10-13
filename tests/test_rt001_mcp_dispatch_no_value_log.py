"""RT-001 (w047): the /mcp dispatch catch-all never logs an exception message."""

from __future__ import annotations

import gc
import logging

import httpx
import pytest
from pydantic import BaseModel, ValidationError

from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.models.content_types import EntityItem, EntityList

MARKER = "MARKER-SECRET-9f3a"
tools = ToolSet()


@tools.tool(tier=1, emits=EntityList)
async def rt001_render_boom() -> EntityList:
    """Return one entity whose rendering fails."""
    return EntityList(entity_type="company", items=[EntityItem(id="1", name="x")])


class _Strict(BaseModel):
    n: int


def _boom(self) -> str:
    try:
        _Strict(n=MARKER)  # type: ignore[arg-type]
    except ValidationError as exc:
        raise exc
    return ""


@pytest.fixture
def rt001_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


async def test_dispatch_catch_all_leaves_marker_out_of_logs(rt001_app, monkeypatch, caplog):
    monkeypatch.setattr(EntityList, "to_plain_text", _boom)
    caplog.set_level(logging.DEBUG)
    async with rt001_app.router.lifespan_context(rt001_app):
        _, token = rt001_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rt001_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}", "MCP-Protocol-Version": "2025-06-18"},
        ) as c:
            r = await c.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
                },
            )
            headers = {}
            if r.headers.get("mcp-session-id"):
                headers["Mcp-Session-Id"] = r.headers["mcp-session-id"]
            r = await c.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {"name": "rt001_render_boom", "arguments": {}},
                },
                headers=headers,
            )
    assert MARKER not in r.text
    assert MARKER not in caplog.text
    for rec in caplog.records:
        assert MARKER not in rec.getMessage()
        assert rec.exc_info is None or MARKER not in str(rec.exc_info[1])
