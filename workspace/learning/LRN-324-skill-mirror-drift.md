---
id: LRN-324
title: Identical-copies AC checked by grep, not whole-file diff
category: testing
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-157 required harness skill mentions to be identical across copies. The new lines matched, but `harness/skills/new-agent/SKILL.md` differs from `template/.claude/skills/new-agent/SKILL.md` at lines 73, 80, 131-133 and 216-225 (uv sync/uv lock vs pip install). LRN-208's Check failed.

## Root cause
Only the newly added lines were compared. Older drift in the rest of the file went unseen.

## Check
`diff harness/skills/new-agent/SKILL.md template/.claude/skills/new-agent/SKILL.md` must print nothing. Repeat for every `harness/skills/*` file against its template mirror.

## Prevention
When a todo says "all copies identical", plan a whole-file diff test over every harness/skills/* and template mirror. A missing mirror must xfail visibly. Plan the template peer repo commit and push (LRN-071).
