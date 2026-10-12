---
id: LRN-299
title: Feature never fires under default policy values
category: testing
severity: high
source: redteam
date: 2026-10-11
---

## What happened
With default `LoopPolicies()`, the token-budget exit could never make the summary call: want = 1024 = final_summary_max_tokens, so the skip condition was always true. Tests passed only because they set `final_summary_max_tokens=3000` and `max_output_tokens=500`. DESIGN.md and CHANGELOG claimed a summary call that the default config never made.

## Root cause
Tests used tuned knobs, so the default-configuration path was never exercised.

## Check
Confirm a test runs the budget exit with bare `LoopPolicies()` and asserts summary or notice. Confirm DESIGN.md (~line 469) and CHANGELOG match the observed behavior.

## Prevention
When planning a feature gated by policy knobs, require at least one test using default policy values. Docs claims must be backed by that default-config test.
