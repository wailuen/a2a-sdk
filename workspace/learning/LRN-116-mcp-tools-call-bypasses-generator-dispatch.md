---
id: LRN-116
title: MCP tools/call bypasses generator tool dispatch, breaking long-running Tier-1 tools
category: protocol
severity: high
source: protocol-audit
date: 2026-07-14
---

## What happened
`_handle_tools_call` in `agent_sdk/routes/mcp.py` always calls `entry.invoke()`, never `entry.invoke_gen()`. Any Tier-1 tool declared `long_running=True` (async-generator body) raises `TypeError` inside `invoke()`, which the blanket `except Exception` turns into a generic `isError: true` "tool execution failed" — permanently unretryable and non-diagnostic.

## Root cause
`agent/loop.py` (A2A/AG-UI dispatch) branches on `entry.decl.is_generator` before choosing `invoke()` vs `invoke_gen()`; `routes/mcp.py` never replicated that branch, so long-running Tier-1 tools work over A2A/AG-UI but always fail over MCP, violating the "Tier 1 only — surface parity" rule.

## Check
`grep -n "entry.invoke(" agent_sdk/routes/mcp.py` — confirm the call site is guarded by `if entry.decl.is_generator` (mirroring `agent/loop.py:441-446`), or add a regression test asserting a `long_running=True` async-generator Tier-1 tool returns valid content (not `isError`) via MCP `tools/call` (see shape in `tests/test_gh87_deferred_task.py`).

## Prevention
When planning any new tool-invocation surface (or auditing an existing one), require it to branch on `entry.decl.is_generator` and call `invoke_gen()` for generator tools — never assume `invoke()` is universal. Prefer factoring a shared invoke-dispatch helper used by `loop.py` and `routes/mcp.py` so this can't reappear on a future surface.
