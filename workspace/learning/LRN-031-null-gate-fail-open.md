---
id: LRN-031
title: Null pytest gate response treated as GREEN (fail-open)
category: testing
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js`, the unit redteam gate (line 538) uses `if (unitGate && unitGate.exitCode !== 0)` — a null `unitGate` response silently passes the gate, letting the fix loop continue with an unknown test result. The same pattern appears for `phaseGate` (line 630). Additionally, after the test-fix agent runs there is no second pytest invocation to confirm GREEN before the loop continues, meaning a failed fix silently proceeds.

## Root cause
The null guard and the gate check were collapsed into a single `&&` expression instead of being split into an explicit null-fail-fast branch. The re-gate after test-fix present in the harness reference implementation was never ported to the template.

## Check
```
grep -n 'unitGate &&\|phaseGate &&' harness/workflows/wave-cycle.js
```
Any hit on the `&&` form (not a prior explicit `if (!unitGate)`) is a fail-open gate.

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
Gate checks must always be two separate statements: `if (!gate) { testsRed = true; break }` followed by `if (gate.exitCode !== 0) { ... }`. After every test-fix agent, a re-gate pytest run is mandatory before continuing the loop. Planners must add both checks as acceptance criteria whenever touching redteam gate logic.
