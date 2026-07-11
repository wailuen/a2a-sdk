---
id: LRN-109
title: Documented ledger-append fix (LRN-062) recurred unenforced in w029
category: ops
severity: high
source: redteam
date: 2026-07-10
---

## What happened
w029 (GH-95–GH-101) was archived and released as 0.5.37, but plan.md's wave table stops at W28 — the exact gap LRN-062 already documented for w020.

## Root cause
LRN-062's Prevention was written as a learning but never wired into wave-cycle.js/sdk-wave.js as an enforced guard, so the ledger append stays skippable for GH-issue waves.

## Check
`grep -oE 'w[0-9]+' workspace/todos/archive/*.md 2>/dev/null | sort -u > /tmp/a.txt && grep -oE 'W[0-9]+' workspace/todos/plan.md | tr A-Z a-z | sort -u > /tmp/p.txt && comm -23 /tmp/a.txt /tmp/p.txt` must be empty.

## Prevention
Archive step must hard-fail (not warn) if the waveId is absent from plan.md post-append. A learning without an enforced code guard isn't a fix — treat LRN-062-class findings as blocking until verified in workflow source.
