---
id: LRN-344
title: Reuses directives treated as optional, not acceptance criteria
category: sdk
severity: high
source: redteam
date: 2026-10-13
---

## What happened
Three `Reuses: C-NNN` directives (C-024 store, C-007 sanitizer, C-020 schema-key helpers) landed unmet. The deferred note ignored C-024, `revoke_oauth_identity` echoed `user` raw, and a regression test used ad-hoc substring checks.

## Root cause
Waves verified the feature worked, not that the named registry component was actually used.

## Check
For each `Reuses: C-NNN` in the wave todo, grep the landed code/note for that component's symbol (e.g. `grep -n sanitize_text agent_sdk/routes/admin.py`, `grep -n BoundedTtlSingleUseStore workspace/todos/deferred/gh162-*.md`) and confirm a match.

## Prevention
When planning, write each `Reuses: C-NNN` as an acceptance criterion with the exact symbol or helper to grep for, and require the redteam to verify it.
