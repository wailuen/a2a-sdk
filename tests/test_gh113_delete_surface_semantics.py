"""GH-113 / GH-214: the deleteSurfaceSemantics agent-card param is removed.

GH-113 added params.deleteSurfaceSemantics: "split-delivery" to describe the
open/close split delivery. GH-214 (https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762)
removed the close message entirely, so the hint has nothing left to describe
and is gone. dataEncoding and the other A2UI params stay.
"""

from __future__ import annotations

from agent_sdk.a2ui.catalog import a2ui_extension


def test_a2ui_extension_has_no_delete_surface_semantics():
    ext = a2ui_extension()
    assert "deleteSurfaceSemantics" not in ext.params
    assert ext.params["dataEncoding"] == "data.messages"


def test_a2ui_extension_has_no_delete_surface_semantics_with_allowed_components():
    ext = a2ui_extension(allowed_components=["KpiCard"])
    assert "deleteSurfaceSemantics" not in ext.params
    assert "supportedCatalogIds" in ext.params


async def test_agent_card_a2ui_extension_has_no_delete_surface_semantics(client):
    r = await client.get("/.well-known/agent-card.json")
    card = r.json()
    a2ui_ext = next(
        e
        for e in card["capabilities"]["extensions"]
        if e["uri"] == "https://a2ui.org/a2a-extension/a2ui/v0.9.1"
    )
    assert "deleteSurfaceSemantics" not in a2ui_ext["params"]
    assert a2ui_ext["params"]["dataEncoding"] == "data.messages"
