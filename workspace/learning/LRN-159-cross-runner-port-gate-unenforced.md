---
id: LRN-159
title: Byte-identical sync guard spans only wave-cycle.js mirrors, blind to sdk-wave.js
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
The RT-009 accumulateNonBlocking fix (loop-scoped groupNonBlockingSigs/phaseNonBlockingSigs,
single post-loop deferred-note write) landed in all three wave-cycle.js copies but not in
sdk-wave.js, which had zero accumulateNonBlocking references and wrote the deferred note only
inside the clean-exit branch — silently discarding all medium/low findings on every non-clean
exit path (round-budget-exhausted, tests-red, null-gate, findings-count-mismatch). Both
SKILL.md copies documented the wave-cycle.js behavior as if sdk-wave.js shared it.

## Root cause
Third recurrence of the root cause already codified in LRN-131 and LRN-137: the harness's
byte-identical sync test enforces parity only across the wave-cycle.js copies, never between
wave-cycle.js and sdk-wave.js — so those learnings' Check/Prevention text was never wired into
a mechanical gate and depended on planner memory, which failed again.

## Check
`grep -c accumulateNonBlocking .claude/workflows/sdk-wave.js .claude/workflows/wave-cycle.js`
must report equal nonzero counts in both files, and every exit path in both (not just
clean-exit) must write the deferred note exactly once, post-loop.

## Prevention
When planning any fix to shared wave-runner gate/accumulator logic, do not rely on prior LRN
Check text alone — add a parametrized test (tests/test_workflows.py) asserting named-symbol
parity across ALL FOUR runner files (sdk-wave.js + 3 wave-cycle.js copies), and list
"port to sdk-wave.js" as a mandatory Creates/Modifies item in the same wave, not a follow-up.
