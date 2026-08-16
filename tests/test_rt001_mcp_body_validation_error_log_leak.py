"""RT-001 (GH-135 follow-up, SI-2): a ``ValidationError`` raised by a TOOL
BODY (as opposed to the input-model coercion step ``ToolInputValidationError``
guards against) falls through ``_handle_tools_call``'s catch-all
``except Exception`` branch. That branch previously called
``logger.exception(...)``, which formats the full traceback — including
Pydantic's ``... input_value='<raw rejected value>' ...`` tail — straight into
the application log. A tool-body-constructed model can easily be built from a
credential/token argument, so this is an SI-2 log leak distinct from (and not
covered by) the wire-response leak GH-135/RT-004 already closed.

Fix: the catch-all branch must log only ``type(exc).__name__`` (never the
exception message/traceback), mirroring the SI-2-safe pattern already used in
``contrib/commitments/executor.py``'s generic exception branch.
"""

from __future__ import annotations

import gc
import logging
from typing import Any

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.registry import ToolSet
from agent_sdk.example.agent import make_agent

_LEAKED_SECRET = "SUPERSECRET_token_abc123"

leaky_tools = ToolSet()


class _InternalModel(BaseModel):
    count: int


@leaky_tools.tool(tier=1)
async def mcp_leaky_body_tool() -> dict[str, Any]:
    """Tool takes no arguments; its BODY constructs an unrelated pydantic
    model with a bad (secret-shaped) value. Not a caller-input problem — the
    tool_call arguments (none) were always valid, so this must NOT be routed
    through ToolInputValidationError, and must fall through to the generic
    catch-all in ``_handle_tools_call``."""
    _InternalModel(count=_LEAKED_SECRET)  # non-numeric str -> ValidationError
    return {}


@pytest.fixture
def leaky_app(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    agent.toolsets = agent.toolsets + [leaky_tools]
    app = agent.build_app()
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def leaky_client(leaky_app):
    async with leaky_app.router.lifespan_context(leaky_app):
        _, token = leaky_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=leaky_app),
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


async def test_mcp_tool_body_validation_error_response_stays_generic(
    leaky_client,
) -> None:
    headers = await _mcp_init(leaky_client)
    r = await leaky_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "mcp_leaky_body_tool", "arguments": {}},
        },
        headers=headers,
    )
    assert r.status_code == 200, r.text
    assert _LEAKED_SECRET not in r.text, "SI-2 leak: rejected value echoed in wire response"
    result = r.json()["result"]
    assert result.get("isError") is True, result
    assert result["content"][0]["text"] == "tool execution failed"


async def test_mcp_tool_body_validation_error_not_logged_with_raw_value(
    leaky_client, sdk_caplog
) -> None:
    headers = await _mcp_init(leaky_client)
    with sdk_caplog("agent_sdk.routes.mcp", logging.WARNING) as records:
        r = await leaky_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "mcp_leaky_body_tool", "arguments": {}},
            },
            headers=headers,
        )
    assert r.status_code == 200, r.text

    assert records, "expected the catch-all branch to log something diagnosable"
    for record in records:
        assert _LEAKED_SECRET not in record.getMessage(), (
            f"SI-2 leak: rejected value in log message: {record.getMessage()!r}"
        )
        formatted = logging.Formatter().format(record)
        assert _LEAKED_SECRET not in formatted, (
            f"SI-2 leak: rejected value in formatted log output "
            f"(likely via logger.exception's traceback): {formatted!r}"
        )
        assert record.exc_info is None, (
            "generic branch must not use logger.exception / exc_info=True — "
            "Pydantic's ValidationError message (embedded in the traceback) "
            "carries the raw rejected value (SI-2)"
        )

    joined = " ".join(r.getMessage() for r in records)
    assert "ValidationError" in joined, (
        f"expected the exception TYPE name for diagnosability, got: {joined!r}"
    )


async def test_mcp_tool_body_validation_error_log_includes_frames_without_leaking_secret(
    leaky_client, sdk_caplog
) -> None:
    """RT-010: logging only ``type(exc).__name__`` (no ``exc_info``) made a
    genuine tool-body bug (AttributeError, KeyError, TypeError — not just this
    ValidationError case) undiagnosable in production: a bare class name with
    no file/line. The fix adds frame LOCATIONS (file:line via
    ``FrameSummary.filename``/``.lineno`` only — never ``.line``, which echoes
    source text that could itself embed a caller-derived literal) without
    reintroducing the SI-2 leak ``logger.exception``/``exc_info=True`` caused.
    """
    headers = await _mcp_init(leaky_client)
    with sdk_caplog("agent_sdk.routes.mcp", logging.ERROR) as records:
        r = await leaky_client.post(
            "/mcp",
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "mcp_leaky_body_tool", "arguments": {}},
            },
            headers=headers,
        )
    assert r.status_code == 200, r.text

    assert records, "expected the catch-all branch to log something diagnosable"
    joined = " ".join(record.getMessage() for record in records)
    assert "frames=" in joined, (
        f"expected file:line frame locations for diagnosability, got: {joined!r}"
    )
    assert __file__.rsplit("/", 1)[-1] in joined, (
        f"expected the raise site's own file:line in frames, got: {joined!r}"
    )

    for record in records:
        assert _LEAKED_SECRET not in record.getMessage(), (
            f"SI-2 leak: rejected value in log message once frames are logged: "
            f"{record.getMessage()!r}"
        )
        formatted = logging.Formatter().format(record)
        assert _LEAKED_SECRET not in formatted, (
            f"SI-2 leak: rejected value in formatted log output once frames are "
            f"logged: {formatted!r}"
        )
        assert record.exc_info is None, (
            "frames must be logged as plain file:line text, not a live "
            "traceback object via exc_info=True (SI-2)"
        )
