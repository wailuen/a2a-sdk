---
id: LRN-430
title: Check-then-delete safety rules need a lock off the event loop
category: security
severity: high
source: redteam
date: 2026-10-19
---

## What happened
Two concurrent DELETE /admin/api/keys/{id} calls on the last two admin keys both passed the other-admin check and both deleted. Zero admin keys were left, breaking the "lockout is impossible" promise in the api_keys.py docstring and DESIGN.md section 6.

## Root cause
revoke() moved to worker threads, so the check (list_items) and the delete are no longer atomic across requests.

## Check
Verify a test runs two revokes at once on the last two admin keys (Barrier inside list_items) and asserts exactly one succeeds and one raises AgentError(VALIDATION). grep api_keys.py to confirm revoke() holds one lock across read, other-admin check and delete.

## Prevention
When planning invariants like "never remove the last X", require the check and the delete under one lock, and a two-thread Barrier test. Note cross-replica races as out of scope in DESIGN.md.
