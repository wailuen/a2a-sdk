---
id: LRN-060
title: Wave-runner scope fix not propagated to sibling runners
category: ops
severity: critical
source: redteam
date: 2026-06-15
---

## What happened
The Creates-only scope bug fixed in sdk-wave.js (w020) was never propagated to the sibling wave-cycle.js runners (.claude/workflows/ and harness/workflows/). Both copies derive every adversarial-review scope set, protocol-surface detection, audit file filters, seam paths, and archive FR-map exclusively from allCreates/group.creates and carry no empty-scope guard. An edit-only (Modifies-only) agent wave therefore lands with an empty redteam scope and zero protocol audit with no error — a silent gate bypass strictly worse than the pre-fix sdk-wave.js state.

## Root cause
The harness maintains two independent runner codebases (sdk-wave.js and wave-cycle.js) with duplicated scope logic. The fix was applied to one runner and closed without a cross-runner propagation check.

## Check
grep -n "allModifies\|allScope\|group\.scope" .claude/workflows/wave-cycle.js harness/workflows/wave-cycle.js — both files must contain allModifies, allScope, and group.scope; absence of any match confirms the fix is missing.

## Prevention
When planning any wave-runner scope or schema change, ensure the task list explicitly includes applying the identical change to ALL sibling runner files (sdk-wave.js, .claude/workflows/wave-cycle.js, harness/workflows/wave-cycle.js) in the same wave before it closes. A partial harness fix seeds the unfixed copy into every new agent wave.
