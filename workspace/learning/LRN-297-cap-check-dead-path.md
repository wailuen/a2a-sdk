---
id: LRN-297
title: Cap check charging input re-send makes budget summary dead code
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
GH-155 budget-exit summary (`_summary_max_tokens`, loop.py) subtracted `last_input_tokens` from a 1024-token allowance although cumulative `total_tokens` already includes it and is past budget. Any realistic input (>1024) gave 0 output tokens, so the fixed notice always shipped. `test_realistic_overshoot_uses_notice_not_call` locked in the dead path.

## Root cause
Allowance arithmetic double-counted the transcript re-send against a tiny fixed allowance, and the test asserted the failure as intended behavior.

## Check
Run a budget exit with budget 200000, total 200500, last input 20000: confirm a summary model call is made (tests/test_gh155_cap_summary.py). grep tests for `uses_notice_not_call` and confirm no match.

## Prevention
When planning a cap-guarded fallback call, require a test with a realistic input size (>1024 tokens) and small overshoot that reaches the happy path. Never write a test that asserts the feature is skipped in the realistic case.
