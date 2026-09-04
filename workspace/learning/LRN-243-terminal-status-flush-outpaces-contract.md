---
id: LRN-243
title: New terminal-status flush marks tasks terminal before transcript persists
category: sdk
severity: high
source: redteam
date: 2026-09-03
---

## What happened
The C-005 contract and its docstrings promise that overriding both `persist_messages` and
`persist_status` makes a copy-on-get `TaskStore` durable-correct. A later change flushes
terminal COMPLETED/FAILED status on the happy path via `_set_status(store=store)`, but
`persist_messages` still has its one call site inside `repair_dangling_tool_use`, which
never runs on that path. Reproduced: `persist_messages` calls stayed `[]` while
`persist_status` recorded `working, working, completed` and `record.messages` grew by
one — a durable store now marks a task terminal without ever receiving its transcript, so
the next `contextId` continuation replays a stale/empty history.

## Root cause
The terminal-status flush was added without re-auditing the sibling write hook it
sits next to, so the contract's "override both hooks" guarantee stopped being true for
the happy path the moment status began flushing before messages.

## Check
Reproduce with a store overriding both hooks: assert `persist_messages` is called at
least once before or alongside the terminal `persist_status` call on a normal
no-tool-call completion. `grep -n "persist_messages\|persist_status" agent_sdk/agent/runner.py`
to confirm both hooks fire on the same terminal transition.

## Prevention
When planning a change that flushes one durable-store write hook on a new code path,
require every sibling hook the store contract also promises to be flushed on that same
path before the transition is allowed to go terminal — never land one half of a paired
guarantee alone.
