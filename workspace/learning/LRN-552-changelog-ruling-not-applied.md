---
id: LRN-552
title: CHANGELOG correction asked by a ruling not applied
category: ops
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-261 item 6 was marked done, but the GH-259 filtering entry still sits under 0.23.0 "Changed", not Breaking. The GH-257 Breaking bullet still names `_mode_accepted`, which no longer exists in `agent_sdk/`. A line still says filtering is listed under Changed.

## Root cause
The new entries were reviewed, but the old text the ruling told us to move was never searched for.

## Check
grep -n "_mode_accepted" CHANGELOG.md agent_sdk/ returns nothing; the GH-259 bullet appears under the 0.23.0 Breaking heading; grep "listed under Changed" returns nothing. Pin these in a test.

## Prevention
When planning, treat each CHANGELOG correction in a ruling as an AC verified by grepping the OLD text for absence, plus a test that pins the section placement.
