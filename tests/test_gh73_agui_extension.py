"""GH#73 — build_agent_card() must include urn:agui:run:v1 in capabilities.extensions."""

from __future__ import annotations

from agent_sdk import BaseAgentSettings
from agent_sdk.routes.agent_card import build_agent_card


async def test_agui_run_extension_in_build_agent_card(app):
    """build_agent_card() must include urn:agui:run:v1 in capabilities.extensions."""
    card = app.state.agent_card
    ext_uris = [e["uri"] for e in card["capabilities"]["extensions"]]
    assert "urn:agui:run:v1" in ext_uris, (
        f"urn:agui:run:v1 must appear in capabilities.extensions; got {ext_uris}"
    )


async def test_agui_run_extension_in_live_card(client):
    """The served card must include urn:agui:run:v1 in capabilities.extensions."""
    r = await client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    card = r.json()
    ext_uris = [e["uri"] for e in card["capabilities"]["extensions"]]
    assert "urn:agui:run:v1" in ext_uris, (
        f"urn:agui:run:v1 must appear in capabilities.extensions; got {ext_uris}"
    )
