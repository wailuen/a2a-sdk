"""GH-113: deleteSurface post-paint semantics must be wire-discoverable via
the A2UI extension's params (DESIGN.md §5.4/§7.1), not only documented in a
project-local convention (console/static/a2ui.js)."""

from __future__ import annotations

from agent_sdk.a2ui.catalog import a2ui_extension


def test_a2ui_extension_declares_delete_surface_semantics():
    ext = a2ui_extension()
    assert ext.params["deleteSurfaceSemantics"] == "post-paint"


def test_a2ui_extension_declares_delete_surface_semantics_with_allowed_components():
    ext = a2ui_extension(allowed_components=["KpiCard"])
    assert ext.params["deleteSurfaceSemantics"] == "post-paint"


async def test_agent_card_a2ui_extension_carries_delete_surface_semantics(client):
    r = await client.get("/.well-known/agent-card.json")
    card = r.json()
    a2ui_ext = next(
        e
        for e in card["capabilities"]["extensions"]
        if e["uri"] == "https://a2ui.org/a2a-extension/a2ui/v0.9.1"
    )
    assert a2ui_ext["params"]["deleteSurfaceSemantics"] == "post-paint"
