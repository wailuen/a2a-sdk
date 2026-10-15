---
id: LRN-393
title: Teardown step placed before later loop rounds
category: ops
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The acceptance skill revoked the service key right after the Phase 2A workflow call. Phase 3 fix rounds and Phase 2B reuse the same key, so later rounds wrote a revoked key and every scenario failed with 401. Fix agents then chased fake auth failures until round 5.

## Root cause
Teardown was written after the first iteration's call, not at the loop's exit points.

## Check
In harness/skills/acceptance/SKILL.md and template/.claude/skills/acceptance/SKILL.md, verify the revoke step appears only after the final report, on Phase 3b escalation and on abort, and that "do not revoke between rounds" appears in the Server restart procedure.

## Prevention
When planning a looping skill, place teardown at loop exit points only. List every later phase that reuses the resource and state that it persists across rounds and restarts.
