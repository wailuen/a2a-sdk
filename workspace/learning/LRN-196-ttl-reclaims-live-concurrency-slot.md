---
id: LRN-196
title: TTL backstop reclaims a still-live concurrency-cap slot under load
category: sdk
severity: high
source: redteam
date: 2026-08-19
---

## What happened
`_prune_get_streams` in `agent_sdk/routes/mcp.py` evicts a GET /mcp
stream's entry after `_GET_STREAM_TTL_SECONDS` (60s) since last touch.
`heartbeats()` touches only once per loop iteration, so a stream
backpressured on `send()` or overshooting `asyncio.sleep()` under
congestion — exactly the load `_MAX_GET_STREAMS` bounds — gets pruned
mid-flight, then resurrects its entry next tick, so `len(streams)` can
exceed the cap too.

## Root cause
Eviction keys on wall-clock elapsed time, not a liveness fact; under
congestion the two diverge.

## Check
grep `_GET_STREAM_TTL_SECONDS`/`_prune_get_streams` in
`agent_sdk/routes/mcp.py`; confirm reclamation gates on `task.done()`
(captured at stream start), not TTL alone. Require a regression test:
open GET /mcp responses never exceed `_MAX_GET_STREAMS` when a
stream's touch is delayed past the TTL.

## Prevention
When planning an admission-capped, long-lived resource pool, require
release keyed on a liveness fact (owning task `.done()`, disconnect
callback) — never a wall-clock TTL alone bounding the load it must
survive.
