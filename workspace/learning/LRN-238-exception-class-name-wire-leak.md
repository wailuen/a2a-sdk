---
id: LRN-238
title: Exception class name interpolated into wire-facing tool error text
category: security
severity: critical
source: redteam
date: 2026-09-03
---

## What happened
Three `except Exception` handlers in `agent_sdk/agent/loop.py`
(`run_loop`) build the wire-facing tool error as
`f"tool '{tc.name}' failed ({type(exc).__name__})"`. That string
reaches `ToolResultEvent.error`, is stringified into the AG-UI
`TOOL_CALL_RESULT.content` frame, and is replayed into
`record.messages` on later turns — leaking upstream exception class
names to an untrusted caller. This is the exact pattern LRN-044
(amended) forbids, already fixed elsewhere in the same wave.

## Root cause
LRN-044's amended Check was applied to the files that triggered the
amendment but never re-swept against every other file matching the
same grep.

## Check
`grep -n "type(exc).__name__" agent_sdk/agent/loop.py` inside any
f-string assigned to a tool `error`/wire-bound variable must return
no matches; the class name may appear only in a `logger.*` call.

## Prevention
When a learning's Check clause is amended mid-wave, planning must
re-run the amended Check's grep against every file it matches
project-wide in the same wave, not only the file that triggered the
amendment.
