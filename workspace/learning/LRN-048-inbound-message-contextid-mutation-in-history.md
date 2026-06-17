---
id: LRN-048
title: Inbound Message mutated with server-assigned taskId/contextId before archiving in history
category: protocol
severity: high
source: redteam
date: 2026-06-17
---

## Observation

At `agent_sdk/routes/a2a.py:183-186`, the route handler overwrites `msg.task_id` and `msg.context_id` on the caller's inbound `Message` object immediately after `new_task()` creates the task, then appends that mutated object to `new_t.history`. The same mutation occurs inside `_create_task_record` at lines 163-169. Because the A2A spec (§3) distinguishes client-sent Messages (contextId OPT) from server-emitted Messages (contextId REQUIRED), a `role='user'` Message stored in history with the server-assigned taskId/contextId is spec-unusual: consumers retrieving history will see a user-role message carrying server-generated identifiers, conflating the two semantic classes.

## Root Cause

The code reuses the inbound `Message` object as the history entry for convenience, mutating it in-place to attach the freshly-created task/context identifiers rather than constructing a separate record. There is no copy step before the mutation, so the original client-submitted field values are silently overwritten.

## Prevention

When planning any task-creation or message-archival path, ensure the inbound client `Message` is never mutated after validation. Archive the original object as received, or construct a distinct server-emitted `Message` with `role='agent'` (or a neutral audit record) to carry the server-assigned ids. The `Task` record itself already stores `contextId`; duplication onto the user-role history entry is unnecessary and spec-conflating.

## Check

grep -n "msg\.task_id\|msg\.context_id" agent_sdk/routes/a2a.py

Confirm every match is either a read (not a write assignment) or occurs only on a freshly constructed Message object, never on the inbound request Message after it has been received. Also verify that `new_t.history` entries with `role='user'` do not carry server-assigned `task_id` values that differ from any client-supplied value.
