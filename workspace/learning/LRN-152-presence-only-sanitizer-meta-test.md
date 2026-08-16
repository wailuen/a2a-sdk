---
id: LRN-152
title: Presence-only meta-test misses per-field sanitisation gaps
category: testing
severity: high
source: redteam
date: 2026-08-15
---

## What happened
`EntityList.to_plain_text` (content_types.py:420) joins free-form `str`
field `entity_type` into rows without `_sanitize_cell`, so a newline
fabricates rows like the GH-130 `item.name` case. The RT-005 meta-test only
asserts `_sanitize_cell(` appears somewhere in a renderer's source, so
sanitising one field while leaving another raw still passes.

## Root cause
The guard checks helper *presence* in a function, not per-field *coverage* —
it can't tell "every untrusted field sanitised" from "at least one is."

## Check
`grep -n 'self.entity_type' agent_sdk/models/content_types.py` — must be
wrapped in `_sanitize_cell(...)`. Confirm
`test_gh130_all_profile_renderers_sanitize_before_joining` counts
interpolated untrusted fields per renderer and asserts equality with the
`_sanitize_cell(` call count, not just `> 0`.

## Prevention
When planning a delimiter/injection guard over multiple free-text fields,
require it to enumerate every untrusted field feeding the join and assert
each is individually wrapped — never a single "helper appears in source"
check.
