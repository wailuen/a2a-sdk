---
id: LRN-425
title: DESIGN.md left stale after protocol behaviour change
category: protocol
severity: high
source: redteam
date: 2026-10-17
---

## What happened
GH-189 made `blocking: true` wait for the task instead of returning -32004 (agent_sdk/routes/a2a.py `_config_error`). DESIGN.md:272 and the error-table row at DESIGN.md:289 still said "unsupported blocking -> -32004", and the CHANGELOG "Changed:" list omitted DESIGN.md.

## Root cause
Only code, tests and docs/protocols.md were updated; DESIGN.md states the same behaviour in prose and in an error table and was not searched.

## Check
Verify that `grep -n "unsupported blocking\|blocking.*-32004" DESIGN.md docs/ agent_sdk/` has no match describing a rejection, and that DESIGN.md mentions `AGENT_SDK_BLOCKING_SEND_MAX`.

## Prevention
When planning any change to protocol behaviour (error codes, accepted params), include a todo to grep DESIGN.md (prose and error tables) and docs/ for the old behaviour, update each hit, and list DESIGN.md in the CHANGELOG "Changed:" entry.
