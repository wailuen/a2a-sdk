---
id: LRN-388
title: Raw user value logged despite Reuses component
category: security
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The service-key mint log in admin.py wrote the caller-supplied label with %r. The todo said `Reuses: C-034` (`safe_line_text`) and warned not to copy the bootstrap log's %r pattern. The label has no length cap, so hostile text reached the logs (SI-2).

## Root cause
The implementer copied a nearby log line instead of calling the registered component named in the todo.

## Check
grep -n "logger\..*%r" agent_sdk/routes/admin.py and confirm no user-supplied field is logged raw; confirm `safe_line_text` is imported from `..common.redact` and used on `body.label`. Test: mint with a label of `\n`, `\x1b` and 5000 chars; assert caplog has the capped form and no raw newline.

## Prevention
When a todo has `Reuses: C-NNN` for a log or render slot, the landed line must import and call that component. A %r copy of a nearby log line counts as a second implementation. Planner: add an AC naming the import.
