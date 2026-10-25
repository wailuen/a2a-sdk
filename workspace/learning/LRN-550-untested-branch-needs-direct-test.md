---
id: LRN-550
title: Named untested path closed by a nearby success test
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-261 item 7 said the deferred-tool -32005 path is untested. The new tests in `tests/test_gh259_a2a_route.py` only hit the success path. Nothing drove `_run_deferred_background` into `apply_output_modes` raising -32005 (runner.py ~:1212).

## Root cause
A neighbouring success-path test was accepted as closing a specific untested-branch item.

## Check
`grep -n "32005" tests/test_gh259_a2a_route.py` must show a deferred (long_running) test asserting status.error.code -32005 and no artifacts.

## Prevention
When an issue item names an untested branch, plan a test that reaches that exact branch and name the branch in the AC. Success-path tests do not count.
