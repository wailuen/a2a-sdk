"""Protocol conformance fix tests — wave 6 (GH #4–#8).

P6-00  GH #4 — MCP-Protocol-Version response header on initialize
P6-01  GH #5 — x-agui.customEvents flat string[] → list of {name, valueSchema}
P6-02  GH #6 — ContentModel artifacts emit only TextPart
P6-03  GH #7 — WWW-Authenticate missing resource_metadata on non-MCP routes
P6-04  GH #8 — CORS preflight missing Access-Control-Expose-Headers
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.events import ArtifactEvent
from agent_sdk.agent.runner import build_artifact
from agent_sdk.models.a2a import DataPart, TextPart
from agent_sdk.models.content_types import ContentModel


# ---------------------------------------------------------------------------
# Minimal ContentModel subclass for unit-testing build_artifact
# ---------------------------------------------------------------------------

class _SimpleCard(ContentModel):
    """Minimal concrete ContentModel for testing.

    Uses a domain-specific catalog_id (non-standard catalog).  Domain types
    are emitted freely whenever tier is active — only tier="none" suppresses
    them (GH-56).  Standard catalog core types are never gated off by
    capabilities alone.
    """

    data_type: ClassVar[str] = "_test_simple_card_w6"
    component: ClassVar[str] = "TestSimpleCardW6"
    catalog_id: ClassVar[str] = "urn:test-sdk-w6:v1"  # domain catalog — emitted freely when tier active; only tier="none" suppresses
    value: str = "test"

    def to_plain_text(self) -> str:
        return f"SimpleCard: {self.value}"


# tier="none" gates off A2UI for ALL types (including domain types).
_CAPS_A2UI_OFF = A2uiCapabilities(tier="none")
# tier="core" → A2UI active; domain types are emitted freely (catalog list vestigial in allows()).
_CAPS_A2UI_ON = A2uiCapabilities(tier="core", catalogs=["urn:test-sdk-w6:v1"])


# ---------------------------------------------------------------------------
# P6-00: MCP-Protocol-Version response header on initialize (GH #4)
# ---------------------------------------------------------------------------


async def test_mcp_initialize_no_version_header_echoes_negotiated(client):
    """POST /mcp initialize with no MCP-Protocol-Version request header.

    The response MUST carry Mcp-Protocol-Version set to the version negotiated
    in the body, NOT the server fallback default (2025-03-26).
    """
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"},
            },
        },
        # Deliberately omit MCP-Protocol-Version request header.
    )
    assert r.status_code == 200, r.text
    # Body must contain the negotiated version.
    body = r.json()
    assert body["result"]["protocolVersion"] == "2025-06-18"
    # Response header must reflect the same negotiated version (P6-00).
    assert r.headers.get("mcp-protocol-version") == "2025-06-18", (
        f"Expected mcp-protocol-version: 2025-06-18, got: {r.headers.get('mcp-protocol-version')}"
    )


async def test_mcp_initialize_version_header_present_echoed(client):
    """When the client sends MCP-Protocol-Version on initialize, the response
    header must echo the same negotiated version."""
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "t", "version": "1"},
            },
        },
        headers={"MCP-Protocol-Version": "2025-06-18"},
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("mcp-protocol-version") == "2025-06-18"


# ---------------------------------------------------------------------------
# P6-01: x-agui.customEvents objects (GH #5)
# ---------------------------------------------------------------------------


async def test_agent_card_custom_events_are_objects(client):
    """x-agui.customEvents must be a list of dicts with 'name' and
    'valueSchema' keys, not flat strings."""
    r = await client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    card = r.json()

    custom_events = card["x-agui"]["customEvents"]
    assert isinstance(custom_events, list), "customEvents must be a list"
    assert len(custom_events) == 5, f"expected 5 custom events, got {len(custom_events)}"

    for evt in custom_events:
        assert isinstance(evt, dict), f"each event must be a dict, got {type(evt)}: {evt!r}"
        assert "name" in evt, f"event missing 'name': {evt!r}"
        assert "valueSchema" in evt, f"event missing 'valueSchema': {evt!r}"
        assert isinstance(evt["valueSchema"], dict), (
            f"valueSchema must be a dict: {evt['valueSchema']!r}"
        )

    names = {e["name"] for e in custom_events}
    assert names == {
        "AGENT_ARTIFACT", "A2UI_UPDATE", "AGENT_PROGRESS", "AGENT_NOTE", "TOOL_PROGRESS",
    }


# ---------------------------------------------------------------------------
# P6-02: ContentModel artifacts emit DataPart even without A2UI (GH #6)
# ---------------------------------------------------------------------------


def _make_event(model: ContentModel) -> ArtifactEvent:
    return ArtifactEvent(
        data_type=model.data_type,
        tool_name="test_tool",
        model=model,
    )


def test_build_artifact_content_model_no_a2ui_emits_two_parts():
    """When A2UI is NOT active (tier='none' gates all types out), build_artifact
    must still emit 2 parts: TextPart + DataPart with the raw model dump.

    P6-02 / A2A §D3 fix: plain A2A clients deserve the structured payload.
    """
    card = _SimpleCard(value="hello")
    # Confirm the gate is actually closed for our test card (tier="none").
    assert not _CAPS_A2UI_OFF.allows(_SimpleCard), "precondition: A2UI must be gated off"

    artifact = build_artifact(_make_event(card), _CAPS_A2UI_OFF)
    parts = artifact.parts
    assert len(parts) == 2, f"expected 2 parts, got {len(parts)}: {parts}"

    text_part, data_part = parts
    assert isinstance(text_part, TextPart), f"first part must be TextPart, got {type(text_part)}"
    assert isinstance(data_part, DataPart), f"second part must be DataPart, got {type(data_part)}"

    # DataPart.data must contain the model dump (structured payload).
    assert isinstance(data_part.data, dict), f"DataPart.data must be dict: {data_part.data!r}"
    assert "value" in data_part.data, f"model dump missing 'value': {data_part.data!r}"
    assert data_part.data["value"] == "hello"

    # Metadata must carry data_type and tool_name.
    meta = data_part.metadata or {}
    assert meta.get("data_type") == "_test_simple_card_w6"
    assert meta.get("tool_name") == "test_tool"


def test_build_artifact_content_model_with_a2ui_emits_a2ui_data_part():
    """When A2UI is active, build_artifact emits TextPart + one A2UI DataPart
    (open only; no close DataPart, GH-214 ruling
    https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762)."""
    card = _SimpleCard(value="world")
    assert _CAPS_A2UI_ON.allows(_SimpleCard), "precondition: A2UI must be active"

    artifact = build_artifact(_make_event(card), _CAPS_A2UI_ON)
    parts = artifact.parts
    assert len(parts) == 2, f"expected 2 parts, got {len(parts)}: {parts}"

    text_part, open_part = parts
    assert isinstance(text_part, TextPart)
    assert isinstance(open_part, DataPart)

    # A2UI DataPart carries the message array wrapped in an object under
    # "messages" — matching the AG-UI CUSTOM value convention (GH-128).
    assert isinstance(open_part.data, dict)
    assert isinstance(open_part.data["messages"], list)
    assert (open_part.metadata or {}).get("mimeType") == "application/a2ui+json"
    assert all("deleteSurface" not in m for m in open_part.data["messages"])


# ---------------------------------------------------------------------------
# P6-03: WWW-Authenticate resource_metadata on non-MCP routes (GH #7)
# ---------------------------------------------------------------------------


async def test_protected_non_mcp_route_returns_resource_metadata_challenge(client):
    """A 401 from a non-MCP protected route must carry
    WWW-Authenticate: Bearer resource_metadata="..." (not Bearer realm=)."""
    # Use the A2A send endpoint without auth — strip the Authorization header.
    r = await client.post(
        "/v1/message:send",
        json={
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "hello"}],
                "messageId": "test-msg-1",
            }
        },
        headers={"Authorization": ""},
    )
    assert r.status_code == 401, f"expected 401, got {r.status_code}"
    www_auth = r.headers.get("www-authenticate", "")
    assert www_auth.startswith("Bearer resource_metadata="), (
        f"expected 'Bearer resource_metadata=...', got: {www_auth!r}"
    )


async def test_mcp_route_still_returns_resource_metadata_challenge(client):
    """The /mcp route must also still return resource_metadata (regression check)."""
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": ""},
    )
    assert r.status_code == 401
    www_auth = r.headers.get("www-authenticate", "")
    assert "resource_metadata=" in www_auth, (
        f"/mcp must carry resource_metadata, got: {www_auth!r}"
    )


# ---------------------------------------------------------------------------
# P6-04: CORS preflight Access-Control-Expose-Headers (GH #8)
# ---------------------------------------------------------------------------


async def test_cors_preflight_includes_expose_headers(client):
    """OPTIONS preflight with a known origin must include
    Access-Control-Expose-Headers in the 204 response."""
    r = await client.options(
        "/mcp",
        headers={
            "Origin": "https://claude.ai",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.status_code == 204, f"expected 204, got {r.status_code}"
    expose = r.headers.get("access-control-expose-headers", "")
    assert expose, "access-control-expose-headers must be present in preflight response"
    # Must include at minimum WWW-Authenticate so OAuth discovery can start.
    assert "WWW-Authenticate" in expose, (
        f"access-control-expose-headers must include WWW-Authenticate: {expose!r}"
    )


async def test_cors_preflight_unknown_origin_no_expose_headers(client):
    """Preflight from an unknown origin must NOT include CORS headers."""
    r = await client.options(
        "/mcp",
        headers={
            "Origin": "https://evil.example.com",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.status_code == 204
    assert not r.headers.get("access-control-allow-origin"), (
        "unknown origin must not receive access-control-allow-origin"
    )
    assert not r.headers.get("access-control-expose-headers"), (
        "unknown origin must not receive access-control-expose-headers"
    )
