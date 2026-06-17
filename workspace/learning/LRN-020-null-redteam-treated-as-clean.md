---
id: LRN-020
title: Null redteam response treated as clean pass in unit loop
category: testing
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js` line 468, the unit redteam loop uses `if (!rt || rt.findingsCount === 0) { break }` to exit the loop. When the redteam agent crashes or returns null, this condition is true and the loop breaks — incorrectly declaring the group clean. A crashed reviewer is an unknown state, not a pass.

## Root cause
The null check and zero-findings check were collapsed into a single OR condition. Null (agent failure) and zero findings (genuine clean) require different handling: null must reset state and continue so debug can engage, while zero findings should break.

## Check
```
grep -n '!rt || rt.findingsCount === 0' template/.claude/workflows/wave-cycle.js
```
Any match is a bug. Correct pattern (from `harness/workflows/wave-cycle.js` lines 471–479) splits into two separate branches: `if (!rt)` resets `prevSigs` and `continue`s; `if (rt.findingsCount === 0)` breaks.

## Prevention
When authoring redteam loop termination logic, null responses must never share a branch with zero-findings responses. Planner must verify template and harness wave-cycle.js stay in sync on this guard whenever either file is modified.
