"""GH-47: MCP tool inputSchema always includes required + additionalProperties.

Four cases:
  1. No input_model → both fields present with empty/False defaults.
  2. Pydantic model with only Optional fields → both fields present, required=[].
  3. Pydantic model with a required str field → required contains the field,
     additionalProperties is False.
  4. Integration: /mcp tools/list — every tool inputSchema has both fields.
"""

from __future__ import annotations

from typing import Optional

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.registry import ToolDecl, ToolEntry, ToolSet


# ---------------------------------------------------------------------------
# Unit helpers
# ---------------------------------------------------------------------------


def _entry_no_model() -> ToolEntry:
    """ToolEntry whose ToolDecl has no input_model."""

    async def _fn() -> None:
        """no-op"""

    decl = ToolDecl(
        fn=_fn,
        name="no_model_tool",
        description="no-op",
        tier=1,
        emits=None,
        sample=None,
        input_model=None,
        adapter_params={},
    )
    return ToolEntry(decl=decl)


def _entry_with_model(model: type[BaseModel]) -> ToolEntry:
    async def _fn(inp: model) -> None:  # type: ignore[valid-type]
        """no-op"""

    decl = ToolDecl(
        fn=_fn,
        name="model_tool",
        description="no-op",
        tier=1,
        emits=None,
        sample=None,
        input_model=model,
        adapter_params={},
    )
    return ToolEntry(decl=decl)


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


def test_no_model_schema_has_required_and_closed() -> None:
    schema = _entry_no_model().input_schema()
    assert schema["required"] == []
    assert schema["additionalProperties"] is False


def test_all_optional_model_has_both_fields() -> None:
    class AllOptional(BaseModel):
        name: Optional[str] = None
        count: Optional[int] = None

    schema = _entry_with_model(AllOptional).input_schema()
    assert "required" in schema
    assert schema["required"] == []
    assert schema["additionalProperties"] is False


def test_required_field_preserved() -> None:
    class HasRequired(BaseModel):
        entity_id: str
        label: Optional[str] = None

    schema = _entry_with_model(HasRequired).input_schema()
    assert "entity_id" in schema["required"]
    assert schema["additionalProperties"] is False


# ---------------------------------------------------------------------------
# Integration: /mcp tools/list
# ---------------------------------------------------------------------------


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


async def test_mcp_tools_list_has_closed_schemas(client: httpx.AsyncClient) -> None:
    """Every tool returned by tools/list must have required and additionalProperties."""
    headers = await _mcp_init(client)
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    tools = r.json()["result"]["tools"]
    assert tools, "expected at least one tool"
    for tool in tools:
        schema = tool["inputSchema"]
        assert "required" in schema, f"tool {tool['name']!r} inputSchema missing 'required'"
        assert "additionalProperties" in schema, (
            f"tool {tool['name']!r} inputSchema missing 'additionalProperties'"
        )
        assert schema["additionalProperties"] is False, (
            f"tool {tool['name']!r} additionalProperties must be False"
        )
