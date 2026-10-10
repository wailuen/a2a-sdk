---
id: LRN-260
title: Todo-requested registry/REVIEWS updates not verified by redteam
category: testing
severity: high
source: redteam
date: 2026-10-09
---

## What happened
RATIFY-R8 asked (Reuses: C-021) for a note that Profile v1.1 makes `metadata` free-form, in REVIEWS.md Round 11 and the C-021 registry entry. Neither landed; only code and tests changed.

## Root cause
Unit redteam checked code and test edits but not the doc/registry updates named in the todo's Reuses/notes line.

## Check
Verify that `grep -n "metadata" workspace/components/README.md` shows the cross-cutting note in the C-021 entry, and that REVIEWS.md Round 11 mentions C-021.

## Prevention
When planning a todo with a Reuses/notes line requiring a registry or REVIEWS update, add it as an explicit acceptance criterion, and have the unit redteam confirm each named doc edit landed.
