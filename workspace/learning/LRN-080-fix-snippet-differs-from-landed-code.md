---
id: LRN-080
title: LRN Fix snippet must be copied from landed code, not the originally proposed fix
category: ops
severity: high
source: redteam
date: 2026-06-19
---

## What happened
LRN-073 was codified with `failureClass: 'harness-contamination'` in its ## Fix
code block. During the redteam loop the fix was deliberately revised to
`failureClass: 'code-bug'` (null results fail the three-condition contamination
gate), but the learning was not updated to track that revision. The LRN therefore
taught the rejected value, not the landed one — the LRN-066 anti-pattern
applied to a specific constant rather than a stale file-state claim.

## Root cause
The ## Fix snippet was taken from the original proposed fix, not from the
accepted landed code. A value that changed during the redteam review cycle was
never reflected back into the LRN before it was committed.

## Check
```bash
# For any LRN whose ## Fix block contains a failureClass literal, confirm it
# matches the source of truth in acceptance-api.js:
grep -n "failureClass" \
  workspace/learning/LRN-073-acceptance-filter-boolean-nan-denominator.md \
  harness/workflows/acceptance-api.js
# Both must show 'code-bug'. Any LRN-side literal that differs from the file
# is a violation.
```

## Prevention
When codifying after a redteam loop, diff the ## Fix snippet against the actual
landed file before writing the LRN. If any literal, field name, or constant was
revised during review, use the landed value — never the originally-proposed one.
This is a stricter sub-rule of LRN-066: narrative drift at the constant level is
as misleading as narrative drift at the file-state level.
