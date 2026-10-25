---
id: LRN-522
title: Parallel group changes serializer fallback, another group's tests still pin old output
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-251 (G1) made `_tool_json` in `agent_sdk/routes/ag_ui.py` replace NaN/inf per value (`{"x":null}`). Two tests in `tests/test_gh235_nested_json_and_resume.py` still asserted the old whole-result fallback, so the file reported 2 failed.

## Root cause
Tests pinning the old fallback output were not updated in the same wave as the serializer change.

## Check
Run `pytest tests/test_gh235_nested_json_and_resume.py` and confirm green. Confirm `grep -n "_RESULT_FALLBACK" tests/test_gh235_nested_json_and_resume.py` only appears in a test where `to_jsonable_python` raises.

## Prevention
When planning a group that changes a serializer's fallback or output shape, list every test file pinning that output (grep the old constant) and assign their update to the same group. Run each group's owned test files against the merged tree before signoff.
