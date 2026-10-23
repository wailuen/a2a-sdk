---
id: LRN-463
title: Redteam finding ids are not unique across rounds
category: sdk
severity: high
source: redteam
date: 2026-10-23
---

## What happened
originalFinding in wave-cycle.js matched candidates to findings by id+file, then by id alone. Each redteam call numbers from RT-001, so an open candidate matched an earlier fixed RT-001 in the same file and was marked `fixed-in-wave`, so it was never filed.

## Root cause
Ids are unique only within one review call; the join fails open on collisions and falls back to model-supplied quote.

## Check
Verify `grep -n "f.id === c.id" harness/workflows/wave-cycle.js` also compares quote with no id-only fallback, and a behaviour test has two RT-001 findings in one file (one fixed, one open) asserting the open one stays still-open.

## Prevention
When planning any cross-round finding join, require key id+file+quote exact match and fail closed (still-open) on zero or multiple matches.
