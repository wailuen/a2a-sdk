---
id: LRN-253
title: Gate/budget fixes skip sdk-wave.js, again
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
Three GH-131/132 fixes (JSON.parse try/catch, `agentBudget === 0`
rejection + recompute, MAX_LRN_PER_WAVE deferred-note) landed only in the
wave-cycle.js mirrors, never sdk-wave.js — the runner `/sdk-wave` actually
runs — despite this drift already codified twice (LRN-131, LRN-163).

## Root cause
The sync guard enforces parity only across the three wave-cycle.js
copies; nothing checks sdk-wave.js, so porting stays manual and keeps
getting skipped, surviving two prior LRNs.

## Check
Add a test_workflows.py case parametrized over all 4 runner files (3
mirrors + sdk-wave.js) asserting each fix marker (e.g. `agentBudget === 0`,
`lrn-cap-exceeded`) has equal count in every file.

## Prevention
Any gate/budget fix to wave-cycle.js must land in sdk-wave.js in the same
change, plus the 4-way parity test — manual porting already failed twice.
