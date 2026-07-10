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

## Check

```
python3 -c "
import re
from pathlib import Path
src = Path('agent_sdk/routes/ag_ui.py').read_text()
names = re.findall(r'self\._custom\(\s*([^,]+?),', src, re.DOTALL)
print(sorted(n.strip().strip(chr(34)) for n in names))
"
```

(a plain single-line `grep 'self\._custom(\s*"[A-Z0-9_]+"'` under-matches — several call sites split the name onto the next line, e.g. `self._custom(\n    "TOOL_PROGRESS",` — so the extraction must span lines the way the regex above and the pytest regex below do.)

Every name this prints must appear in all four canonical locations:

1. `CUSTOM_EVENTS` tuple — `agent_sdk/routes/agent_card.py`
2. `_CUSTOM_EVENT_SCHEMAS` list (the `name` field of each entry) — same file
3. The frozen contract table under `### 5.3 AG-UI` in `DESIGN.md`
4. The `handleCustom()` routing table (`name === "<NAME>"` branches) in `agent_sdk/console/static/chat.js`

This is machine-runnable end-to-end via the existing regression test, which must pass:

```
.venv/bin/pytest -q tests/test_card_console.py::test_custom_events_match_actually_emitted_events tests/test_card_console.py::test_custom_events_match_console_routing_table tests/test_card_console.py::test_card_shape
```

`test_custom_events_match_actually_emitted_events` extracts every `self._custom(` call-site name in `ag_ui.py` (rejecting non-literal arguments so the extraction itself can't be evaded) and asserts the set equals `CUSTOM_EVENTS`; `test_custom_events_match_console_routing_table` asserts every `CUSTOM_EVENTS` name has a live `handleCustom()` branch in `chat.js`; `test_card_shape` asserts the served agent card's `x-agui.customEvents` names equal `CUSTOM_EVENTS` (which is sourced from `_CUSTOM_EVENT_SCHEMAS`). The `DESIGN.md` §5.3 table has no automated check — cross-check it by hand against the grep output above whenever any of the three tests' name sets change.
