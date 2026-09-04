---
id: LRN-236
title: Landed C-NNN component leaves inline duplicate + stale registry status
category: sdk
severity: high
source: redteam
date: 2026-09-03
---

## What happened
Registered component C-007 (`sanitize_text`,
`agent_sdk/common/redact.py`) landed and is used by
`content_types.py`, but `agent_sdk/agent/loop.py` still carries a
byte-identical private copy (`_CONTROL_CHAR_MAP` +
`_sanitize_model_name`) at two call sites.
`workspace/components/README.md` still marks C-007 `planned` and
claims the pattern is "currently inline at loop.py" — both false.

## Root cause
Landing a planned component omitted a sweep to delete inline copies
and flip the registry row to `present`.

## Check
grep `agent_sdk/agent/loop.py` for `_CONTROL_CHAR_MAP` or
`_sanitize_model_name` — must be no match. grep
`workspace/components/README.md` for `C-007` — its row must read
`present`, not `planned`.

## Prevention
When planning a wave that lands a previously-`planned` C-NNN
component, add a todo to grep for pre-existing inline copies of that
pattern, delete them, redirect call sites, and flip the registry row
to `present` in the same wave — never leave "currently inline" prose
standing after landing.
