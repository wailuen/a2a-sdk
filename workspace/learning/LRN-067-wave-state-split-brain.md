---
id: LRN-067
title: Wave state split-brain — plan.md and todo file disagree on critical item status
category: ops
severity: high
source: redteam
date: 2026-06-18
---

## What happened
A critical security AC (GH-66: ADR-001 credential files gitignore glob missing) was partially reopened by changing `[x]` to `[ ]` in `workspace/todos/completed/w019-gh-issues.md` after the acceptance check was found to have inspected SDK-internal files instead of a scaffolded agent repo. Despite the reopening, `plan.md` still showed `W19 [x] ✅ 2026-06-18` and the todo file remained in `completed/` rather than `active/`. The result was a critical-severity security item simultaneously marked done and open depending on which artifact was read.

## Root cause
The wave close-out procedure updated only one artifact (the todo checklist) when an AC was invalidated, leaving `plan.md` and the `completed/` directory placement out of sync. No atomic rule enforced that reopening a single AC must propagate to all three state holders.

## Check
Run: `grep -r '\[x\].*GH-66\|W19.*\[x\]' workspace/todos/completed/ workspace/todos/plan.md` and confirm no completed marker exists while a corresponding `[ ]` AC remains open in any file. Also verify: any todo in `completed/` has no unchecked `[ ]` ACs inside it.

## Prevention
When planning a wave close-out or partial reopen, ensure all three state holders are updated atomically: (1) flip the AC checkbox, (2) move the todo file from `completed/` back to `active/` if any AC is unchecked, and (3) downgrade the `plan.md` row from `[x]` to `[ ]` with a note. A critical-severity item must never show `[x]` in `plan.md` while any of its ACs remains open.
