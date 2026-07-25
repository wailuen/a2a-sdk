"""RT-001 (LRN-134 follow-up): the A2UI-over-A2A DataPart wraps the A2UI
message array as ``{"messages": [...]}`` (GH-128, agent_sdk/agent/runner.py::
build_artifact()) to satisfy A2A v0.3.0's DataPart.data object typing — a
deliberate deviation from A2UI v0.9.1's own A2A binding, which mandates a
bare array at ``data``. That deviation must be wire-discoverable via a
non-normative agent-card hint, mirroring the ``deleteSurfaceSemantics``
precedent (GH-113), so a strictly spec-conformant third-party A2UI Path-A
renderer has a documented way to learn the wrapper exists rather than
silently rendering nothing.
"""

from __future__ import annotations

from agent_sdk.a2ui.catalog import a2ui_extension


def test_a2ui_extension_declares_data_encoding_hint():
    ext = a2ui_extension()
    assert ext.params["dataEncoding"] == "data.messages"


def test_a2ui_extension_declares_data_encoding_hint_with_allowed_components():
    ext = a2ui_extension(allowed_components=["KpiCard"])
    assert ext.params["dataEncoding"] == "data.messages"


async def test_agent_card_a2ui_extension_carries_data_encoding_hint(client):
    r = await client.get("/.well-known/agent-card.json")
    card = r.json()
    a2ui_ext = next(
        e
        for e in card["capabilities"]["extensions"]
        if e["uri"] == "https://a2ui.org/a2a-extension/a2ui/v0.9.1"
    )
    assert a2ui_ext["params"]["dataEncoding"] == "data.messages"
