---
id: LRN-306
title: Spend-cap promises must count input re-send tokens
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
`_summary_max_tokens` (loop.py) capped only summary OUTPUT, yet the call re-sends the whole transcript (often 100k+ input tokens). `docs/deployment.md` promised "at most AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS past the budget", which is false. The `estimated_input_tokens` parameter and `last_call_tokens` were dead code, and two comments contradicted each other.

## Root cause
An output-only cap was presented as a spend cap, from a half-reverted design.

## Check
grep loop.py for `estimated_input_tokens` and confirm it is read in `_summary_max_tokens`. Verify a test where a large transcript skips the call. Confirm docs/DESIGN/CHANGELOG wording matches the implemented accounting.

## Prevention
When planning a budget guard, define "at most N past the budget" as total billed tokens (input plus output), or get the user to ratify output-only. Remove unused parameters.
