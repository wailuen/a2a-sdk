"""GH-135: a ValidationError raised INSIDE a tool body (e.g. constructing a
ContentModel with bad data) must not be misreported as caller-input error.

Root cause: registry.py's invoke()/invoke_gen() ran input_model.model_validate
(arguments) and the tool body itself in the same try scope in loop.py, so a
bare ``except ValidationError`` could not distinguish "the caller's tool_call
arguments failed schema coercion" from "the tool body itself raised
ValidationError constructing something downstream" — both were reported via
safe_validation_message() as if the MODEL's tool_call arguments were bad,
which triggers an unresolvable retry loop (the model has no way to fix
arguments that were never the problem).

Fix: ToolInputValidationError (registry.py) is raised ONLY by the
input-model coercion step. loop.py's three ``except ValidationError`` sites
became ``except ToolInputValidationError`` — a body-raised ValidationError no
longer matches and falls through to the generic/internal-failure path
instead.

Covers all three sites (loc: agent/loop.py):
- the async-generator tool drain branch
- the coroutine tool invoke branch
- the interrupt resume_handler branch
"""

from __future__ import annotations

import gc
import logging
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
from pydantic import BaseModel, field_validator

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import ToolInterrupt, run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.example.agent import make_agent
from agent_sdk.models.content_types import MetricItem
from agent_sdk.testing import FakeModelClient, tool_call

tools = ToolSet()


@tools.tool(tier=1)
async def body_validation_tool() -> dict[str, Any]:
    """Tool takes no arguments; its BODY constructs a ContentModel with bad
    data. Not a caller-input problem — the tool_call arguments (none) were
    always valid."""
    MetricItem(label="x", value=True)  # bool is rejected -> ValidationError
    return {}


@tools.tool(tier=1)
async def body_validation_gen_tool() -> AsyncGenerator[Any, None]:
    """Same failure mode, but from the async-generator drain branch."""
    MetricItem(label="x", value=True)  # bool is rejected -> ValidationError
    yield {}


async def _bad_resume_handler(resume_value: Any) -> Any:
    MetricItem(label="x", value=True)  # bool is rejected -> ValidationError
    return resume_value


@tools.tool(tier=1)
async def interrupt_body_validation_tool() -> dict[str, Any]:
    """Raises ToolInterrupt whose resume_handler itself raises ValidationError
    once resumed — never routed through registry input coercion."""
    raise ToolInterrupt(
        "confirm", "please confirm", resume_handler=_bad_resume_handler
    )


# RT-011: every test above proves the misreport/logging fix using a
# NON-secret rejected value (a bare ``bool``, or the literal strings "x" /
# "True"). None of them prove the SI-2 contract holds when the rejected
# value actually LOOKS like a credential — the exact shape GH-135's own AC
# names ("a ValidationError whose msg interpolates a secret-looking value").
# Pin that with the literal attack input, on every dispatch surface that can
# hit this same generic catch-all: agent loop (ToolResultEvent + its log),
# MCP tools/call (wire response + its log), and the admin try-tool endpoint
# (wire response + its log) — reusing sdk_caplog (LRN-106) so the assertion
# is not order-dependent on root-logger propagation.
_LEAKED_SECRET = "sk_live_9f3d8b2c1a4e5f60SECRETVALUE"


class _SecretLeakInternalModel(BaseModel):
    token: str

    @field_validator("token")
    @classmethod
    def _reject(cls, v: str) -> str:
        # Mirrors the documented SI-2 anti-pattern (routes/admin.py's
        # ToolInputValidationError comment): a custom validator that
        # interpolates the rejected value straight into the error message.
        raise ValueError(f"bad token {v!r}")


@tools.tool(tier=1)
async def body_secret_leak_tool() -> dict[str, Any]:
    """Tool takes no arguments; its BODY constructs an internal model whose
    field validator embeds a secret-looking value in the raised
    ValidationError. Not a caller-input problem — the tool_call arguments
    (none) were always valid."""
    _SecretLeakInternalModel(token=_LEAKED_SECRET)
    return {}


REGISTRY = ToolRegistry([tools], {})


