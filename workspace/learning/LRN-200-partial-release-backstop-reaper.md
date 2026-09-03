---
id: LRN-200
title: Backstop reaper reclaims only half of a release surface
category: sdk
severity: high
source: redteam
date: 2026-08-19
---

## What happened
`agent_sdk/routes/mcp.py` deleted the hard bound on `mcp_sse_queues`
while its prune function popped only `mcp_get_streams`, though
`release()` owns both. A cancelled GET /mcp/sse request left `streams`
at 0 but `queues` at 1, leaking an unbounded `asyncio.Queue` per
occurrence.

## Root cause
The reaper's reclaim set matched an old, narrower release surface and
wasn't updated when a second dict joined it; dropping the hard bound in
the same change turned a partial leak into an unbounded one.

## Check
`grep -n "_prune_get_streams\|_sse_queues\|_get_streams"
agent_sdk/routes/mcp.py` — confirm prune drains every dict any
`release()` closure writes to, not just the one it iterates. Confirm
any hard bound/TTL removed alongside it is restored, or proven
redundant by a test cancelling the owning task and asserting all
co-owned collections empty.

## Prevention
When a reaper reclaims release-owned state, grep the release callback
and require coverage of every collection it touches, not just the one
under discussion. Deleting a pre-existing hard bound/TTL in the same
change requires proof the backstop now covers 100% of what it
protected.
