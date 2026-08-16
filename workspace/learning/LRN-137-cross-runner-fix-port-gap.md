---
id: LRN-137
title: Wave-runner fixes land in wave-cycle.js copies but skip sibling sdk-wave.js
category: sdk
severity: critical
source: redteam
date: 2026-08-15
---

## What happened
The GH-131 args-normalization fix and the entire GH-132 bundle (severity-floor gating,
debug-replaces-fanout, AGENT_CALL_BUDGET, MAX_LRN_PER_WAVE) landed in all three
wave-cycle.js copies but were never ported to sdk-wave.js, which still has unnormalized
`args.waveFile`, a fail-open `!rt ||` null-redteam-as-CLEAN check (LRN-020/023/030
family), no agent-call budget, and no LRN cap.

## Root cause
LRN-131's prevention (port shared gate fixes to every runner) was not enforced by any
mechanical gate — it relied on planner memory, so a second cross-runner fix wave repeated
the exact drift LRN-131 already documented.

## Check
`grep -n "AGENT_CALL_BUDGET\|MAX_LRN_PER_WAVE\|FIX_BATCH_FILE_THRESHOLD" .claude/workflows/sdk-wave.js .claude/workflows/wave-cycle.js` —
both must report matches. Also confirm no bare `!rt ||` / `!rt.findingsCount` fail-open
check remains in sdk-wave.js (must match wave-cycle.js:673-689 fail-closed form).

## Prevention
When planning any fix to wave-cycle.js gate/loop logic, require the todos to explicitly
list sdk-wave.js as a port target (not just the 3 wave-cycle.js copies), and add a CI/test
parametrization in tests/test_workflows.py asserting the two runners' shared constants and
gate predicates stay identical — do not rely on planner recall of LRN-131.
