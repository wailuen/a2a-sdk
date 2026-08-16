---
id: LRN-156
title: Hard cost backstop must ship with operator-reachable override
category: ops
severity: high
source: redteam
date: 2026-08-15
---

## What happened
`AGENT_CALL_BUDGET` in wave-cycle.js was a fixed constant (150), no
override, while `agentCallCount` resets each run. A wave costing >150
calls threw at the same point every retry, yet the deferred note told
the operator to "re-run /wave <id> to retry" — a deterministically-
failing fix with no escape hatch short of editing the workflow file.

## Root cause
Budget was hardcoded; remediation text was written without regard to
whether an override existed.

## Check
grep `Number(normalizedArgs.agentBudget) || 150` in
`.claude/workflows/wave-cycle.js`, `harness/workflows/wave-cycle.js`,
`.claude/workflows/sdk-wave.js`; confirm each budget-exceeded deferred
note names `agentBudget` (not a bare retry).

## Prevention
Any hard numeric ceiling that aborts a run (budget, retry cap, timeout)
needs an operator-reachable override in the same change, and its
failure remediation must name that override, not a bare retry —
cross-check LRN-021/LRN-032 at redteam.
