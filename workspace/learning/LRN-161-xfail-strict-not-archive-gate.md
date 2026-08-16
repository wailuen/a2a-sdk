---
id: LRN-161
title: xfail(strict=True) absorbs unverifiable state, doesn't block archive
category: testing
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-131/GH-132 declare `template/.claude/workflows/wave-cycle.js` a
deliverable, but `template/` is absent here. Its propagation guards are
`xfail(strict=True)` when `TEMPLATE_DIR` is missing, so pytest exits green
("2 xfailed") and the wave archived with the peer copy still carrying the
pre-fix bugs.

## Root cause
`xfail(strict=True)` is a test-outcome annotation, not an archive gate — a
runner checking only "suite passed" treats an unverified deliverable as
done.

## Check
Run with `-rxX`, grep XFAIL lines for `template/`-path tests; confirm a
pre-archive check hard-fails when a todo names `template/` and
`test -d template` is false.

## Prevention
When a wave declares a `template/` deliverable, never let xfail/skip be the
sole completion signal — add a pre-archive check that hard-fails if the
peer dir isn't checked out.
