---
id: LRN-240
title: Durable write hook wired only into repair path, not happy-path completion
category: protocol
severity: high
source: redteam
date: 2026-09-03
---

## What happened
`run_task_worker`'s normal COMPLETED/FAILED branches (runner.py:1044-1053) call
`_set_status(..., store=store)` only. `TaskStore.persist_messages` has exactly one call
site in the SDK — inside `repair_dangling_tool_use` — which never runs on a clean
completion. A durable copy-on-get store that overrides `persist_messages` instead of
tracking object identity (an option the ABC docstring explicitly offers) silently drops
GH-147's assistant fold, the `bridge_trailing_user` marker, and every GH-148
`__resolved__` reuse marker on the happy path.

## Root cause
The write hook was added for the error/repair path only; the contract docs describe it as
a general durability guarantee without auditing every terminal-transition call site.

## Check
`grep -n "persist_messages" agent_sdk/agent/runner.py` — confirm a call exists on the
COMPLETED/FAILED branches of `run_task_worker` (~runner.py:1038-1053), not only inside
`repair_dangling_tool_use`. Add a test with a copy-on-get store overriding
`persist_messages` that asserts a completed no-tool-call task's durable transcript
carries the assistant fold.

## Prevention
When planning any change to a `TaskStore` write-hook contract, require the hook to be
called from every terminal-transition writer (completion, failure, cancel, deferred), not
only the exception/repair path — and require the ABC docstring to name every actual call
site, not the intended ones.