async def _wait_resume(interrupt_id: str) -> Any:
    return {"confirmed": True}


async def _collect(model: FakeModelClient, *, with_resume: bool = False) -> list[Any]:
    events: list[Any] = []
    async for ev in run_loop(
        model=model,
        registry=REGISTRY,
        adapters={},
        system="test",
        messages=[{"role": "user", "content": [{"text": "go"}]}],
        wait_resume=_wait_resume if with_resume else None,
    ):
        events.append(ev)
    return events


def _tool_result(events: list[Any]) -> ToolResultEvent:
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert results, "expected at least one ToolResultEvent"
    return results[0]


async def test_coroutine_tool_body_validation_error_not_reported_as_caller_input():
    model = FakeModelClient([tool_call("body_validation_tool", {})])
    result = _tool_result(await _collect(model))
    assert not result.ok
    assert "input invalid" not in result.error, (
        f"body-raised ValidationError misreported as caller-input error: {result.error!r}"
    )
    assert result.error == "tool 'body_validation_tool' failed", result.error


async def test_generator_tool_body_validation_error_not_reported_as_caller_input():
    model = FakeModelClient([tool_call("body_validation_gen_tool", {})])
    result = _tool_result(await _collect(model))
    assert not result.ok
    assert "input invalid" not in result.error, (
        f"body-raised ValidationError misreported as caller-input error: {result.error!r}"
    )
    assert result.error == "tool 'body_validation_gen_tool' failed", result.error


async def test_resume_handler_validation_error_not_reported_as_caller_input():
    model = FakeModelClient([tool_call("interrupt_body_validation_tool", {})])
    result = _tool_result(await _collect(model, with_resume=True))
    assert not result.ok
    assert "input invalid" not in result.error, (
        f"body-raised ValidationError misreported as caller-input error: {result.error!r}"
    )
    assert result.error == "tool 'interrupt_body_validation_tool' failed after resume", (
        result.error
    )


# RT-008: the fixed generic string reaching the tool result (asserted above)
# is only half of GH-135's SI-2 AC — the internal path must ALSO log the
# exception via logger.exception/logger.error so the failure class is
# diagnosable in production. loop.py's three bare ``except Exception:``
# catch-alls bound no exception and logged nothing, breaking parity with the
# mcp.py/admin.py siblings (C-012 cross-surface parity contract). These
# assert each site logs exactly one record naming the exception TYPE only —
# never the label/value that triggered it (SI-2: no field values echoed).


async def test_coroutine_tool_body_validation_error_logs_exception_type(sdk_caplog):
    model = FakeModelClient([tool_call("body_validation_tool", {})])
    with sdk_caplog("agent_sdk.agent.loop", logging.ERROR) as records:
        await _collect(model)
    assert len(records) == 1, [r.getMessage() for r in records]
    message = records[0].getMessage()
    assert "ValidationError" in message, message
    assert "x" not in message, f"field label leaked into log: {message!r}"
    assert "True" not in message, f"field value leaked into log: {message!r}"


async def test_generator_tool_body_validation_error_logs_exception_type(sdk_caplog):
    model = FakeModelClient([tool_call("body_validation_gen_tool", {})])
    with sdk_caplog("agent_sdk.agent.loop", logging.ERROR) as records:
        await _collect(model)
    assert len(records) == 1, [r.getMessage() for r in records]
    message = records[0].getMessage()
    assert "ValidationError" in message, message
    assert "x" not in message, f"field label leaked into log: {message!r}"
    assert "True" not in message, f"field value leaked into log: {message!r}"


async def test_resume_handler_validation_error_logs_exception_type(sdk_caplog):
    model = FakeModelClient([tool_call("interrupt_body_validation_tool", {})])
    with sdk_caplog("agent_sdk.agent.loop", logging.ERROR) as records:
        await _collect(model, with_resume=True)
    assert len(records) == 1, [r.getMessage() for r in records]
    message = records[0].getMessage()
    assert "ValidationError" in message, message
    assert "x" not in message, f"field label leaked into log: {message!r}"
    assert "True" not in message, f"field value leaked into log: {message!r}"


