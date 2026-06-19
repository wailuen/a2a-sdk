---
id: LRN-088
title: Inbound client Message mutated with server-assigned IDs before history storage
category: protocol
severity: high
source: redteam
date: 2026-06-15
---

## What happened
`_create_task_record` (a2a.py:164-167) writes `msg.task_id` and `msg.context_id` directly onto the inbound client `Message` object, then stores that same mutated object as `task.history = [msg]`. `_resume_or_error` (line 197) repeats the pattern for `msg.context_id` before appending to history (line 203). This violates LRN-048, which forbids mutating the inbound request `Message` after validation and forbids `role='user'` history entries carrying server-assigned IDs.

## Root cause
History construction reused the already-parsed `params.message` object instead of constructing a separate record, conflating client-sent vs server-emitted `Message` semantics (A2A §3).

## Check
`grep -n "msg\.task_id\s*=\|msg\.context_id\s*=" agent_sdk/routes/a2a.py` must return zero matches; all hits should only be reads or target a freshly-constructed object (e.g. via `model_copy(update={...})`).

## Prevention
When planning any task/history construction logic, ensure inbound `params.message` is treated as read-only after validation. Archive a distinct copy (e.g. `msg.model_copy(update={"task_id": task.id, "context_id": task.context_id})`) for history storage; never assign server-generated IDs back onto the original request object.
