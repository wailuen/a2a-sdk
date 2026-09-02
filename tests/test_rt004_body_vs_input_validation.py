"""RT-004: a ValidationError raised INSIDE a tool body must never be reported
as "input invalid" — only ``ToolEntry.invoke``/``invoke_gen`` calling
``input_model.model_validate(arguments)`` may earn that label.

Before the fix, ``agent/loop.py``'s ``except ValidationError`` handlers (the
coroutine branch, the async-generator branch, and the post-interrupt
``resume_handler`` branch) could not tell an input-model failure apart from a
ValidationError raised while a tool constructs its ContentModel return value
— every tool must return one, so this is the common case, not an edge case.
All three unconditionally formatted the error against ``entry.decl.input_model``
via ``safe_validation_message``, so a tool whose INPUT was perfectly valid
could still get told "tool 'x' input invalid: <unrelated field> — ...",
sending the model into a pointless retry loop on input it never got wrong.

The fix: ``ToolEntry.invoke``/``invoke_gen`` validate the input in a narrow
try/except and re-raise ``ToolInputValidationError`` (registry.py) — the loop
labels ONLY that as "input invalid"; a bare ``ValidationError`` (raised by
tool body code, or by a ``resume_handler``) now falls through to the generic
"tool '<name>' failed" branch, same as any other unclaimed exception.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncGenerator

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import ToolInterrupt, run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient, tool_call

pytestmark = pytest.mark.asyncio


# ── shared tool declarations ──────────────────────────────────────────────


class BodyIn(BaseModel):
    x: int


class StrictOut(BaseModel):
    """Deliberately unrelated field name to BodyIn.x — proves a mislabeled
    error is blaming the wrong model, not merely reusing a shared name."""

    count: int


tools = ToolSet()


@tools.tool(tier=1)
async def body_validation_tool(inp: BodyIn) -> StrictOut:
    """Input is always valid; the BODY raises ValidationError building its
    return value — the common "every tool returns a ContentModel" case."""
    return StrictOut(count="not-an-int")  # type: ignore[arg-type]


@tools.tool(tier=1)
async def body_validation_gen_tool(inp: BodyIn) -> AsyncGenerator[Any, None]:
    """Async-generator sibling of ``body_validation_tool`` — input valid,
    body raises ValidationError before producing its terminal yield."""
    StrictOut(count="not-an-int")  # type: ignore[arg-type]
    yield None


async def _failing_resume_handler(resume_value: Any) -> Any:
    StrictOut(count="not-an-int")  # type: ignore[arg-type]
    return resume_value


@tools.tool(tier=1)
async def interrupt_then_bad_resume_tool(inp: BodyIn) -> Any:
    """Input is always valid; raises a ToolInterrupt whose resume_handler
    raises ValidationError — never went through model_validate at all."""
    raise ToolInterrupt(
        "need-more-info", "give me more", resume_handler=_failing_resume_handler
    )


class GenStrictIn(BaseModel):
    count: int


@tools.tool(tier=1)
async def generator_strict_tool(inp: GenStrictIn) -> AsyncGenerator[Any, None]:
    """Genuine input-model tool, async-generator shape (regression guard for
    the real "input invalid" path GH-48 already covers for coroutine tools)."""
    yield {"n": inp.count}


REGISTRY = ToolRegistry([tools], {})


async def _collect(model: FakeModelClient, tool_name: str, arguments: dict[str, Any]):
    resumed = {"called": False}

    async def wait_resume(_interrupt_id: str) -> Any:
        resumed["called"] = True
        return {"ok": True}

    events = []
    async for ev in run_loop(
        model=model,
        registry=REGISTRY,
        adapters={},
        system="test",
        messages=[{"role": "user", "content": [{"text": "go"}]}],
        wait_resume=wait_resume,
    ):
        events.append(ev)
    return events


def _first_result(events: list[Any]) -> ToolResultEvent:
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert results, "expected at least one ToolResultEvent"
    return results[0]


# ── coroutine tool: body-level ValidationError ──────────────────────────────


async def test_coroutine_body_validation_error_is_not_labeled_input_invalid():
    model = FakeModelClient([tool_call("body_validation_tool", {"x": 1})])
    result = _first_result(await _collect(model, "body_validation_tool", {"x": 1}))
    assert not result.ok
    assert "input invalid" not in result.error, (
        f"body-level ValidationError mislabeled as input error: {result.error!r}"
    )
    assert result.error == "tool 'body_validation_tool' failed", result.error


# ── async-generator tool: body-level ValidationError ────────────────────────


async def test_generator_body_validation_error_is_not_labeled_input_invalid():
    model = FakeModelClient([tool_call("body_validation_gen_tool", {"x": 1})])
    result = _first_result(await _collect(model, "body_validation_gen_tool", {"x": 1}))
    assert not result.ok
    assert "input invalid" not in result.error, (
        f"body-level ValidationError mislabeled as input error: {result.error!r}"
    )
    assert result.error == "tool 'body_validation_gen_tool' failed", result.error


# ── resume_handler: ValidationError after an interrupt ──────────────────────


async def test_resume_handler_validation_error_is_not_labeled_input_invalid():
    model = FakeModelClient([tool_call("interrupt_then_bad_resume_tool", {"x": 1})])
    result = _first_result(
        await _collect(model, "interrupt_then_bad_resume_tool", {"x": 1})
    )
    assert not result.ok
    assert "input invalid" not in result.error, (
        f"resume_handler ValidationError mislabeled as input error: {result.error!r}"
    )
    assert result.error == "tool 'interrupt_then_bad_resume_tool' failed after resume", (
        result.error
    )


# ── regression: genuine input errors keep the "input invalid" label ────────


async def test_generator_genuine_input_validation_error_still_reports_input_invalid():
    model = FakeModelClient([tool_call("generator_strict_tool", {"count": "nope"})])
    result = _first_result(await _collect(model, "generator_strict_tool", {"count": "nope"}))
    assert not result.ok
    assert "input invalid" in result.error, result.error
    assert "count" in result.error, result.error
    assert "nope" not in result.error, f"raw input leaked: {result.error!r}"


# ── MCP / admin surface parity (routes/mcp.py, routes/admin.py mirror loop.py) ──


@pytest.fixture
def parity_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [tools]
    built = agent.build_app()
    yield built
    built.state.credential_store.close()


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


async def test_mcp_body_validation_error_is_not_labeled_input_invalid(parity_client):
    init = await parity_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    assert init.status_code == 200, init.text
    headers = {"MCP-Protocol-Version": "2025-06-18"}
    session = init.headers.get("mcp-session-id")
    if session:
        headers["Mcp-Session-Id"] = session

    r = await parity_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "body_validation_tool", "arguments": {"x": 1}},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result.get("isError") is True, result
    text = result["content"][0]["text"]
    assert "input invalid" not in text, f"body-level error mislabeled: {text!r}"


async def test_admin_try_tool_body_validation_error_is_not_labeled_validation(
    parity_client,
):
    r = await parity_client.post(
        "/admin/api/tools/body_validation_tool/try",
        json={"x": 1},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is False, body
    assert body["error"]["category"] != "validation", (
        f"body-level error mislabeled as input validation: {body['error']!r}"
    )
    assert "input invalid" not in body["error"]["message"], body["error"]
