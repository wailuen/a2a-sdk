---
id: LRN-465
title: CHANGELOG template SHA taken before final fix round
category: ops
severity: high
source: redteam
date: 2026-10-23
---

## What happened
The GH-223 CHANGELOG entry cited template commit 2ccf3ac, but template/.claude/workflows/wave-cycle.js had later uncommitted fixes. The pushed template shipped the weaker filer, and the commit was only on a feature branch, not origin/main.

## Root cause
The template SHA was recorded before the last redteam fix round; later harness edits re-dirtied the mirror.

## Check
Run `git -C template status --short` (expect empty), `git -C template diff --stat origin/main -- .claude/workflows/wave-cycle.js` (expect empty), and tests/test_wave_scope_extraction.py::test_gh164_template_mirror_is_committed_and_pushed.

## Prevention
When planning a wave touching harness files, make the template commit/push and the CHANGELOG SHA the last step after all fix rounds, re-taken if any harness file changes afterwards.
