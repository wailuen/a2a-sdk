---
id: LRN-298
title: Output-only token cap does not bound total call spend
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
`_summary_max_tokens` capped only output tokens, but the summary call re-sends the whole transcript as input. A budget of 200,000 with spend 200,500 ended about 50% over budget. `last_input_tokens` was set but never read, and the test only asserted `spent > 0`.

## Root cause
An allowance meant to bound cost was applied to output alone; the implementer redefined the AC in CHANGELOG prose without a maintainer ruling.

## Check
Verify `test_budget_summary_output_stays_within_allowance` asserts total spend (input + output) <= token_budget + final_summary_max_tokens. grep loop.py: `last_input_tokens` must be both set and read.

## Prevention
When planning any budget or allowance, state whether it bounds input plus output. Require the test to assert total spend. If the AC is reinterpreted, get a recorded ruling first and update the todo and DESIGN.md.
