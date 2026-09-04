---
id: LRN-187
title: Doc-file AC verified against working tree, not the landing commit
category: ops
severity: high
source: redteam
date: 2026-09-03
---

## What happened
A wave archived at 231e370 with two GH ACs requiring specific CHANGELOG.md
entries. Both entries exist only as uncommitted working-tree edits — `git show
231e370:CHANGELOG.md` has no trace of them, alongside related uncommitted
DESIGN.md and pyproject.toml changes.

## Root cause
The archive check read the working tree to confirm the AC text existed,
instead of the landing commit's actual committed content — an uncommitted
draft was accepted as a landed AC.

## Check
For any doc-file AC, run `git show <landing-commit>:<path>` and grep for the
required text; never grep the working tree. Also run `git status --short` at
archive time and fail if it's non-empty for any file in the wave's scope.

## Prevention
When planning an archive/landing gate, require every AC that references a
file's content to be verified via `git show <commit>:<file>`, and add a
pre-archive check that the working tree is clean for all in-scope files.
