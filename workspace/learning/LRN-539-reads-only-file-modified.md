---
id: LRN-539
title: Field added to a Reads-only file escapes scope gates
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-259 added `accepted_output_modes` to TaskRecord in agent_sdk/tasks/store.py, but listed that file only under `Reads:`. Five test files (test_gh177, test_gh179, test_rt001_strict_required_nullable_output, test_rt003, test_rt005) were edited to absorb GH-258/GH-255 changes and sat outside every todo's scope.

## Root cause
Todos declared files by expected role at plan time and were not updated when implementation touched more; scope gates only saw declared files.

## Check
Verify that every path in `git diff --name-only` appears under a todo's Creates/Modifies, not only Reads (LRN-520).

## Prevention
When planning, list as Modifies any file that gains a public field, and list tests likely to absorb a behavior change under Creates/Modifies. The phase gate must diff against declared paths.
