---
id: LRN-296
title: Bare catch-all on model call hides seam contract breaks
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
`_final_summary` in loop.py used a bare `except Exception:` with no binding and no log. A new `tool_choice` keyword on the public ModelClient Protocol makes any 0.9.0-era custom client raise TypeError. The error was swallowed, so capped runs silently got the fixed notice, and CHANGELOG did not warn client authors.

## Root cause
Silent fallback on a model call path, plus a Protocol signature change shipped without a migration note.

## Check
Verify no bare catch-all on model or tool call paths: `grep -n "except Exception:" agent_sdk/agent/loop.py` returns none. Verify a test asserts the log names the exception type and holds no exception text (SI-2, C-007), and CHANGELOG mentions `tool_choice`.

## Prevention
When planning, require every catch-all on a model or tool call path to bind the exception and log type(exc).__name__ plus frame_locations, never str(exc). A new Protocol keyword needs a CHANGELOG note for custom implementers.
