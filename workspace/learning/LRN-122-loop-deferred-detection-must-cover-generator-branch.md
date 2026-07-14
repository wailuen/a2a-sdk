---
id: LRN-122
title: DeferredResult detection must run on every tool-result path in loop.py, not just the coroutine branch
category: protocol
severity: medium
source: redteam
date: 2026-07-14
---

## What happened
w034/group G RT-001: `agent_sdk/agent/loop.py`'s async-generator tool branch
(`elif entry.decl.is_generator`) drained `invoke_gen` and set the terminal
`result`, but never ran the `isinstance(result, DeferredResult)` handoff the
coroutine branch performs immediately after. A long-running async-generator
tool whose final yield was a `DeferredResult` was never recognised as
deferred: no `DeferredEvent` emitted, the raw `DeferredResult` (holding an
unawaited coroutine handle) was folded into the model conversation on
`ToolResultEvent`, and the deferred job never ran. The identical tool
dispatched over MCP (`invoke_any` -> `resolve_deferred_result`) worked
correctly — a transport contract drift on the exact class of repr leak
GH-120/GH-121 had just closed on the coroutine surfaces.

## Root cause
Two separate tool-dispatch branches in `run_loop` (coroutine vs
async-generator) each produce a terminal `result` value, but the
`DeferredResult` handoff was written once, on only one of the two branches.

## Check
`grep -n "isinstance(result, DeferredResult)" agent_sdk/agent/loop.py` must
match in BOTH the `is_generator` branch and the coroutine (`else`) branch of
the per-tool-call dispatch. If a third dispatch branch is ever added, it must
carry the same check too.

## Prevention
When planning a change to `run_loop`'s per-tool dispatch (loop.py), or adding
a new tool-execution branch, require the todo's AC to state that
`isinstance(result, DeferredResult)` detection is applied identically on
every branch that can produce a terminal `result`, and add a cross-surface
parity test (mirroring `test_rt001_deferred_nesting_parity.py`) proving the
MCP and A2A/AG-UI surfaces resolve the same tool contract identically.
