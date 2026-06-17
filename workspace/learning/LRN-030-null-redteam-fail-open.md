---
id: LRN-030
title: Null redteam response silently treated as clean pass
category: testing
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js`, the unit-redteam loop (line 468) and phase-redteam loop (line 571) used `if (!rt || rt.findingsCount === 0) { break }` to exit the fix loop. A null agent response and a genuine zero-findings result were collapsed into the same branch, so a failed or non-responsive redteam agent was silently treated as a clean pass. This allowed archive to proceed on code that was never inspected.

## Root cause
Null-check and clean-detection were merged into one condition. A null response should reset state and continue the loop (engage debug); a zero-findings response should break. Conflating them violated RT-004 (fail-safe redteam).

## Check
```
grep -n 'if (!rt || rt.findingsCount' template/.claude/workflows/wave-cycle.js
```
Must return no matches. Correct pattern (as in `harness/workflows/wave-cycle.js` lines 471-481 and 610-620) uses separate guards:
```
if (!rt) { log('WARNING: ...'); prevSigs = new Set(); continue }
if (rt.findingsCount === 0) { break }
```

## Prevention
When authoring or reviewing redteam loop logic: null response MUST `continue` (never `break`). Any condition that joins null with zero-findings is a fail-open bug. Planner must add an explicit review step for this pattern whenever wave-cycle loop logic is modified.
