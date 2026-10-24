"""GH-207: ``@tool(mcp_description=...)`` overrides the description on MCP tools/list only.

Ruling: https://github.com/wailuen/a2a-sdk/issues/207#issuecomment-6359828022
"""

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent

from .test_mcp_conformance_w9 import _mcp_init


class In(BaseModel):
    q: str


def _toolset(**kw) -> ToolSet:
    ts = ToolSet()

    @ts.tool(tier=1, sample={"q": "x"}, **kw)
    async def gh207_tool_x(inp: In) -> dict:
        """Docstring description."""
        return {"q": inp.q}

    return ts


def _app(settings, fake_model, ts: ToolSet):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [ts]
    return agent.build_app()


async def _mcp_tool(app) -> dict:
    _, token = app.state.auth.api_keys.mint("test-admin", admin=True)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            h = await _mcp_init(c)
            r = await c.post(
                "/mcp",
                json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                headers=h,
            )
            return next(t for t in r.json()["result"]["tools"] if t["name"] == "gh207_tool_x")


async def test_mcp_uses_override_card_and_loop_keep_docstring(settings, fake_model):
    ts = _toolset(mcp_description="MCP-only text")
    app = _app(settings, fake_model, ts)
    tool = await _mcp_tool(app)
    assert tool["description"] == "MCP-only text"

    entry = next(e for e in app.state.registry.all() if e.name == "gh207_tool_x")
    assert entry.description == "Docstring description."
    assert entry.decl.mcp_description == "MCP-only text"

    skill = next(s for s in app.state.agent_card["skills"] if s["id"] == "gh207_tool_x")
    assert skill["description"] == "Docstring description."


async def test_unset_mcp_uses_docstring(settings, fake_model):
    tool = await _mcp_tool(_app(settings, fake_model, _toolset()))
    assert tool["description"] == "Docstring description."


@pytest.mark.parametrize("bad", ["", "   \n", "x" * 2049, 123])
def test_bad_mcp_description_rejected_at_boot(bad):
    with pytest.raises(ValueError, match="mcp_description"):
        _toolset(mcp_description=bad)


def test_max_length_accepted():
    _toolset(mcp_description="x" * 2048)


async def test_model_sees_docstring_not_mcp_description(settings):
    from agent_sdk.agent.loop import run_loop
    from agent_sdk.testing import FakeModelClient, reply

    model = FakeModelClient([reply("ok")])
    app = _app(settings, model, _toolset(mcp_description="MCP-only text"))
    events = [
        e
        async for e in run_loop(
            model=model,
            registry=app.state.registry,
            adapters=app.state.adapters,
            system="s",
            messages=[{"role": "user", "content": [{"text": "hi"}]}],
        )
    ]
    assert events
    (call,) = model.calls
    spec = next(t for t in call["tools"] if t["name"] == "gh207_tool_x")
    assert spec["description"] == "Docstring description."
    assert "MCP-only text" not in str(call["tools"])
