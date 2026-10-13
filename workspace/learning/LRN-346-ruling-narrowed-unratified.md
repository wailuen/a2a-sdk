---
id: LRN-346
title: Maintainer ruling implemented for fewer slots than named
category: protocol
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-167 ruling said standalone titles, names, summaries and as-of headers keep ASCII and ids move to their own line. Code did this only for EntityList and chart titles. MarketBriefing, KpiCard, ComparisonTable, UserList, UserProfile, DocumentList and CalendarEvents still used look-alike substitution, with no recorded approval.

## Root cause
The wave silently narrowed the ruling's scope.

## Check
For every slot the ruling names, grep the renderer for `safe_cell_text`/`_sanitize_cell` on titles, names and as-of headers in `agent_sdk/models/content_types.py`. Confirm none remain, or a maintainer comment URL is cited in CHANGELOG and REVIEWS.md.

## Prevention
When planning against a maintainer ruling, list every slot it names as an AC. Any narrowing needs a recorded maintainer comment URL before release.
