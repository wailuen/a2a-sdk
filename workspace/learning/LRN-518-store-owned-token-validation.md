---
id: LRN-518
title: Route must not hard-code format of store-minted tokens
category: sdk
severity: high
source: redteam
date: 2026-10-24
---

## What happened
The route in `agent_sdk/routes/a2a.py` rejected any `pageToken` that was not 32-hex with 400 -32602. `TaskStore.list_tasks_for_identity` documents the token as opaque, and `Agent(task_store=...)` accepts custom stores. A custom store with offset or base64 cursors failed on page 2, with no Breaking changes entry.

## Root cause
The route enforced the default InMemoryTaskStore's token format instead of leaving validation to the store that mints the token.

## Check
Grep `_TASK_ID_SHAPE.fullmatch(pageToken)` in agent_sdk/routes/ and confirm no match. Confirm a test passes a non-hex token through a custom TaskStore on page 2 and gets 200.

## Prevention
When planning route validation of a value minted by a pluggable component, delegate it to an overridable hook on that component (default True) and have only the default implementation enforce its own format. If the contract changes, update the docstring and add a Breaking changes entry.
