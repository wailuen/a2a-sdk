---
id: LRN-133
title: Reversing a decision must supersede its learning's Check in the same wave
category: ops
severity: high
source: redteam
date: 2026-07-21
---

## What happened
w036 (GH-123) removed the `seamPaths.length > 0` guard on both seam-audit
pushes — exactly what LRN-034/LRN-038 (high, live) flagged as a bug via
their `## Check` clauses. Neither was updated same-wave, so a live Check
briefly failed against landed code.

## Root cause
No step cross-checks a wave's touched files against existing learnings'
Checks before close, so landed code can contradict a live, unsuperseded
learning unnoticed.

## Check
For a wave reversing prior behavior, grep learning Checks for the touched
paths; any match must show a same-wave edit (`superseded_by:` frontmatter
or rewritten Check/Prevention).

## Prevention
When planning a wave reversing behavior a live learning's Check asserts, add
a task to supersede/rewrite it before close. Sibling modes: LRN-066
(narrative drift), LRN-131 (cross-runner drift).
