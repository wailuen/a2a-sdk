---
id: LRN-249
title: LRN-144 Check failure — legitimate second bridge call site left the LRN unamended
category: protocol
severity: high
source: redteam
date: 2026-09-03
---

## What happened
LRN-144's Check asserts `bridge_trailing_user` has exactly one call site
(inside `repair_dangling_tool_use`) and zero matches in `routes/a2a.py`.
RT-002 added a defensible second call in `routes/a2a.py`'s
`_create_task_record` to re-assert the invariant on store-supplied
transcripts, but LRN-144 was never amended — its recorded invariant is now
false, every future audit of it fails, and the landed precedent invites
more inlined bridge calls elsewhere. The Check also names the old symbol
`_repair_dangling_tool_use_safe` instead of the current public
`repair_dangling_tool_use_safe`, so it isn't runnable as written.

## Root cause
A new, justified call site was added without treating the LRN that pinned
the old count as part of the change's surface — exact-count/zero-match
Check clauses are load-bearing contracts, not incidental grep output.

## Check
`grep -rn "bridge_trailing_user" agent_sdk/agent/runner.py agent_sdk/routes/a2a.py`
must match LRN-144's *current* text exactly (call sites + rationale for
each), and `grep -n "repair_dangling_tool_use_safe" workspace/learning/LRN-144*.md`
must use the real symbol name.

## Prevention
When planning a change that adds a call site an existing LRN's Check
pins as exact-count or zero-match, require amending that LRN in the same
change — enumerate the new site and its rationale — rather than leaving a
Check clause to silently fail forever.
