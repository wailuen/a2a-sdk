---
id: LRN-025
title: Null agent response in archive commit guard silently passes as clean
category: protocol
severity: high
source: redteam
date: 2026-06-15
---

## What happened
In the wave-cycle workflow, when the archive-commit-check agent returns null, the condition `if (archiveIntent && archiveIntent.offendingPaths && ...)` evaluates to false and the else branch logs "Commit check passed — all Creates: files are committed". The gate never fired, yet the workflow reports success and proceeds to archive.

## Root cause
The null guard was omitted for this specific gate. Every other null-agent response in the file sets `protocolBlocked = true` via RT-001 handling; the archive commit guard was the lone exception, making it fail-open instead of fail-closed.

## Check
```
grep -n "archiveIntent" harness/workflows/wave-cycle.js
```
Expected: a leading `if (!archiveIntent)` block that sets `protocolBlocked = true` before the `offendingPaths` check. Absence means the null guard is missing.

RT-014: checks the in-repo propagation source (`harness/workflows/wave-cycle.js`)
only — the peer repo copy `template/.claude/workflows/wave-cycle.js` (LRN-071) is
not always checked out locally, and `test_workflow_sync.py`'s harness↔template
axis already keeps the two byte-identical whenever it is, so this grep covers
both copies without a dead path in a checkout without `template/`.

## Prevention
For every gate agent result in wave-cycle (and any future workflow), add a null guard as the first branch: set `protocolBlocked = true` and log a blocking warning before testing inner fields. Never rely on a falsy compound condition to catch a missing agent response — it silently takes the else/pass branch.
