---
id: LRN-120
title: MCP tools/call folds unhandled DeferredResult via str(), leaking repr
category: protocol
severity: high
source: redteam
date: 2026-07-14
---

## What happened
GH-115 fixed `is_generator` dispatch, but the coroutine branch still assumed `invoke()` returns a terminal artifact. A `long_running=True` tool returning `DeferredResult` was folded via `str()`: coroutine repr leaked onto the wire as `isError:false`, `handle` never awaited, work dropped.

## Root cause
Dispatch branched only generator-vs-coroutine, never checked the return value for `DeferredResult`; MCP lacks `agent/loop.py`'s background-task channel.

## Check
`tools/call` on a `DeferredResult`-returning tool must never emit `"DeferredResult("`/`"coroutine object"` in `content[0].text` (see `test_gh87_deferred_task.py`). `grep -n DeferredResult agent_sdk/routes/mcp.py`.

## Prevention
Any tool-invocation surface must handle BOTH long-running forms — generator AND `DeferredResult` coroutine (await inline under timeout, else error). Use one shared dispatch helper (LRN-116).
