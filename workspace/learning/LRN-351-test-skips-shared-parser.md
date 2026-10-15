---
id: LRN-351
title: Test inspects raw strings instead of calling shared parser verdict
category: testing
severity: high
source: redteam
date: 2026-10-15
---

## What happened
GH-171 required the fallback schema summary to work with the shared C-020 parser. `_field_summary` put the optional marker on the type (`b: str|null?`), so `required_paths` saw every field as required. The new test only checked `endswith('?')` on parsed values and passed green.

## Root cause
The test asserted on raw string shape, never calling the shared parser's verdict function (`required_paths`), so a notation mismatch went unseen.

## Check
grep `required_paths` in tests/test_gh171_fallback_schema_required.py and confirm it asserts `== {'a','c'}` for `_Gh171Card`. Confirm `_field_summary` emits `name?: type` (marker on key).

## Prevention
When planning a todo whose AC names a shared test parser (e.g. C-020), require the test to call that parser's verdict function (`required_paths`), not inspect raw strings. Docs and CHANGELOG must show the same notation.
