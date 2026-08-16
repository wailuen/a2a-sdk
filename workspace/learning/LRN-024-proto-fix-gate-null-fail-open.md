---
id: LRN-024
title: Proto-fix gate null treated as pass in wave-cycle
category: ops
severity: high
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js` line 799, the `protoFixGate` result is checked as `if (protoFixGate && protoFixGate.exitCode !== 0)`. When the gate agent crashes and returns null, the condition evaluates to false and the recheck dispatch proceeds unconditionally — a fail-open on an unknown test suite state.

## Root cause
The guard conflates a null response (agent crash) with a passing exit code. The null case silently falls through rather than being treated as a blocking failure.

## Check
```
grep -n 'protoFixGate' harness/workflows/wave-cycle.js | grep -v 'if (!protoFixGate)'
```
Any line matching `if (protoFixGate &&` without a preceding null-check branch is the defect.

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
After every gate dispatch, add an explicit null-check first: `if (!protoFixGate) { testsRed = true; protocolBlocked = true; }` before the exit-code branch. Mirror harness RT-001 lines 877–883. Planner must flag any gate result used in a compound `&&` condition without a prior null guard.
