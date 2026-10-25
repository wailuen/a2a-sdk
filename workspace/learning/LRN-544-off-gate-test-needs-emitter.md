---
id: LRN-544
title: Off-gate tests must use an emitting tool
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
`test_ag_ui_off_drops_forwarded_caps` and `test_card_state_and_runtime_agree[False]` drove the `plain` tool, which returns a dict and never emits A2UI. With the AG-UI gate patched to always pass, the route test still passed.

## Root cause
The tool could not produce the output the gate suppresses, so the assertion was vacuous.

## Check
Mutation: force `a2ui_enabled=True` at the route call site; `pytest tests/test_gh257_single_a2ui_gate.py` must fail on the off-gate route tests.

## Prevention
When planning a gate-off test, require a tool whose result carries A2UI with the gate on (e.g. `demo_kpis`) and an assertion of no A2UI_UPDATE frame or part.
