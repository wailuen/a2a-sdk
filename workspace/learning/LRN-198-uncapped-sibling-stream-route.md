---
id: LRN-198
title: Concurrency cap applied to one stream route, sibling route left uncapped
category: security
severity: high
source: redteam
date: 2026-08-19
---

## What happened
A concurrency cap added to `GET /mcp` left the identically-authenticated, identically-indefinite sibling `GET /mcp/sse` uncapped in the same module, so the DoS was bypassable by changing one path segment. Verified empirically: the 3rd concurrent `GET /mcp` from one identity got 429, while 12/12 concurrent `GET /mcp/sse` streams from the same identity were admitted and stayed live.

## Root cause
The cap was wired into one route handler instead of a shared live-stream budget; the sibling route still used evict-oldest, which drops only the bookkeeping entry, not the running generator/heartbeat loop, so it could not actually bound concurrency — and evict-oldest is also cross-tenant, since it pops entries regardless of owner.

## Check
`grep -n "StreamingResponse(" agent_sdk/routes/mcp.py` and confirm every match is preceded by the same admission check (shared `_get_streams()`/`_prune_get_streams()` call, reject-not-evict) before the response is constructed — no route should reach `StreamingResponse(` without first passing that gate.

## Prevention
When planning a concurrency/rate cap for any indefinite-stream endpoint, enumerate every route in the same module that returns a `StreamingResponse` and route all of them through one shared admission-control budget in the same change — never scope the cap or its tests to a single handler when sibling handlers emit the same kind of stream.
