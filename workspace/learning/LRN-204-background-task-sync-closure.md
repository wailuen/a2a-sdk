---
id: LRN-204
title: Sync BackgroundTask closures race event-loop state off-thread
category: sdk
severity: high
source: redteam
date: 2026-08-19
---

## What happened
Slot-release closures (mcp.py `release()`, a2a.py `abort()`) passed to
`BackgroundTask` were plain `def`s, so Starlette ran them via
`run_in_threadpool` on a worker thread while the loop concurrently iterated
the same state — reproducing "dict mutated during iteration" and silently
dropping a live SSE subscriber.

## Root cause
Starlette dispatches `BackgroundTask` off-loop unless the callable is
`async def`; a teardown closure mutating loop-owned state must be async.

## Check
`grep -rn "background=BackgroundTask(" agent_sdk/routes/*.py` — confirm each
referenced callable is `async def`. Grep `def release\|def abort` (no
`async`) as a direct violation signal.

## Prevention
When a route hands `BackgroundTask` a callable touching loop-owned mutable
state, require `async def` plus a test asserting it runs on
`threading.main_thread()`.
