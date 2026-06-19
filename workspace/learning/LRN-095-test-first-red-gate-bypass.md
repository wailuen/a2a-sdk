---
id: LRN-087
title: Test-first test shipped RED — wave archived without passing its own AC
category: testing
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
GH-76 required an A2UI_UPDATE custom-event schema fix; a test-first test (`tests/test_gh76_a2ui_update_items.py`) was landed and the wave was archived, but the corresponding code change in `agent_sdk/routes/agent_card.py` `_CUSTOM_EVENT_SCHEMAS` was never applied. The full suite reported 1 failed, 767 passed at archive time, meaning the wave closed with a RED acceptance criterion.

## Root cause
The zero-tolerance gate ran only the new-feature happy-path tests rather than the full suite before archiving. A test-first test that is RED by design before the fix is indistinguishable from a failing regression unless the gate explicitly verifies all tests pass after the fix is applied.

## Check
Run `pytest tests/test_gh76_a2ui_update_items.py -v` and confirm GREEN. Also verify: `grep -n '"messages"' agent_sdk/routes/agent_card.py` shows `"items": {"type": "object"}` alongside `"type": "array"` in the A2UI_UPDATE schema block.

## Prevention
When planning any wave that lands a test-first test, ensure the zero-tolerance gate runs the full suite (`pytest`) — not just the new-feature subset — and blocks archiving on any failure. A wave must not be marked complete while `pytest` reports any failed test, regardless of whether the failure predates the wave.
