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
grep -n "fix:tests:proto:fix\|gate:proto:fix:recheck\|protocolBlocked" harness/workflows/wave-cycle.js
```
Expect both `fix:tests:proto:fix` and `gate:proto:fix:recheck` present; `protocolBlocked` must be set when the re-gate fails.

RT-002 (round-7 fresh-lens debug) — corrects an RT-005/RT-014 rewrite that dropped
the `template/` copy from this Check on the justification that
"`test_workflow_sync.py`'s harness↔template axis already keeps the two byte-identical
whenever it is checked out". **That justification is false in exactly the checkout
where it was load-bearing.** `HARNESS_TEMPLATE_SHARED` is built from
`TEMPLATE_DIR.glob("*.js")` and is EMPTY when `template/` is absent, so
`test_harness_and_template_copies_are_identical` is parametrized over **zero cases**,
and the two presence guards are `xfail(strict=True)` — never a failure. Delegating a
Check's coverage to that axis turns the Check into a permanent silent pass. The
`template/` copy is also currently KNOWN divergent (deferred RT-001 in
`workspace/todos/deferred/w039-group-G-budget-exhausted.md`) — and it is the copy a
downstream agent's `/wave` actually runs.

So also run this Check's grep against the template copy, guarded INLINE on the same
line per LRN-054 (a guard on its own line is still flagged as a dead-path guard):

```bash
test -d template/ && grep -n '<this Check's pattern>' template/.claude/workflows/wave-cycle.js
```

It is a live check where the peer repo is checked out and a documented no-op where it
is not — never a silent removal.

## Prevention
Every test-fix dispatch — unit, phase, or protocol — must be followed by a re-gate agent call before any downstream step proceeds. Planner constraint: after `fix:tests:proto:fix`, assert a `gate:proto:fix:recheck` result with `exitCode === 0`; set `protocolBlocked=true` and skip the recheck on failure.
