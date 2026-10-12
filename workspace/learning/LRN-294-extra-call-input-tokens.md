---
id: LRN-294
title: Spend cap on extra model call ignores its input tokens
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
The token-budget exit in loop.py capped only the summary call's output tokens, but the budget counts input plus output and the call re-sends the whole transcript. With budget=200000, an overshoot to 215000 skipped the summary, and a landing at 200500 ended at 401500 spent. The test hid this because the fake reply reported 0 input tokens.

## Root cause
The gate modelled max_tokens as the whole cost of the call, and the test double reported unrealistic usage.

## Check
Verify a test where the summary reply reports realistic input_tokens asserts total spend <= token_budget + final_summary_max_tokens, and one where a realistic overshoot still yields a summary: `grep -n "input_tokens" tests/test_gh155_cap_summary.py`.

## Prevention
When planning a spend cap on an extra model call, require the gate to include the estimated input cost (last response.input_tokens) plus max_tokens. Require fake replies in tests to report realistic input_tokens.
