---
id: LRN-400
title: SI annotation marked done with call sites left
category: security
severity: high
source: redteam
date: 2026-10-16
---

## What happened
The todo's SI-6 annotation required header-from-file/env for the mint, failure-path revoke and teardown revoke. Only the first two were done. The teardown still ran `curl -X DELETE ... -H "Authorization: Bearer <admin_key>"`, exposing the admin key in argv and the transcript.

## Root cause
The annotation was treated as done after fixing some of its listed call sites, with no whole-skill grep for the old pattern.

## Check
`grep -rn "Bearer <admin_key>" harness/skills .claude/skills template/.claude/skills` must return nothing. The test must assert no SKILL.md line contains it.

## Prevention
When planning, give each SI annotation a closing grep for the old pattern across the whole skill and all mirrors. Mark it done only when that grep is empty.
