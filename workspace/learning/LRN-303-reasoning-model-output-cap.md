---
id: LRN-303
title: Output caps on reasoning models must leave room for reasoning
category: sdk
severity: high
source: redteam
date: 2026-10-11
---

## What happened
On summary calls (`tool_choice == "none"`) `openai_client.py` forced `max_completion_tokens` to at most 1024 while still sending `reasoning_effort`. The module docstring warns small caps get consumed by reasoning and return empty content. `_final_summary` then silently fell back to the fixed notice. No test caught it.

## Root cause
The AC cap was applied literally without checking the client's documented limits; fakes never model reasoning tokens.

## Check
Run a test where the fake returns `finish_reason="length"` with empty content on a summary call and assert the chosen strategy (low effort or extra reasoning allowance). grep `openai_client.py` for the summary-path `max_completion_tokens`.

## Prevention
When planning any per-call output cap on a reasoning-capable client, require a reasoning allowance or lowered effort, a test with empty-length completions, and a DESIGN note on the trade-off.
