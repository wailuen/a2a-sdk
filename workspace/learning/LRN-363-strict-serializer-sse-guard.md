---
id: LRN-363
title: Stricter SSE serializer needs terminal-frame guard in every generator
category: protocol
severity: high
source: redteam
date: 2026-10-15
---

## What happened
sse_data switched to allow_nan=False. AG-UI _run() yields STATE_SNAPSHOT from client state outside the try block, so a non-finite value raised ValueError after RUN_STARTED and cut the stream with no RUN_ERROR or RUN_FINISHED. A2A got a tail guard; AG-UI did not.

## Root cause
The serializer change was guarded on the surface the wave focused on only. This broke the one-terminal-frame rule (LRN-114).

## Check
Run a test posting state {"x":1e999} (or NaN float frame) to /ag-ui/run and assert exactly one terminal frame. `grep -n "sse_data" agent_sdk/routes/ag_ui.py` and confirm each call is inside a ValueError-catching guard.

## Prevention
When planning a stricter shared serializer, list every SSE generator using it and require a catch-to-terminal-frame guard plus a test for each.
