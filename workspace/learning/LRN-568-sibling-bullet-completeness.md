---
id: LRN-568
title: Each Breaking bullet needs its own path, ruling, migration
category: sdk
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The GH-270 item 2 bullet (`TimeSeriesChart.x_key`/`y_key` now frozen) sat under Breaking changes. It had no ruling URL, no Migration line and no changed file path, though sibling bullets for the same issue had them.

## Root cause
The author treated the issue's other bullets as covering this one, but LRN-557 and LRN-491 apply per bullet.

## Check
For every bullet under "Breaking changes" in CHANGELOG.md [Unreleased], confirm it contains `agent_sdk/` path, `issuecomment-` URL, and `**Migration:**`. Grep each separately per bullet, not per section.

## Prevention
When planning CHANGELOG work, list each Breaking item as its own checklist row with file path, ruling URL and Migration line. Do not share these across sibling bullets.
