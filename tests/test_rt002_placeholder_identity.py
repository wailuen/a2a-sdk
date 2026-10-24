"""RT-002 — Placeholder identity normalization across protocol surfaces.

In DEV_MODE, AGENT_NAME=placeholder ('agent') must NOT appear verbatim in
MCP serverInfo.name/title or the health 'agent' field.  All three surfaces
must emit the same neutral sentinel rather than the raw placeholder value,
matching the normalization already applied to the agent card description.

AC:
  1. settings.display_name returns a neutral value when agent_name is the
     placeholder ('agent') or blank.
  2. MCP initialize serverInfo.name does not expose the raw placeholder.
  3. MCP initialize serverInfo.title (2025-11-25+) does not expose the raw
     placeholder.
  4. GET /health 'agent' field does not expose the raw placeholder.
  5. GET /openapi.json 'info.title' does not expose the raw placeholder.
"""

from __future__ import annotations

import gc
from typing import AsyncIterator

import httpx
import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.config import PLACEHOLDER_AGENT_NAME
from agent_sdk.example.agent import make_agent


# ---------------------------------------------------------------------------
# Fixture: app and client with AGENT_NAME left at the placeholder default
# ---------------------------------------------------------------------------


@pytest.fixture
def placeholder_settings(tmp_path) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        # AGENT_NAME deliberately omitted — stays at the placeholder default
    )


@pytest.fixture
def placeholder_app(placeholder_settings):
    from agent_sdk.testing import FakeModelClient

    built = make_agent(placeholder_settings, model_client=FakeModelClient()).build_app()
    yield built
    built.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def placeholder_client(placeholder_app) -> AsyncIterator[httpx.AsyncClient]:
    async with placeholder_app.router.lifespan_context(placeholder_app):
        _, token = placeholder_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=placeholder_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            yield c


# ---------------------------------------------------------------------------
# AC-1: settings.display_name normalizes the placeholder
# ---------------------------------------------------------------------------


def test_display_name_normalizes_placeholder(placeholder_settings) -> None:
    """display_name must NOT return the raw placeholder string."""
    assert placeholder_settings.agent_name == PLACEHOLDER_AGENT_NAME
    assert placeholder_settings.display_name != PLACEHOLDER_AGENT_NAME, (
        f"display_name must not expose the raw placeholder {PLACEHOLDER_AGENT_NAME!r}; "
        f"got {placeholder_settings.display_name!r}"
    )
    assert isinstance(placeholder_settings.display_name, str)
    assert placeholder_settings.display_name.strip(), "display_name must not be blank"


def test_display_name_normalizes_blank() -> None:
    """display_name must NOT return blank when agent_name is blank/whitespace."""
    s = BaseAgentSettings(DEV_MODE=True, AGENT_NAME="  ")
    assert s.display_name.strip(), "display_name must not be blank when agent_name is whitespace"
    assert s.display_name != "  "


def test_display_name_passes_through_real_name() -> None:
    """display_name must return the configured name unchanged for non-placeholder values."""
    s = BaseAgentSettings(DEV_MODE=True, AGENT_NAME="my-awesome-agent")
    assert s.display_name == "my-awesome-agent"


# ---------------------------------------------------------------------------
# AC-1b: settings.is_placeholder_name — single source of truth for predicate
# ---------------------------------------------------------------------------


def test_is_placeholder_name_true_for_placeholder(placeholder_settings) -> None:
    """is_placeholder_name must be True when agent_name equals the placeholder constant."""
    assert placeholder_settings.agent_name == PLACEHOLDER_AGENT_NAME
    assert placeholder_settings.is_placeholder_name is True


def test_is_placeholder_name_true_for_blank() -> None:
    """is_placeholder_name must be True when agent_name is blank/whitespace."""
    s = BaseAgentSettings(DEV_MODE=True, AGENT_NAME="   ")
    assert s.is_placeholder_name is True


def test_is_placeholder_name_true_for_empty() -> None:
    """is_placeholder_name must be True when agent_name is empty string."""
    s = BaseAgentSettings(DEV_MODE=True, AGENT_NAME="")
    assert s.is_placeholder_name is True


def test_is_placeholder_name_false_for_real_name() -> None:
    """is_placeholder_name must be False for a real agent name."""
    s = BaseAgentSettings(DEV_MODE=True, AGENT_NAME="my-awesome-agent")
    assert s.is_placeholder_name is False


def test_is_placeholder_name_false_for_placeholder_substring() -> None:
    """is_placeholder_name must be False when agent_name merely contains the placeholder."""
    s = BaseAgentSettings(DEV_MODE=True, AGENT_NAME="my-agent-service")
    assert s.is_placeholder_name is False


def test_display_name_delegates_to_is_placeholder_name() -> None:
    """display_name and is_placeholder_name must agree: if predicate is True, display_name differs from agent_name."""
    for name in [PLACEHOLDER_AGENT_NAME, "", "  "]:
        s = BaseAgentSettings(DEV_MODE=True, AGENT_NAME=name)
        assert s.is_placeholder_name is True
        assert s.display_name != name.strip() or (name.strip() == "" and s.display_name.strip())


