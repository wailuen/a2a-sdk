---
id: LRN-264
title: Advisor docs say Ratified while REVIEWS says unratified
category: protocol
severity: high
source: redteam
date: 2026-10-09
---

## What happened
All three a2ui-advisor copies, DESIGN.md, the a2ui-check SKILL and the content_types.py header said Profile v1.1 was ratified. REVIEWS.md Round 11, CHANGELOG and the docstring body said PROPOSED. The frozen TimeSeriesChart row was already removed everywhere.

## Root cause
The wave edited normative advisor copies before its own review record was ratified, and no check compared status wording across files.

## Check
Verify that `grep -rn "Ratified by the Profile v1.1" .claude harness template DESIGN.md` matches only when REVIEWS.md Round 11 starts with **SIGNED OFF**.

## Prevention
When planning frozen-contract changes, land edits to normative advisor copies only after user-confirmed sign-off, and list every file stating the status so all agree.
