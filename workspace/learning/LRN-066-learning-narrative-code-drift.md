---
id: LRN-066
title: Learning narrative must match landed code at codify time
category: ops
severity: high
source: redteam
date: 2026-06-18
---

## What happened
LRN-053 was written while the wave was still in flight. Its Prevention note
named wave-cycle.js as still carrying the creates-only scope defect. By the
time the wave closed, the union fix had been applied to all three wave runners,
but the LRN text was not updated to reflect this. A future redteam reading
LRN-053 would chase a non-existent defect or, worse, re-apply an already-landed
change.

## Root cause
The codify step ran (or the LRN was drafted) before the wave completed, so the
"still defective" claim was accurate at draft time but stale at merge time.
No re-verification step reconciled the LRN narrative with the final landed code.

## Check
```bash
# After codifying any LRN that names a specific file as still-defective,
# confirm the claimed defect is actually present:
grep -nE 'allCreates|group\.creates' \
  .claude/workflows/sdk-wave.js \
  .claude/workflows/wave-cycle.js \
  harness/workflows/wave-cycle.js
# Expected: schema / parse-prompt / derivation lines only — no scope-consumer hits.
# If the grep returns no consumer hits, the LRN claim is stale and must be updated.
```

## Prevention
When codifying a finding that says "file X still has defect Y", re-run the
Check grep against the actual working tree before finalising the LRN. If the
fix already landed in the same wave, update the LRN's narrative and Check clause
to reflect the resolved state rather than the in-flight state.
