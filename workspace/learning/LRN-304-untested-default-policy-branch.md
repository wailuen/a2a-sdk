---
id: LRN-304
title: Cap formulas must be tested at default policy and settings
category: testing
severity: high
source: redteam
date: 2026-10-11
---

## What happened
With default `LoopPolicies()`, the budget-exit summary never ran: remaining < cap always, so `_summary_max_tokens` returned 0 and the fixed notice was sent. `final_summary_max_tokens` had no settings/env field, though docs told operators to raise it. All tests hand-built `LoopPolicies(...)` with large values.

## Root cause
Tests used tuned policies, hiding a branch dead under production defaults; a documented knob had no operator-facing setting.

## Check
Verify an end-to-end test builds the app with default settings, crosses `token_budget` slightly, and asserts the A2A status.message holds a model summary. grep `app.py` for `final_summary_max_tokens` and `config.py` for `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS`.

## Prevention
When planning a cap or limit formula, require at least one test at default values via settings. Every knob docs tell operators to change must have a settings/env field passed in `app.py`.
