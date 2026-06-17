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
grep -n 'protoFixGate' template/.claude/workflows/wave-cycle.js | grep -v 'if (!protoFixGate)'
```
Any line matching `if (protoFixGate &&` without a preceding null-check branch is the defect.

## Prevention
After every gate dispatch, add an explicit null-check first: `if (!protoFixGate) { testsRed = true; protocolBlocked = true; }` before the exit-code branch. Mirror harness RT-001 lines 877–883. Planner must flag any gate result used in a compound `&&` condition without a prior null guard.
