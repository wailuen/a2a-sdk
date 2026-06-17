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
grep -n "unitGate\|phaseGate\|testsRed" template/.claude/workflows/wave-cycle.js | grep -v "null\|=== null\|== null"
```
Expect no unchecked gate result assignments. Also verify `testsRed` is set and triggers a loop break on gate failure.

## Prevention
Gate result variables must be null-checked before proceeding; a null gate MUST be treated as a failure (fail-closed). Planner constraint: after every `parallel(fixTasks)`, assert `gateResult !== null && gateResult.exitCode === 0` before advancing to the next redteam round.
