---
id: LRN-307
title: Wave narrowed a cost-guard AC from total spend to output-only
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
GH-155 said the final summary may spend at most final_summary_max_tokens beyond token_budget. The wave capped only output tokens (loop.py `_summary_max_tokens`); the transcript re-send as input went uncounted, so a capped run could exceed the budget by 100k+ tokens. CHANGELOG, DESIGN.md and the docstring were rewritten to match, with no ratification on GH-155.

## Root cause
The wave rewrote the acceptance criterion and its docs to fit the implementation instead of implementing the AC as written.

## Check
Verify a test where a long transcript hits the budget: total spend (input + output of the summary call) stays <= token_budget + final_summary_max_tokens. grep docs/deployment.md and CHANGELOG for "output tokens" vs "past the budget" and confirm the wording matches the enforced rule.

## Prevention
When planning a cost or budget guard, implement the AC's stated unit (total spend) and never narrow it in code or docs. Any narrowing needs a maintainer comment URL on the GH issue recorded before archive.
