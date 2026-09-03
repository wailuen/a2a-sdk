---
id: LRN-211
title: Admission cap wired into one router module, sibling module's streams left unbounded
category: security
severity: high
source: redteam
date: 2026-08-19
---

## What happened
GH-143's DoS fix added a shared admission budget for indefinite SSE streams in `agent_sdk/routes/mcp.py`, but `POST /v1/tasks/{task_id}:subscribe` and `POST /v1/message:stream` in `agent_sdk/routes/a2a.py` still return authenticated, indefinitely-held streams on the same single-process connection pool with no accounting — `tasks_resubscribe` can be called unboundedly against one task, appending a `Subscription` every time, since `reap_dead_subscriptions` only reclaims orphans of a *done* task, never bounding live subscribers.

## Root cause
The admission budget was wired to the route family where the DoS was first reported (MCP GET streams), not to the shared resource class it protects (process-wide open-stream slots), so a second route family in a different module holding that same resource open indefinitely was never connected to it.

## Check
`grep -n "StreamingResponse(" agent_sdk/routes/a2a.py` and confirm every match (`message:stream`, `tasks:subscribe`) is preceded by the same admission-control call used in `agent_sdk/routes/mcp.py` (or an equivalent budget), enforced before the response is constructed. Also confirm `record.subscriptions` growth is capped per-task/globally, not just reaped post-completion.

## Prevention
When planning a concurrency/admission cap for a shared finite resource (event loop, single-process connection pool), enumerate every route across *every* router module that returns a long-lived streaming response over that resource — not just the module where the DoS report originated — and route them all through one shared budget in the same change, or explicitly document the exemption.
