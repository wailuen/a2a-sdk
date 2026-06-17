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
grep -n 'unitGate &&\|phaseGate &&' template/.claude/workflows/wave-cycle.js
```
Any hit on the `&&` form (not a prior explicit `if (!unitGate)`) is a fail-open gate.

## Prevention
Gate checks must always be two separate statements: `if (!gate) { testsRed = true; break }` followed by `if (gate.exitCode !== 0) { ... }`. After every test-fix agent, a re-gate pytest run is mandatory before continuing the loop. Planners must add both checks as acceptance criteria whenever touching redteam gate logic.
