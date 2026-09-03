---
id: LRN-141
title: Reuses:C-NNN annotation treated as behavior match instead of landing-location binding
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
A todo carried `Reuses: C-007`, instructing the neutralisation helper to land in `agent_sdk/common/redact.py` alongside C-008/C-009. Instead `_sanitize_cell` was implemented locally in `agent_sdk/models/content_types.py:60` — a third divergent copy of logic `loop.py:392` already inlines a second copy of — and the new docstring tells external subclass authors to call this module-private, non-exported symbol.

## Root cause
The implementer read `Reuses: C-007` as "produce equivalent behavior" rather than "call the registered component from its registered home module."

## Check
`grep -rn "dict.fromkeys(range(0x20)" agent_sdk/` must match only `agent_sdk/common/redact.py`; confirm `content_types.py` imports `safe_error_text` from `agent_sdk.common.redact` and defines no local sanitizer.

## Prevention
When a todo carries `Reuses: C-NNN`, the planner must pin the landing module to the C-NNN registry's home path; redteam must verify the consuming module imports the symbol rather than redefining it.