# ── RT-011: literal secret-looking value, pinned across loop/MCP/admin ──


async def test_loop_tool_body_validation_error_secret_not_leaked(sdk_caplog):
    """RT-011: the loop surface half of the parity pin — a body-raised
    ValidationError whose message embeds a secret-looking value must not
    reach the ToolResultEvent.error text nor any LogRecord agent/loop.py
    emits while handling it (only the exception TYPE may be logged, per
    RT-008 above)."""
    model = FakeModelClient([tool_call("body_secret_leak_tool", {})])
    with sdk_caplog("agent_sdk.agent.loop", logging.WARNING) as records:
        result = _tool_result(await _collect(model))
    assert not result.ok
    assert _LEAKED_SECRET not in result.error, (
        f"SI-2 leak: secret-looking value echoed in loop ToolResultEvent.error: {result.error!r}"
    )
    assert result.error == "tool 'body_secret_leak_tool' failed", result.error
    assert records, "expected the catch-all branch to log something diagnosable"
    for record in records:
        assert _LEAKED_SECRET not in record.getMessage(), (
            f"SI-2 leak: secret-looking value in log message: {record.getMessage()!r}"
        )
        formatted = logging.Formatter().format(record)
        assert _LEAKED_SECRET not in formatted, (
            f"SI-2 leak: secret-looking value in formatted log output "
            f"(likely via logger.exception's traceback): {formatted!r}"
        )
        assert record.exc_info is None, (
            "generic branch must not use logger.exception / exc_info=True — "
            "ValidationError's message (embedded in the traceback) carries "
            "the raw rejected value (SI-2)"
        )


@pytest.fixture
def secret_leak_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def secret_leak_client(secret_leak_app):
    async with secret_leak_app.router.lifespan_context(secret_leak_app):
        _, token = secret_leak_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=secret_leak_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
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


async def _invoke_via_mcp(client: httpx.AsyncClient) -> str:
    headers = await _mcp_init(client)
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "body_secret_leak_tool", "arguments": {}},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    result = r.json()["result"]
    assert result.get("isError") is True, result
    return r.text


async def _invoke_via_admin(client: httpx.AsyncClient) -> str:
    r = await client.post("/admin/api/tools/body_secret_leak_tool/try", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("ok") is False, body
    return r.text


@pytest.mark.parametrize(
    "invoke_surface", [_invoke_via_mcp, _invoke_via_admin], ids=["mcp", "admin"]
)
async def test_wire_surface_tool_body_validation_error_secret_not_leaked(
    invoke_surface, secret_leak_client, sdk_caplog
):
    """RT-011: the MCP + admin half of the parity pin. Both surfaces dispatch
    through the shared ``ToolEntry.invoke_any()`` helper (C-010) and share
    the same generic ``except Exception`` catch-all shape as agent/loop.py —
    a secret-looking value embedded in a tool-body ValidationError's message
    must not reach the wire response body, nor any LogRecord either surface
    emits while handling it."""
    with sdk_caplog("agent_sdk", logging.WARNING) as records:
        wire_text = await invoke_surface(secret_leak_client)
    assert _LEAKED_SECRET not in wire_text, (
        f"SI-2 leak: secret-looking value echoed on the wire: {wire_text!r}"
    )
    assert records, "expected the catch-all branch to log something diagnosable"
    for record in records:
        assert _LEAKED_SECRET not in record.getMessage(), (
            f"SI-2 leak: secret-looking value in log message: {record.getMessage()!r}"
        )
        formatted = logging.Formatter().format(record)
        assert _LEAKED_SECRET not in formatted, (
            f"SI-2 leak: secret-looking value in formatted log output "
            f"(likely via logger.exception's traceback): {formatted!r}"
        )
        assert record.exc_info is None, (
            "generic branch must not use logger.exception / exc_info=True — "
            "ValidationError's message (embedded in the traceback) carries "
            "the raw rejected value (SI-2)"
        )
    joined = " ".join(r.getMessage() for r in records)
    assert "ValidationError" in joined, (
        f"expected the exception TYPE name for diagnosability, got: {joined!r}"
    )
