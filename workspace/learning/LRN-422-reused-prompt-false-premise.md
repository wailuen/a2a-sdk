---
id: LRN-422
title: Reused helper prompt text states false premise for new trigger
category: sdk
severity: high
source: redteam
date: 2026-10-17
---

## What happened
GH-194 `_empty_reply_retry` reused `_summary_request_messages`, which injects `_FINAL_SUMMARY_INSTRUCTION` ("You have reached the limit... can call no more tools"). The retry runs by default when no limit was hit, so the model was told something false and replies could claim incompleteness. The test checked only `tool_choice`, not the text.

## Root cause
A helper with built-in prompt text was reused for a different trigger without checking the text was still true.

## Check
Test that the retry call's last user block contains the empty-reply instruction and not "reached the limit". `grep -n "_EMPTY_REPLY_INSTRUCTION" agent_sdk/agent/loop.py` must match.

## Prevention
When a new model-call path reuses another feature's helper, plan an explicit review of the helper's prompt text and require a test asserting the request text, not only call parameters.
