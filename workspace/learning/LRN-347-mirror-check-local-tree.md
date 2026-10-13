---
id: LRN-347
title: Mirror byte-identity test compares local tree, not pushed commit
category: testing
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-164 required the template repo to be pushed. The bare-path scan fix existed only as an uncommitted edit in `template/.claude/workflows/wave-cycle.js`; pushed commit a7bd017 still had the old scan. `test_gh164_workflow_copies_are_byte_identical` passed because it read the working tree.

## Root cause
The sync test checks local files, so unpushed edits pass as synced.

## Check
Run `git -C template status --porcelain` (must list no mirrored file), `git -C template diff origin/main -- .claude/workflows/wave-cycle.js` (must be empty), and confirm the branch is not ahead of origin.

## Prevention
When a wave mirrors files into template/, plan a commit-and-push step and an archive gate comparing against origin/main, not the working tree.
