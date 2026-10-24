---
id: LRN-493
title: Ingress JSON depth cap must be explicit
category: security
severity: high
source: redteam
date: 2026-10-24
---

## What happened
`loads_strict` (C-040) relied on the interpreter raising RecursionError. Bodies nested 255-1000 levels parse fine on every Python; on 3.14 even 50000 deep parses. A 300-deep `message.metadata` stored a task, then `GET /v1/tasks` returned 500 (pydantic "Circular reference detected").

## Root cause
No depth limit in C-040; the guard depended on the interpreter's recursion limit, which differs per version and sits above pydantic's 255 limit.

## Check
`grep -n "_MAX_DEPTH" agent_sdk/common/json_strict.py` must match, with the cap below 255. Verify a test POSTs `/v1/message:send` with metadata nested 300 deep, then `GET /v1/tasks` is never 500.

## Prevention
When planning any JSON ingress parser, require an explicit depth cap (e.g. 64-128) set below the smallest downstream limit, raising the fixed-message JSONDecodeError. Keep RecursionError only as a backstop.
