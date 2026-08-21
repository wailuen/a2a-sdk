---
id: LRN-206
title: Route safety invariant relies on one ABC subclass, not the contract
category: sdk
severity: high
source: redteam
date: 2026-08-19
---

## What happened
`_open_stream` in `agent_sdk/routes/a2a.py` depends on orphan-subscription
reaping that only `InMemoryTaskStore.subscribe` performs
(`agent_sdk/tasks/memory.py:78-90`). The abstract `TaskStore.subscribe`
(`agent_sdk/tasks/store.py:111`) is a bare ellipsis with no docstring, unlike
its sibling abstractmethods, so the obligation is invisible to implementers.

## Root cause
A leak-safety invariant was implemented inside one concrete subclass of a
documented public ABC (`TaskStore`, per LRN-113) instead of being stated on
the abstract contract or hoisted into shared code the route calls directly.

## Check
Verify `agent_sdk/tasks/store.py`'s abstract `subscribe` docstring states the
"drop subscriptions whose owner_task.done()" obligation, OR that the reap
logic is hoisted to a shared/base method or into `_open_stream` itself. Add
a store-conformance test (any `TaskStore` impl, including a minimal fake,
must not accumulate dead subscriptions after publish) and confirm it fails
against a subclass lacking the reap.

## Prevention
When planning a fix whose correctness depends on behavior inside a single
subclass of a documented public ABC (docs/deployment.md, DESIGN.md extension
points), require either: (a) the invariant stated in the ABC's abstract
docstring plus a cross-implementation conformance test, or (b) the logic
hoisted into shared/base code or the caller — never left as tribal knowledge
in one implementation.
