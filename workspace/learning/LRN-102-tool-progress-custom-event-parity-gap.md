---
id: LRN-102
category: testing
severity: high
summary: TOOL_PROGRESS CUSTOM event emitted in ag_ui.py but absent from CUSTOM_EVENTS tuple, card schema, DESIGN.md contract table, and console router — parity guard silent because both sides missing
prevention: When adding any new CUSTOM event name to ag_ui.py, update CUSTOM_EVENTS tuple, _CUSTOM_EVENT_SCHEMAS list, DESIGN.md §5.3 table, and console handleCustom() router atomically in the same commit; CI must grep for _custom() call-sites and assert every name appears in CUSTOM_EVENTS.
---

## What happened

During wave w025 red-team, RT-AG-001 found that `TOOL_PROGRESS` is emitted as a CUSTOM AG-UI event in `agent_sdk/routes/ag_ui.py` (line 259, introduced for GH-88 async-generator tool support) but was never registered in any of the four canonical locations that the frozen §5.3 contract requires:

1. `CUSTOM_EVENTS` tuple in `agent_sdk/routes/agent_card.py` (line 32)
2. `_CUSTOM_EVENT_SCHEMAS` list in the same file (which drives the card's `x-agui.customEvents` field)
3. The `DESIGN.md §5.3` frozen contract table
4. The console chat.js `handleCustom()` routing table

## Root cause

The GH-88 change added `ToolProgressEvent` handling and the `_custom("TOOL_PROGRESS", ...)` emission path in ag_ui.py without updating the four parity anchors. The existing parity guard test (`test_card_console.py::test_custom_events_match_console_routing_table`) did not catch this because it asserts that the `CUSTOM_EVENTS` tuple equals the console routing table — both sets were missing `TOOL_PROGRESS`, so the assert passed with a false-green result. The guard is a same-size equality check, not an exhaustive scan of `_custom()` call-sites.

## Fix applied

`TOOL_PROGRESS` must be added to:
- `CUSTOM_EVENTS` tuple (agent_card.py line 32)
- `_CUSTOM_EVENT_SCHEMAS` list with appropriate `valueSchema` (`{message: string, toolName: string}`)
- `DESIGN.md §5.3` frozen contract table row
- `handleCustom()` console routing table entry

The parity guard test must additionally verify that every name passed to `self._custom()` in ag_ui.py appears in `CUSTOM_EVENTS`, so that future additions cannot silently diverge again.
