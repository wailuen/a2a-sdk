---
id: LRN-514
title: dumps_strict swap must keep default=str coercion
category: sdk
severity: high
source: redteam
date: 2026-10-24
---

## What happened
AG-UI TOOL_CALL_RESULT content moved from `json.dumps(..., default=str)` to bare `dumps_strict`. A dict result holding date, Decimal or UUID now reached the wire as "tool result not serializable". It worked in v0.21.0 and had no CHANGELOG notice.

## Root cause
The strict encoder rejects non-JSON native types, and the lenient coercion was dropped along with the old call.

## Check
Run a test that `{'when': date, 'amt': Decimal, 'id': UUID}` still serializes in `agent_sdk/routes/ag_ui.py`, next to the NaN test. Grep for bare `dumps_strict(value)` there and confirm it is wrapped in `to_jsonable_python(value, fallback=str)`.

## Prevention
When planning a switch to `dumps_strict`, ensure the value is first coerced with `to_jsonable_python(fallback=str)`, and add a native-type regression test.
