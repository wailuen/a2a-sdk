---
id: LRN-360
title: Reject non-finite JSON at every protocol ingress
category: protocol
severity: high
source: redteam
date: 2026-10-15
---

## What happened
After `sse_data` got `allow_nan=False`, AG-UI got a `parse_constant` guard but A2A (`a2a.py` json.loads) and MCP did not. POSTing `NaN` in message metadata to `/v1/message:stream` raised ValueError at the first frame: no final:true frame, task kept running.

## Root cause
The ingress guard was added to one surface only, and A2A `gen()` did not wrap `sse_data` failures.

## Check
`grep -rn "json.loads" agent_sdk/routes/` and confirm each passes `parse_constant=`. Test: POST NaN metadata to `/v1/message:stream`, assert 4xx parse error or exactly one final frame.

## Prevention
Put the non-finite rejection in a shared helper in `agent_sdk/common/`. Plan its use on A2A, AG-UI and MCP together with any serializer tightening.
