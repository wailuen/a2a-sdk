---
id: LRN-314
title: Harness skill edit missing template mirror
category: ops
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-157/158 edited ag-ui-check, add-artifact and new-agent skills in harness/ and .claude/, but not in `template/.claude/skills/`. `git -C template status` was clean, so no peer-repo commit existed. Downstream agents kept the stale rule and never learned about `mcp_instructions`. Same pattern as LRN-208/271/276.

## Root cause
The template mirror is a separate repo and was not part of the edit checklist.

## Check
For each edited skill `<s>`: `diff harness/skills/<s>/SKILL.md template/.claude/skills/<s>/SKILL.md` shows no GH hunks, and `git -C template log -1` shows the commit.

## Prevention
When planning any harness skill edit, add an explicit task to apply the same hunk to `template/.claude/skills/` and commit in the template repo (LRN-071, never `git add template/` in a2a-sdk) before /sdk-release.
