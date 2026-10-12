---
id: LRN-305
title: Model client must not add unconfigured provider parameters
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
`openai_client.py` sent `reasoning_effort="minimal"` on every summary call, even when the operator set none. `OPENAI_MODEL` is free-form and `OPENAI_BASE_URL` allows compatible servers, so gpt-4o/4.1, o-series and third-party endpoints return 400. The broad `except` in `_final_summary` hid it as a silent fallback to the fixed notice.

## Root cause
A model-specific knob was injected unconditionally into a client that serves many models, and a catch-all fallback masked the failure.

## Check
Verify a test: a client built without `reasoning_effort` sends no `reasoning_effort` key when `tool_choice="none"`. grep `openai_client.py` for `reasoning_effort` and confirm every send is guarded by `self._reasoning_effort`.

## Prevention
When planning model-client changes, send provider parameters only if the operator configured them. Test the unset case and log (not swallow) fallback causes.
