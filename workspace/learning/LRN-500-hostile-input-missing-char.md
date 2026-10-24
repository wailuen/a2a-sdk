---
id: LRN-500
title: Absence assertion on a char never put in the input
category: testing
severity: high
source: redteam
date: 2026-10-24
---

## What happened
The AC asked for U+2028, `\x85` and `\x9b` to be added to `HOSTILE_STANDALONE` in `tests/test_gh212_id_safe_text.py`. They were not added. The assertion at line 164 (`ch not in text` for `\r\x07\x1b\x85\x9b`) is always true for those characters, so it cannot fail (same dead check as GH-242).

## Root cause
The assertion was extended without extending the hostile input it checks.

## Check
Verify that every character in a `ch not in text` loop also appears in the hostile input constant (`grep -n "HOSTILE_STANDALONE" tests/test_gh212_id_safe_text.py`), and that the test fails when `safe_id_text` stops neutralising C1 or U+2028.

## Prevention
When planning tests that assert a hostile character is absent, require the same character in the input, and require a mutation check that the test fails without the sanitiser.
