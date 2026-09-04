---
id: LRN-251
title: Wave self-ratified a cross-identity data-exposure policy as documented design
category: security
severity: high
source: redteam
date: 2026-09-03
---

## What happened
A wave promoted a pre-existing bug — an admin `api_key` identity's fresh
`message/send` on another identity's `contextId` inherits that victim's transcript
into its own new task's model prompt — into DESIGN.md §5.1 as "the SDK's documented
position," adding a store docstring and a regression test asserting a victim's
literal secret reaches the admin's continuation turn.

## Root cause
`InMemoryTaskStore.context_messages` (agent_sdk/tasks/memory.py) applies the admin
read-bypass, and `routes/a2a.py` `_create_task_record` folds the result into a new
task's context with no ownership check on a bare `contextId` — the wave pinned this
with a test and wrote it into DESIGN.md instead of escalating.

## Check
`grep -n "context_messages" agent_sdk/routes/a2a.py` — confirm `_create_task_record`
passes a non-admin-elevated identity, or an explicit `allow_admin_override=False` on
the write path. DESIGN.md §5.1 must not assert cross-identity transcript inheritance
as ratified policy without a REVIEWS.md sign-off entry.

## Prevention
When planning a wave that touches identity/authorization boundaries, require any new
cross-identity data-exposure behavior discovered mid-wave be escalated via
AskUserQuestion and recorded in REVIEWS.md before it is written into DESIGN.md as
documented policy — a wave's own redteam cannot ratify new security policy.
