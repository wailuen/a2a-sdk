---
id: LRN-193
title: Generator finally is not a lifecycle hook for pre-stream admission slots
category: security
severity: critical
source: redteam
date: 2026-08-19
---

## What happened
`GET /mcp` (agent_sdk/routes/mcp.py:766) registers a `mcp_get_streams` cap slot
before the `StreamingResponse` is built, but the only release is the
`heartbeats()` generator's `finally` (mcp.py:782). When uvicorn cancels the
stream before the generator body starts (spec_version<2.4 disconnect at the
`http.response.start` `send()` checkpoint), that `finally` never runs. The
slot leaks permanently — no TTL, no prune, no eviction — so repeated
early-aborts lock out one identity (429) or, at scale, every tenant (500)
until process restart.

## Root cause
An admission slot's release was coupled only to a generator body executing
to completion/exception, not to the response's actual lifecycle; the code
assumed "stream starts" and "stream ends" are guaranteed paired events, but
ASGI can cancel between accept and first-chunk pull.

## Check
Grep `agent_sdk/routes/mcp.py` for any `_get_streams[...]  = ` or
`.add(` / registration call that precedes `StreamingResponse(` construction,
and confirm the matching release is reachable via more than the streaming
generator's own `finally` (e.g. `BackgroundTask`, or a TTL/prune sweep like
`_prune_sessions` at mcp.py:159-164). Regression test: drive a raw ASGI
`GET /mcp` whose `send()` suspends at `http.response.start` while the client
disconnects before the generator's `async for` runs; assert
`len(_get_streams(app)) == 0` after the request completes.

## Prevention
When planning any capacity-limited streaming/subscription endpoint, require
that admission-slot release be attached to the response lifecycle itself
(e.g. `StreamingResponse(..., background=BackgroundTask(release))`) or backed
by a TTL+prune/evict-oldest sweep on every admission — never solely a
`finally` inside the streamed generator, since ASGI can cancel before that
generator body ever begins.
