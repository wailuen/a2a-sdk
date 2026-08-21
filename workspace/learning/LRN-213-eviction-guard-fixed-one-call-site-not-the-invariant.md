---
id: LRN-213
title: Live-subscriber eviction guard was added at one call site, not as the store's invariant
category: correctness
severity: high
source: agent-stack-check (ag-ui-advisor, pre-release /sdk-test Leg 3)
date: 2026-08-21
---

## What happened
RT-001 round 5 fixed `InMemoryTaskStore._evict_over_capacity()` so it never evicts a record with live subscribers, closing a real cross-tenant stream-severing bug. But `evict()` has two other unconditional callers in the same class — `get()`'s TTL/interrupt-deadline expiry check, and the periodic background `sweep()` — and neither got the same guard. `get()`'s path is reachable from `find_interrupt()` (AG-UI's `_resume_target_task_id` resume lookup), so a resume attempt for one interrupt walks every record and could silently evict an unrelated, still-live-streamed task that simply hadn't been touched recently enough to dodge its TTL. Caught by the AG-UI protocol advisor during the pre-release conformance audit, not by the redteam round that shipped the original fix.

## Root cause
The fix was scoped to the one call site the reproducing test exercised (capacity overflow via `create()`), not to the invariant it was actually establishing ("evict() must never be called on a record with a live subscriber, regardless of why eviction was triggered"). `evict()` itself has no such guard — it's the callers' job, and there were three of them, not one.

## Check
`grep -n "self.evict(" agent_sdk/tasks/memory.py` and confirm every call site first does `self.reap_dead_subscriptions(record)` then checks `if record.subscriptions: continue`/skip before calling `evict()` — no caller should reach `evict()` without passing that gate.

## Prevention
When a fix adds a guard in front of a shared, destructive method (here `evict()`), grep every call site of that method in the same class/module and apply the guard uniformly — never scope the fix (or its regression test) to just the call site the original repro happened to hit. This is the same lesson as [[LRN-198-uncapped-sibling-stream-route]] one layer down: a cap/guard fixed for one route/call-site and left off its siblings is bypassable by reaching the store through a different door.
