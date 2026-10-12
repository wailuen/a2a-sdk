---
id: LRN-311
title: Provider-specific cap widening exceeds model limits, unratified
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
For tool_choice='none', openai_client.py (~391-406) sent max_completion_tokens = max_tokens + 25_000 (26,024 by default). The AC said min(max_tokens, cap) and the ruling said small output cap. gpt-4o and gpt-4o-mini allow 16,384, so the request returns 400 and the summary silently becomes the fixed notice; on non-reasoning models the cap is effectively unlimited. app.py:379-388 never passes max_completion_tokens, so env operators cannot override it (LRN-156/LRN-222).

## Root cause
Headroom for reasoning models was applied to every model, unreachable from settings and never ratified into the AC.

## Check
Verify a test that the summary request stays <= 16,384 for a non-reasoning model. grep app.py for max_completion_tokens and reasoning_effort passed from BaseAgentSettings.

## Prevention
When widening a ruling-mandated cap per provider, apply it only to reasoning deployments, keep it within every accepted model's limit, expose it via settings, and ratify it on the GH issue.
