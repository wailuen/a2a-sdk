---
id: LRN-203
title: Safety invariant lives in one ABC subclass, not contracted
category: sdk
severity: high
source: redteam
date: 2026-08-19
---

## What happened
`_open_stream` (`agent_sdk/routes/a2a.py`) relies on a dead-subscription reap that exists
only in `InMemoryTaskStore.subscribe`. Abstract `TaskStore.subscribe`
(`agent_sdk/tasks/store.py:111`) is a bare `...`, no docstring — the documented extension
point (`Agent(task_store=...)`) states no such obligation.

## Root cause
The leak-safety fix landed in the concrete class where the bug surfaced, never hoisted onto
the abstract interface every implementation must satisfy.

## Check
`TaskStore.subscribe` docstring must state the no-unbounded-growth obligation. Grep tests
for a conformance case parametrized over `TaskStore` subclasses (not just
`InMemoryTaskStore`) asserting subscriptions don't accumulate across `publish`.

## Prevention
When a route's safety guarantee depends on one impl of a public ABC, put the obligation on
the ABC (docstring/shared helper) plus a subclass-parametrized conformance test — never
leave it living only in the fixed instance.