# ---------------------------------------------------------------------------
# AC-2: MCP serverInfo.name must not expose the raw placeholder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_serverinfo_name_not_placeholder(
    placeholder_client: httpx.AsyncClient,
) -> None:
    """MCP initialize serverInfo.name must not be the raw placeholder string."""
    r = await placeholder_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
        headers={"MCP-Protocol-Version": "2025-06-18"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    server_info = body["result"]["serverInfo"]
    assert server_info["name"] != PLACEHOLDER_AGENT_NAME, (
        f"serverInfo.name must not expose the raw placeholder; got {server_info['name']!r}"
    )
    assert server_info["name"].strip(), "serverInfo.name must not be blank"


# ---------------------------------------------------------------------------
# AC-3: MCP serverInfo.title (2025-11-25) must not expose the raw placeholder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mcp_serverinfo_title_not_placeholder(
    placeholder_client: httpx.AsyncClient,
) -> None:
    """MCP initialize serverInfo.title (2025-11-25+) must not be the raw placeholder."""
    r = await placeholder_client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-11-25", "capabilities": {}},
        },
        headers={"MCP-Protocol-Version": "2025-11-25"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    server_info = body["result"]["serverInfo"]
    assert "title" in server_info, "serverInfo.title must be present for 2025-11-25"
    assert server_info["title"] != PLACEHOLDER_AGENT_NAME, (
        f"serverInfo.title must not expose the raw placeholder; got {server_info['title']!r}"
    )
    assert server_info["title"].strip(), "serverInfo.title must not be blank"


# ---------------------------------------------------------------------------
# AC-4: GET /health 'agent' field must not expose the raw placeholder
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_health_agent_not_placeholder(
    placeholder_client: httpx.AsyncClient,
) -> None:
    """GET /health 'agent' field must not be the raw placeholder string."""
    r = await placeholder_client.get("/health")
    assert r.status_code == 200, r.text
    payload = r.json()
    assert payload["agent"] != PLACEHOLDER_AGENT_NAME, (
        f"/health 'agent' must not expose the raw placeholder; got {payload['agent']!r}"
    )
    assert payload["agent"].strip(), "/health 'agent' must not be blank"


# ---------------------------------------------------------------------------
# AC-5: served agent card 'name' (A2A REQUIRED identity field) must not expose
#       the raw placeholder — RT-001
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_agent_card_name_not_placeholder(
    placeholder_client: httpx.AsyncClient,
) -> None:
    """GET /.well-known/agent-card.json 'name' must not be the raw placeholder.

    The card name is the primary A2A identity surface (downstream registries key
    on it); it must be normalized via display_name identically to MCP serverInfo
    and /health, not left as the raw AGENT_NAME placeholder.
    """
    r = await placeholder_client.get("/.well-known/agent-card.json")
    assert r.status_code == 200, r.text
    card = r.json()
    assert card["name"] != PLACEHOLDER_AGENT_NAME, (
        f"card 'name' must not expose the raw placeholder; got {card['name']!r}"
    )
    assert card["name"].strip(), "card 'name' must not be blank"


# ---------------------------------------------------------------------------
# AC-6: OpenAPI schema 'info.title' must not expose the raw placeholder
# ---------------------------------------------------------------------------


def test_openapi_title_not_placeholder(placeholder_app) -> None:
    """The OpenAPI info.title must not be the raw placeholder string.

    Checked via app.openapi() directly: /openapi.json is only served in DEV_MODE
    (GH-231), but the schema must still carry the normalized display_name.
    """
    title = placeholder_app.openapi()["info"]["title"]
    assert title != PLACEHOLDER_AGENT_NAME, (
        f"openapi info.title must not expose the raw placeholder; got {title!r}"
    )
    assert title.strip(), "openapi info.title must not be blank"


# ---------------------------------------------------------------------------
# AC-7: card 'description' fallback must be consistent with 'name' (RT-006)
# ---------------------------------------------------------------------------


def test_card_description_consistent_with_name(tmp_path) -> None:
    """When AGENT_NAME has surrounding whitespace and no description is set,
    card 'description' must be derived from display_name (stripped), not the
    raw AGENT_NAME — so name and description stay consistent (RT-006).
    """
    from agent_sdk.agent.registry import ToolRegistry
    from agent_sdk.routes.agent_card import build_agent_card

    s = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="  My Agent  ",
    )
    card = build_agent_card(s, ToolRegistry([], {}))
    assert card["name"] == s.display_name, (
        f"card name must equal display_name; got {card['name']!r}"
    )
    assert card["description"] == s.display_name, (
        f"card description must equal display_name when no explicit description is set; "
        f"got {card['description']!r}, expected {s.display_name!r}"
    )
    assert card["name"] == card["description"], (
        f"card name and description must be consistent; "
        f"name={card['name']!r}, description={card['description']!r}"
    )


# ---------------------------------------------------------------------------
# RT-004: whitespace-only AGENT_DESCRIPTION must not be emitted verbatim
# ---------------------------------------------------------------------------


def test_card_description_whitespace_only_collapses_to_fallback(tmp_path) -> None:
    """A whitespace-only AGENT_DESCRIPTION must not be emitted verbatim.

    '  ' is truthy in Python, so the old check `not settings.agent_description`
    was False and the raw whitespace was written into the card description.
    The fix must strip before the truthiness test so whitespace-only collapses
    to the display_name fallback, consistently with the placeholder/blank path.
    """
    from agent_sdk.agent.registry import ToolRegistry
    from agent_sdk.routes.agent_card import build_agent_card

    s = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="My Agent",
        AGENT_DESCRIPTION="   ",
    )
    card = build_agent_card(s, ToolRegistry([], {}))
    assert card["description"].strip(), (
        f"card description must not be blank/whitespace; got {card['description']!r}"
    )
    assert card["description"] == s.display_name, (
        f"whitespace-only AGENT_DESCRIPTION must fall back to display_name; "
        f"got {card['description']!r}, expected {s.display_name!r}"
    )
