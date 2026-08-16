---
id: LRN-154
title: LRN-133 gate excludes non-wave GH fixes
category: ops
severity: high
source: redteam
date: 2026-08-15
---

## What happened
RT-008: LRN-044's (critical) Check still read "(a) re-raise or (b) enrich
the error body." GH-135 swapped in a discriminator logging the type but
keeping the caller message fixed — neither held — yet LRN-044 went
un-reconciled: GH-135 was an issue fix, not a `/wave` marked a reversal.

## Root cause
LRN-133's gate is scoped to "a wave reversing prior behavior"; its Check
only greps learnings in wave review. Standalone GH fixes never trigger it,
so a live Check can go stale outside waves.

## Check
For any merged change touching a file a live Check names, grep
`workspace/learning/*.md` for Checks on it; each must be satisfied by the
diff or carry `superseded_by:`.

## Prevention
When planning any change to a surface a live Check names, grep learning
Checks on it and rewrite/supersede any it no longer satisfies, same
commit — wave or standalone.
