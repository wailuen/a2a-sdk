---
id: LRN-348
title: Extra security swap added beyond ruling's only-X wording
category: security
severity: high
source: redteam
date: 2026-10-13
---

## What happened
The GH-167 ruling said only line-break/control-char collapse applies to standalone titles. KpiCard and ComparisonTable titles called `_sanitize_line(title, separators=":")` / `"|"`, turning "Q3: Revenue" into "Q3： Revenue". A fresh-lens debug round added it with no approval URL.

## Root cause
A fix round added a defense beyond the ruling's literal wording without ratification.

## Check
`grep -n 'separators=' agent_sdk/models/content_types.py` and confirm no title slot uses it, or a ratification URL is recorded in the todo and REVIEWS.md.

## Prevention
When a fix round adds a protection beyond a ruling, prefer a layout defense (indented rows) that keeps the ruling literal, or record a ratification URL first.
