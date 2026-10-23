---
id: LRN-452
title: Mirror-pushed test keyed to upstream hides undelivered mirror
category: ops
severity: high
source: redteam
date: 2026-10-22
---

## What happened
The GH-208 template mirror (commit 53a62d7) sat only on origin/feat/gh210-acceptance-turn-helper with no PR; `git -C template diff --stat origin/main -- .claude/workflows/wave-cycle.js` showed 305 changed lines. `test_gh164_template_mirror_is_committed_and_pushed` still passed.

## Root cause
The test compares against `@{upstream}`, which is the feature branch on the local template checkout, not origin/main.

## Check
`grep -n "upstream" tests/test_wave_scope_extraction.py` shows `@{upstream}` is not used; the test diffs against `origin/main`. Run `git -C template diff --stat origin/main -- .claude/workflows/wave-cycle.js` and confirm empty.

## Prevention
When planning template-mirror work, define "pushed" as reachable from the template's origin/main, and include a merged template PR as a deliverable. Never key delivery tests to `@{upstream}`.
