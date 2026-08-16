---
id: LRN-035
title: Test-fix agent result must be verified with a re-gate pytest pass
category: testing
severity: high
source: redteam
date: 2026-06-15
---

## What happened
After a `fix:tests:unit:*` or `fix:tests:phase:*` agent dispatch, the wave-cycle template advances the loop without re-running pytest to confirm the fix succeeded. A test-fix agent's self-reported success can be wrong, and if the budget is exhausted the loop archives a still-red suite as if it passed.

## Root cause
The template omits the `:recheck` gate agent call (GATE_SCHEMA) that the harness (RT-002) added at lines 566–585 (unit) and 694–706 (phase). Without it, fix failures are invisible to the loop controller.

## Check
```
grep -n "recheck" harness/workflows/wave-cycle.js
```
Expected: at least one `:recheck` gate call after each `fix:tests:unit:*` and `fix:tests:phase:*` dispatch. Missing output means the re-gate is absent.

RT-002 (round-7 fresh-lens debug) — corrects an RT-014 rewrite that dropped the
`template/` copy from this Check on the justification that "`test_workflow_sync.py`'s
harness↔template axis already keeps the two byte-identical whenever it is checked
out". **That justification is false in exactly the checkout where it was
load-bearing.** `HARNESS_TEMPLATE_SHARED` is built from `TEMPLATE_DIR.glob("*.js")`
and is EMPTY when `template/` is absent, so
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
In every test-fix loop (unit and phase): after the fix agent call, add a re-gate agent with GATE_SCHEMA and label `:recheck`; on null result or exitCode != 0, write a deferred note and break. Never trust a fix agent's self-report as a substitute for running pytest.
