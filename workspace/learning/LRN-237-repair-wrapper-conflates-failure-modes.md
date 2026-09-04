---
id: LRN-237
title: Guarded repair wrapper conflates in-memory failure with flush-only failure
category: sdk
severity: high
source: redteam
date: 2026-09-03
---

## What happened
`repair_dangling_tool_use_safe` (`agent_sdk/agent/runner.py`) returns
one boolean for two different outcomes: the in-memory repair itself
failing, and the in-memory repair succeeding but
`store.persist_messages` failing. Every caller threads that boolean
into `set_task_status(..., repaired=...)`, which treats `False` as
"skip both durable flushes" — short-circuiting `set_task_status`'s
own retry-then-fail-closed logic for the flush-only case, so a
transient store write failure can leave a task's durable record
non-terminal forever.

## Root cause
The wrapper collapsed "primary mutation failed" and "primary mutation
OK but its persistence flush failed" into one boolean, losing the
distinction its caller's gate depends on.

## Check
Verify `repair_dangling_tool_use_safe` lets a caller distinguish
"in-memory repair failed" from "in-memory repair OK, flush failed" —
grep its body for the flush-exception branch and confirm it does not
fall through to the same `return False` as the repair-failed branch.

## Prevention
When planning a guarded wrapper around a mutation with a separate
persistence step, require its return value (or a tri-state) to let
callers distinguish "mutation failed" from "mutation OK, flush
failed" — never fold both into one boolean feeding a fail-closed gate.
