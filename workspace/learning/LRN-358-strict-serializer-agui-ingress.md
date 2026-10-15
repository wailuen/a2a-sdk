---
id: LRN-358
title: Strict serializer kills AG-UI stream on raw client JSON
category: protocol
severity: high
source: redteam
date: 2026-10-15
---

## What happened
`sse_data` gained `allow_nan=False`. AG-UI `_parse_body` used plain `json.loads`, which accepts `NaN`. A body with `"state":{"x":NaN}` made the STATE_SNAPSHOT `sse_data` call raise outside the try block, so the stream died after RUN_STARTED with no RUN_ERROR.

## Root cause
Serializer was tightened without rejecting non-finite values at ingress, and the snapshot yield sat outside the RUN_ERROR guard.

## Check
Run a test posting raw body `{"state":{"x":NaN}}` to `/ag-ui/run`. Assert pre-stream 4xx, or RUN_STARTED followed by exactly one terminal frame. `grep -n "parse_constant" agent_sdk/routes/ag_ui.py`.

## Prevention
When tightening `sse_data`, list every caller that echoes request data. Put each such frame inside the RUN_ERROR try block, and add a raw-body test.
