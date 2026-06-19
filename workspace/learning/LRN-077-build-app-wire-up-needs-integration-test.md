---
id: LRN-077
title: Wire-up fixes in build_app() need their own integration test at the app.state seam
category: testing
severity: medium
source: redteam
date: 2026-06-19
---

## What happened
`settings.max_output_tokens` was wired into `LoopPolicies` inside `build_app()` as a fix (RT-004), but no test covered the integration seam (`app.state.loop_policies.max_output_tokens == settings.max_output_tokens`). `test_loop.py` covered `LoopPolicies` internals and the settings default, but not the `build_app()` assignment. The seam could silently regress without any test failure.

## Root cause
The fix arrived as scope creep on an unrelated wave with no AC and no integration-point test. `test_loop.py` unit tests stop at `LoopPolicies(max_output_tokens=X)` — they do not exercise the path where `build_app()` reads from `settings` and passes the value through.

## Check
`grep -n "loop_policies" tests/test_loop.py` must show a test that calls `build_app()` and asserts `app.state.loop_policies.max_output_tokens == custom_tokens`.

## Prevention
When planning any fix that forwards a settings field into a downstream construct inside `build_app()`, ensure an integration test asserts `app.state.<construct>.<field> == settings.<field>` after calling `build_app()`. Inject `FakeModelClient` into the `Agent` constructor to bypass `_build_model_client()` in tests that do not exercise the model layer.
