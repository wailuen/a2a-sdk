---
id: LRN-100
title: "Budget-exhausted deferred marker must be relocated once findings are resolved"
category: workflow
severity: low
tags: [housekeeping, deferred, wave-cycle]
wave: w024
---

A budget-exhausted deferred file placed in `workspace/todos/deferred/` implies pending work. Once all findings in that file are resolved, the file must be moved to `workspace/todos/completed/` (or deleted). Leaving a file with a "wave complete / no further action required" note inside `deferred/` creates a contradictory state signal: the directory says "outstanding work here" but the file says "nothing to do."

**Concrete case:** `w024-group-G-budget-exhausted.md` sat in `deferred/` after all its RT findings were fixed, with the original instruction struck through (`~~Fix remaining findings…~~`). A later redteam (RT-002 in w024) flagged it as misleading.

**Pattern seen in:** w021, w022, w024 (recurring drift).

**Guard:** After resolving all findings in a budget-exhausted deferred file, immediately `mv` it to `workspace/todos/completed/`. The `deferred/` directory must only ever contain files with at least one OPEN finding.
