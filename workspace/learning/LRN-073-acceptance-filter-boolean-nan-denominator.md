---
id: LRN-073
title: Scenario runner filter(Boolean) turns crashed agents into silent pass-rate inflation
category: testing
severity: high
source: redteam
date: 2026-06-19
sdkCandidate: true
related: RT-002 (w021 group:G RT-001)
---

## What happened
`acceptance-api.js` collected pipeline results with `.filter(Boolean)`, silently dropping any scenario whose agent crashed or timed out (null return). When all agents crashed, `results` was an empty array; the reduce for `a2aMin`/`aguiMin` returned its initial value of `10`, and the log line reported "A2A min: 10/10" over zero scenarios — a false-pass on the SKILL.md 100%-pass gate with no signal that anything ran.

## Root cause
`.filter(Boolean)` over agent pipeline results conflates "no result" with "scenario excluded", reducing the denominator without reifying the failure. Any scoring function that divides `passed / results.length` or reduces `min(scores)` over a filtered array will produce misleading output (NaN or initial-value) when nulls are dropped.

## Fix
Map each null to a synthetic failure record before any scoring or assertion:
```js
const results = rawResults.map(function(r, i) {
  if (r != null) return r
  const s = scenarios[i]
  return {
    scenarioId: s.id, name: s.name,
    passed: false, a2aMinScore: 1, aguiMinScore: 1,
    a2aTurns: [], aguiTurns: [],
    failureClass: 'code-bug',
    failureDetail: 'agent returned null (crash or timeout)',
  }
})
// failureClass is 'code-bug', NOT 'harness-contamination': a null agent result
// does not satisfy the three-condition contamination gate (cross-scenario tool
// bleed + anomalous low score + an identified contaminating scenario). A crash
// or timeout is a code bug, so the synthetic record must say so.
if (results.length !== scenarios.length) throw new Error('pipeline dropped results must be reified as failures')
```
Guard summary reductions against an empty array: `results.length > 0 ? results.reduce(...) : 0`.

## Check
grep -n 'filter(Boolean)' harness/workflows/acceptance-api.js
# Must return no results — any .filter(Boolean) on pipeline output is a violation.
grep -n '\.filter(Boolean)' template/.claude/workflows/acceptance-api.js
# Same check for the peer-repo template copy that agents actually run via /acceptance.
# (acceptance-api.js has NO .claude/workflows/ runtime copy in this repo — it is
#  propagated only to template/; greppng a non-existent path is a fail-open no-op.)

## Prevention
In any scenario/agent runner:
1. Never drop null agent results — map them to explicit synthetic failure records keyed by scenario index.
2. Assert `results.length === scenarios.length` after the map.
3. Guard all reduce/summary operations against empty arrays to prevent NaN or initial-value false-passes.
4. Apply the same fix to every propagated copy in the same commit. acceptance-api.js
   has no .claude/workflows/ runtime copy in this repo — its second copy is the peer
   repo at template/.claude/workflows/acceptance-api.js (guarded by tests/test_workflow_sync.py
   axis 2). Verify every ## Check grep path resolves to a real file (`ls`) at codify time.
