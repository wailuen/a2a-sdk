---
id: LRN-019
title: Null gate response treated as pass (fail-open)
category: security
severity: high
source: redteam
date: 2026-06-15
---

## What happened
All four gate agents in `harness/workflows/wave-cycle.js` (unitGate, phaseGate, protoFixGate, preArchiveGate) use the pattern `if (gate && gate.exitCode !== 0)` to decide whether to block. If a gate agent returns null due to a schema validation failure, timeout, or orchestrator crash, the null is treated as a passing gate and execution continues. For the pre-archive gate this directly violates the GH-22 invariant: a null response can allow archiving a wave with a red test suite.

## Root cause
The guard condition checks truthiness before checking exit code, making null equivalent to exit code 0 (green). Unknown state is silently promoted to success rather than treated as an error.

## Check
```
grep -n 'gate &&' harness/workflows/wave-cycle.js
```
Any match is fail-open; all gate checks must use `!gate || gate.exitCode !== 0`.

## Prevention
Gate checks must be fail-closed. Planner rule: whenever a gate agent result is consumed, the null/undefined case must be the blocking branch. For pre-archive specifically, a null result must set `protocolBlocked=true` and log `'gate agent failed — archive blocked'` before halting.
