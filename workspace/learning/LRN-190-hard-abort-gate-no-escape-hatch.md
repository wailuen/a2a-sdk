---
id: LRN-190
title: Parse-phase hard-abort gate leaves wave permanently unresumable
category: ops
severity: high
source: redteam
date: 2026-08-15
---

## What happened
The RT-005 Parse-phase guard aborts before any phase runs when a todo lists
a `template/` path in Creates:/Modifies: and `template/` is absent.
GH-131/GH-132 still declare that path, so `/wave w039` can never complete
here — the gate added to fix LRN-174 makes the wave unresumable, with no
split-out or deferral offered.

## Root cause
The gate is abort-only: it blocks on an unmet precondition but offers no
remedy besides that precondition becoming true.

## Check
```bash
grep -n "template-dir-missing" harness/workflows/wave-cycle.js
ls workspace/todos/deferred/ | grep -i template   # remedy must exist
```
Abort present with no matching deferred todo means the wave is stuck.

## Prevention
A hard Parse-phase abort on an unmeetable precondition must pair with a
remedy: a clone-first todo, or strip the blocking path and file
propagation as its own deferred todo. Never land an abort-only gate with
no unblock procedure.
