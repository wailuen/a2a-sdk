---
id: LRN-026
title: Null proto-fix gate fails open — crashed gate must set protocolBlocked
category: testing
severity: high
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js` (~line 799) the proto-fix gate check is `if (protoFixGate && protoFixGate.exitCode !== 0)`. When the gate agent crashes and returns null, the condition short-circuits to false, so neither `testsRed` nor `protocolBlocked` is set. The harness handles null in a dedicated branch that sets both flags and emits a warning. The template silently proceeds to recheck dispatch with the suite in an unknown state.

## Root cause
The null guard and the non-zero exit-code guard were collapsed into one condition. A null return (agent crash) is distinct from a passing exit code and must be treated as a blocking failure.

## Check
```
grep -n 'protoFixGate &&' harness/workflows/wave-cycle.js
```
The result must NOT show a single compound condition; it must show a null branch that sets `testsRed=true` and `protocolBlocked=true` separately from the `exitCode !== 0` branch.

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
When writing gate checks: always handle null (agent crash) as an explicit blocking branch before checking exitCode. Mirror harness lines 877–883: null → `testsRed=true, protocolBlocked=true` + warning log; non-zero exitCode → same flags + error log. Never collapse the two into a single `&&` predicate.
