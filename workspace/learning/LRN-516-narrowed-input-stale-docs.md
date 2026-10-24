---
id: LRN-516
title: Narrowed accepted input leaves stale doc examples
category: protocol
severity: high
source: redteam
date: 2026-10-24
---

## What happened
GH-247 limited AG-UI resume status to "resolved"/"cancelled". `docs/testing.md:169-173` still called `agui_resume(..., status="approved")` and `docs/tools.md:221-224` still said AG-UI accepts "approved"/"rejected" in `status`. A copied example now ends in RUN_ERROR "invalid resume entry".

## Root cause
The ruling changed the accepted values without sweeping docs for the old ones.

## Check
Run `grep -rn 'status="approved"\|"approved"/"rejected"' docs/` and confirm no AG-UI resume example uses it. Decision belongs in `payload={"decision": "approved"}`.

## Prevention
When planning a change that narrows an accepted input value, include a task that greps docs/ and examples for the old value and fixes them in the same change.
