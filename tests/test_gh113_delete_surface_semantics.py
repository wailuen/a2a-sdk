"""GH-113: deleteSurface split-delivery semantics must be wire-discoverable
via the A2UI extension's params (DESIGN.md §5.4/§7.1).

Critical protocol-conformance fix (post-GH-113): deleteSurface is now always
delivered as its own, independently-folded message array (a separate A2A
DataPart / AG-UI A2UI_UPDATE CUSTOM event), never bundled with its surface's
create/populate messages — see agent_sdk/a2ui/translator.py::
split_a2ui_delivery(). The card's ``deleteSurfaceSemantics`` hint value
changed from the retired ``"post-paint"`` (which described bundling
deleteSurface into the same delivered array and closing the registry after
painting it) to ``"split-delivery"``. Correct rendering no longer depends on
a consumer reading this hint at all — ordinary per-array fold-then-paint
handling is sufficient — but the hint documents the delivery shape as a
courtesy.
"""

from __future__ import annotations

from agent_sdk.a2ui.catalog import a2ui_extension


def test_a2ui_extension_declares_delete_surface_semantics():
    ext = a2ui_extension()
    assert ext.params["deleteSurfaceSemantics"] == "split-delivery"


def test_a2ui_extension_declares_delete_surface_semantics_with_allowed_components():
    ext = a2ui_extension(allowed_components=["KpiCard"])
    assert ext.params["deleteSurfaceSemantics"] == "split-delivery"


async def test_agent_card_a2ui_extension_carries_delete_surface_semantics(client):
    r = await client.get("/.well-known/agent-card.json")
    card = r.json()
    a2ui_ext = next(
        e
        for e in card["capabilities"]["extensions"]
        if e["uri"] == "https://a2ui.org/a2a-extension/a2ui/v0.9.1"
    )
    assert a2ui_ext["params"]["deleteSurfaceSemantics"] == "split-delivery"
