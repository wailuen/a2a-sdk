---
id: LRN-168
title: Todo Creates/Modifies omits an actually-touched tracked file
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-135's todo declared Creates:/Modifies: for 5 files, but executor.py (new
import, new constant, a persisted-data migration) was also modified and
named on no todo line. Dirty in `git status --short`, absent from
wave.allScope: tripped offendingUndeclaredScope.

## Root cause
Planning traced the primary chain but missed a downstream consumer,
including a stored-value contract change (DB `last_error` value) noted
only in CHANGELOG prose.

## Check
`git status --short` every tracked `agent_sdk/**.py` path touched; confirm
each has its own Creates:/Modifies: line, not just a CHANGELOG mention.
Fails if offendingUndeclaredScope flags a dirty path outside wave.allScope.

## Prevention
When a wave touches a module, grep its importers/callers and add every
file needing a change to its own Creates:/Modifies: line, incl.
stored-value contract changes.
