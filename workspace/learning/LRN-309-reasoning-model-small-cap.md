---
id: LRN-309
title: Small token cap on a reasoning model returns empty output
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
The GH-155 summary call set max_completion_tokens to min(max_tokens, cap), 1024 by default (openai_client.py ~122-128). The module docstring (lines 14-17) already warns that a small cap is consumed by gpt-5 reasoning and returns an empty completion. On the OpenAI/Azure gpt-5 backend the summary comes back empty and the user gets the fixed notice.

## Root cause
A new code path ignored an invariant documented in the same module.

## Check
Verify a test that sets reasoning_effort and asserts the tool_choice='none' request's reasoning_effort and max_completion_tokens leave reasoning headroom. grep openai_client.py for a warning on empty content with finish_reason 'length'.

## Prevention
When planning any new low-cap model call, read the client module's docstring invariants first. For reasoning models, plan lowest reasoning_effort or headroom, plus a test of the exact request.
