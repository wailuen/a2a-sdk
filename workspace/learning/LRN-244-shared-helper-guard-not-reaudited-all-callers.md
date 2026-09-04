---
id: LRN-244
title: Shared helper's new raising hook guarded at one call site, not all
category: sdk
severity: high
source: redteam
date: 2026-09-03
---

## What happened
`repair_dangling_tool_use(store=...)` calls `store.persist_messages(record)`
unconditionally. One caller (`tasks_cancel` in routes/a2a.py) was wrapped in
try/except to survive a raising store override, but three other call sites —
the deferred background awaiter's `_fail`, and `run_task_worker`'s `except AgentError`
and `except Exception` handlers — remain unguarded and sit before the `try/finally` that
guarantees `close_streams`. A raising store override escapes a fire-and-forget
`asyncio.Task` entirely, leaving the task stuck WORKING with its SSE stream never closed.

## Root cause
The fix for the cancel path treated the hazard as local to that one call site instead of
auditing every caller of the now-shared helper that gained a raising hook.

## Check
`grep -n "repair_dangling_tool_use" agent_sdk/agent/runner.py` — confirm every call site
(cancel, `_fail`, `except AgentError`, `except Exception`, and any deferred path) is
wrapped in try/except, or that the flush was moved inside the helper itself with its own
guard. Add a regression test per call site with a store whose `persist_messages` raises.

## Prevention
When planning a fix that guards one caller of a shared helper against a hook that can
raise, require the planner to enumerate and re-audit every other caller of that helper in
the same change — guarding one caller while leaving others unguarded is not a partial
fix, it is a new failure mode on the common path.
