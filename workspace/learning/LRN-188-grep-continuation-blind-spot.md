---
id: LRN-188
title: Grep-path guard blind to backslash-continued commands
category: testing
severity: high
source: redteam
date: 2026-08-15
---

## What happened
The LRN dead-path guard required each physical line to start with
`grep`, so backslash-continued file args were never scanned.
`_extract_check_grep_paths` returned `[]` for LRN-028/036/037, so the
guard stayed green while those Checks still grep the nonexistent
`template/.claude/workflows/wave-cycle.js`.

## Root cause
Regex anchored on `^\s*grep\b` matches per physical line; a
continuation line never starts with `grep`, so it's dropped instead of
joined into the logical command first.

## Check
`tests/test_learning_index.py::test_extract_check_grep_paths_joins_backslash_continued_lines`
passes; extraction returns every path token, not just the last.

## Prevention
A guard parsing shell snippets from prose must join backslash
continuations before line-anchored regex matching, and scan every
path token in a multi-file command, not just the trailing one.
