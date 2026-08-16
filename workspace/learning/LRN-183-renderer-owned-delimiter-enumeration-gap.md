---
id: LRN-183
title: Delimiter-safety fix missed renderer-owned separators
category: security
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-130's initial fix neutralised universal `" | "`/newline separators but
left renderer-owned ones live: `,`/`=` (MultiCategoryChart), `" — "`
(UserList), `": "` (KpiCard/BarChart/EmailList/CalendarEvents),
`[unread]`/`[online]` markers — letting untrusted values fabricate a pair
or forge a job title.

## Root cause
The fix enumerated delimiters from the bug report, not every literal each
renderer's f-string inserts, leaving a "complete" contract holed.

## Check
`agent_sdk/common/redact.py` separator maps must cover `,` `=` `:` `—` `[`
`]`. Confirm `test_content_types.py::test_multi_category_chart_category_key_comma_equals_do_not_fabricate_pair` passes.

## Prevention
When planning a delimiter-safety fix, require grepping every renderer's
f-string for literal separators, plus one fabrication test per pair, as
the completion gate.
