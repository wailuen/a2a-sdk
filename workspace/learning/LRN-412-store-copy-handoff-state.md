---
id: LRN-412
title: Handoff state on TaskRecord lost by copy-on-get stores
category: sdk
severity: high
source: redteam
date: 2026-10-17
---

## What happened
GH-185 added public field `TaskRecord.resume_identity`, set on the object returned by `store.get()`/`find_interrupt()`. The TaskStore contract lets a durable subclass return a fresh copy per get(), so the route wrote a copy while the worker read its own live record and the identity was silently lost.

## Root cause
Cross-component handoff state was stored on a record whose identity the store contract does not guarantee, with no DESIGN.md section 5 durability statement.

## Check
Grep `agent_sdk/tasks/store.py` for new `TaskRecord` fields set by routes (e.g. `resume_identity`). Confirm each is either absent or documented in DESIGN.md section 5 and the TaskStore docstring, and that a fresh-copy store test exists in `tests/`.

## Prevention
When planning a handoff between route and worker, pass it through a channel the store already relays (the `deliver_resume` value), not a new TaskRecord field. If a field is unavoidable, the todo must include the DESIGN.md section 5 note and a copy-on-get store test.
