---
id: LRN-549
title: Listed low items skipped when ruling says fix as listed
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-261 item 7 low was left undone. `apply_output_modes` in `agent_sdk/agent/runner.py` (~:447) kept the dead `texts = [... TextPart ...]` line, and a FilePart-only artifact still got `TextPart(text="")` instead of a -32005 error.

## Root cause
The ruling said "the lows as listed", but the diff was not checked item by item.

## Check
`grep -n "isinstance(p, TextPart)" agent_sdk/agent/runner.py` must not match inside the apply_output_modes fallback, and a unit test for a FilePart-only artifact must assert -32005.

## Prevention
When a ruling covers "lows as listed", write one AC per low, each naming its code change or test. Sign off only after ticking them one by one.
