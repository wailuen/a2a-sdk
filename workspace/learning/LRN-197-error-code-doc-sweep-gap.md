---
id: LRN-197
title: Error-code change lands without sweeping docs that pin the old code
category: protocol
severity: high
source: redteam
date: 2026-08-19
---

## What happened
GH-144 changed terminal-task resume (message/send, message/stream) to 501/-32004, was 409/-32002. docs/protocols.md:20 still says resume → -32002 (reserved for tasks/cancel); DESIGN.md:277's -32004 row omits terminal-task re-message.

## Root cause
The fix updated route handlers (a2a.py) but no step required docs pinning that error code to change in the same commit.

## Check
`grep -n "terminal-task" docs/protocols.md` — resume must say 501/-32004, cancel 409/-32002. `grep -n "32004" DESIGN.md` — row must list terminal-task re-message.

## Prevention
A wave changing which error code a route emits must add docs/protocols.md and DESIGN.md's error-table row to that unit's Modifies: list, not a later pass.
