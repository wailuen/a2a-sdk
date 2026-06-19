"""GH #76 — A2UI_UPDATE messages array must declare items schema.

JSON Schema without an ``items`` key leaves the array element type
undeclared; schema-validating AG-UI consumers cannot verify payload
structure.  The fix adds ``"items": {"type": "object"}`` to the
``messages`` property of the ``A2UI_UPDATE`` custom event schema.
"""

from __future__ import annotations

from agent_sdk.routes.agent_card import _CUSTOM_EVENT_SCHEMAS


def test_a2ui_update_messages_items_type():
    a2ui = next(e for e in _CUSTOM_EVENT_SCHEMAS if e["name"] == "A2UI_UPDATE")
    messages_schema = a2ui["valueSchema"]["properties"]["messages"]
    assert messages_schema.get("items", {}).get("type") == "object", (
        "A2UI_UPDATE messages must declare items.type == 'object'"
    )
