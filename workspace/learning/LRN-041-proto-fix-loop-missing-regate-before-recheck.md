---
id: LRN-041
title: Protocol-fix loop missing re-gate before recheck
category: testing
severity: high
source: redteam
date: 2026-06-15
---

## What happened
When the `gate:proto:fix` agent returns RED, the wave-cycle template dispatches a `fix:tests:proto:fix` agent and then proceeds directly to the protocol recheck without verifying the fix succeeded. The harness sets `protocolBlocked=true` and runs a `gate:proto:fix:recheck` agent call to block advancement; the template omits both, allowing a red test suite to silently reach the protocol recheck step.

## Root cause
The test-fix dispatch in the template (around line 971) has no corresponding re-gate agent call. Only the harness enforces the re-gate discipline; the template diverged without inheriting it, defeating zero-tolerance for agent projects using the template.

## Check
```
grep -n "fix:tests:proto:fix\|gate:proto:fix:recheck\|protocolBlocked" template/.claude/workflows/wave-cycle.js
```
Expect both `fix:tests:proto:fix` and `gate:proto:fix:recheck` present; `protocolBlocked` must be set when the re-gate fails.

## Prevention
Every test-fix dispatch — unit, phase, or protocol — must be followed by a re-gate agent call before any downstream step proceeds. Planner constraint: after `fix:tests:proto:fix`, assert a `gate:proto:fix:recheck` result with `exitCode === 0`; set `protocolBlocked=true` and skip the recheck on failure.
