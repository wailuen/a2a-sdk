---
id: LRN-034
title: Unconditional seam audit fires on every protocol wave
category: ops
severity: high
source: redteam
date: 2026-06-15
---

## What happened
In `template/.claude/workflows/wave-cycle.js` line 739, the seam audit advisor task is pushed unconditionally for every protocol wave. When a wave creates no route files, the seam audit still fires, producing empty or vacuous findings that inflate the issue list and waste an agent call.

## Root cause
No guard derives which files in the `creates` list are route files before scheduling the seam advisor. The harness version (RT-005) uses `SEAM_ROUTE_MARKERS` to derive `seamPaths` from `allCreates` and skips the push when `seamPaths.length === 0`.

## Check
```
grep -n 'seamPaths\|SEAM_ROUTE_MARKERS' template/.claude/workflows/wave-cycle.js
```
Must return the `SEAM_ROUTE_MARKERS` constant definition and a `seamPaths.length > 0` guard before the seam advisor task push near line 739, and the same guard at the seam recheck near line 854.

## Prevention
Before scheduling any cross-cutting advisor (seam, security, schema), derive the relevant file subset from `allCreates` first and gate the push on a non-empty subset. Never push unconditionally when the audit scope depends on the creates list.
