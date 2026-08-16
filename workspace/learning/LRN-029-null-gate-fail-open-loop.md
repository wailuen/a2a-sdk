---
id: LRN-029
title: Null gate crash allows fail-open progression in fix loops
category: testing
severity: high
source: redteam
date: 2026-06-15
---

## What happened
The wave-cycle template runs `parallel(fixTasks)` then proceeds directly to the next redteam round without verifying fix success through a schema-gated gate. The gate check only tests for a non-zero exit code; if the gate agent crashes and returns null, the loop continues without any confirmation. Combined with a consistent crash pattern (RT-003), this allows infinite silent progression to budget exhaustion.

## Root cause
`unitGate`/`phaseGate` results are not null-guarded before being evaluated. A null result is falsy but not caught as a failure, so the LRN-017 rule ("every fix batch must be followed by a schema-gated pytest gate") is violated — the gate runs but the loop does not break.

## Check
```
grep -n "unitGate\|phaseGate\|testsRed" harness/workflows/wave-cycle.js | grep -v "null\|=== null\|== null"
```
Expect no unchecked gate result assignments. Also verify `testsRed` is set and triggers a loop break on gate failure.

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
Gate result variables must be null-checked before proceeding; a null gate MUST be treated as a failure (fail-closed). Planner constraint: after every `parallel(fixTasks)`, assert `gateResult !== null && gateResult.exitCode === 0` before advancing to the next redteam round.
