---
id: LRN-149
title: Schema required-key added without syncing agent contract
category: testing
severity: high
source: redteam
date: 2026-08-15
---

## What happened
`PLAN_RT_SCHEMA` in `wave-cycle.js` added `peerRepoAnnotations` to `required`, but
redteam's contract docs (`.claude/` and `harness/agents/core/redteam.md`, Mode 2)
still list the old 5 keys. An agent following its doc emits an invalid object;
persistent failure yields `planRt === null`, hitting fail-open and skipping Todos
Redteam.

## Root cause
The JSON Schema and the prose teaching the agent are edited independently;
schema was extended without updating `redteam.md`.

## Check
Diff `PLAN_RT_SCHEMA.required` vs Mode 2 block keys in both `redteam.md` copies;
every required key must appear in both. Confirm `planRt === null` fails closed.

## Prevention
A plan adding/removing a `required` schema key must, same wave: update both
`redteam.md` copies, add a test asserting required keys are documented, and
verify the null branch fails closed.
