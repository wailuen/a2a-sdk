---
id: LRN-290
title: Todo done while template peer-repo edit is uncommitted
category: ops
severity: high
source: redteam
date: 2026-10-10
---

## What happened
GH-152 edited `template/.claude/skills/setup/SKILL.md` (peer repo wailuen/a2a-agent-template) but left it uncommitted and unpushed. The todo was treated as complete, so downstream agents seeded from the template would miss the fail-closed rule and opt-out docs.

## Root cause
The template/ directory is a separate git repo that is not tracked by a2a-sdk, so the SDK's own git status and tests never show the pending change.

## Check
For any todo whose Creates list has a `template/` path, verify `git -C template status --short` prints nothing and `git -C template log origin/main -1` shows the todo's commit. Also confirm `git ls-files template/` returns 0 lines in a2a-sdk.

## Prevention
When planning a todo that creates or edits `template/` paths, add an explicit final AC: commit and push in the peer repo (`git -C template ...`), never stage template/ in a2a-sdk. Redteam runs this Check before sign-off.
