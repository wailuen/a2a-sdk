---
id: LRN-331
title: Git stash/reset in shared wave tree wipes other groups
category: ops
severity: critical
source: redteam
date: 2026-10-13
---

## What happened
Repeated `git stash` (reflog "reset: moving to HEAD" five times) in the shared working tree dropped 21 files of uncommitted G1 work into dangling stashes 956125b and e7fe843. Only untracked tests survived, and the template peer repo diverged.

## Root cause
Wave agents share one working tree, and nothing forbade stash/reset or checked that declared files changed.

## Check
`grep -nE "git (stash|reset|checkout --|restore)" .claude/workflows/*.js harness/workflows/*.js` must show only prohibitions. Post-group gate must fail when a path in allScope has no diff.

## Prevention
Ban git stash, reset, checkout -- and restore in implement and fix prompts. Edit in place or use a worktree. Gate each group on a diff for every declared path.
