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
grep -n "recheck" template/.claude/workflows/wave-cycle.js
```
Expected: at least one `:recheck` gate call after each `fix:tests:unit:*` and `fix:tests:phase:*` dispatch. Missing output means the re-gate is absent.

## Prevention
In every test-fix loop (unit and phase): after the fix agent call, add a re-gate agent with GATE_SCHEMA and label `:recheck`; on null result or exitCode != 0, write a deferred note and break. Never trust a fix agent's self-report as a substitute for running pytest.
