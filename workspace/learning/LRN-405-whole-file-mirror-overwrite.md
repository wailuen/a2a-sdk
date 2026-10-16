---
id: LRN-405
title: Whole-file skill sync to template wipes per-repo lines
category: ops
severity: high
source: redteam
date: 2026-10-16
---

## What happened
The template copy of the acceptance skill was made byte-identical to the harness copy. That removed the one intentional difference: the live `scriptPath` now pointed at `harness/workflows/acceptance-api.js`, which does not exist in agent repos. The change was also uncommitted in the template repo.

## Root cause
The sync was a whole-file copy with no allow-list of deliberate per-repo differences, and no commit/push step.

## Check
Verify `grep -n "scriptPath" template/.claude/skills/acceptance/SKILL.md` points at `.claude/workflows/acceptance-api.js`, `git -C template status --short` is empty, and `git -C template rev-list @{upstream}..HEAD --count` is 0.

## Prevention
When planning harness-to-template skill syncs, require a diff of the pair that keeps the allow-listed lines (workflow path), then commit and push the peer repo before closing the todo.
