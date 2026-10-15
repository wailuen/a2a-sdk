---
id: LRN-392
title: Skill credential switch left stale admin placeholders
category: ops
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The AC said /acceptance uses only the service key for protocol calls. The A2A and AG-UI sections still said `Authorization: Bearer <admin_key>`, the Rules bullet still said the admin key goes in the temp file, and acceptance-api.js still said "admin API key". Copies under template/ and .claude/ had the same text, so a rerun would use the admin key.

## Root cause
Only the edited step was changed; the old placeholder was not grepped across the skill, workflow and mirrored copies.

## Check
grep -rn "admin_key\|admin API key\|Admin key" harness/skills/acceptance harness/workflows/acceptance-api.js template/.claude .claude/skills/acceptance and confirm no protocol-call match remains.

## Prevention
When a skill changes which credential it uses, planner must require a grep of the whole skill, its workflow and every mirrored copy (LRN-085) for the old placeholder.
