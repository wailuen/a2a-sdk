---
id: LRN-334
title: Standalone text slot can forge a sibling row
category: security
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-167 moved titles to `safe_line_text`, which keeps `:` and `|`. `KpiCard(title='Revenue: 999999', metrics=[Revenue=100]).to_plain_text()` renders `Revenue: 999999` beside `Revenue: 100`. A ComparisonTable title like `Acme | 1` also matches a ` | ` data row.

## Root cause
"Standalone" was judged per slot, not against the sibling lines of the same renderer that share its shape.

## Check
Verify `tests/test_content_types.py` has one forgery test per renderer using `_sanitize_line` / `safe_line_text`: a hostile title mimicking that renderer's row shape yields no extra row-shaped line. `grep -n "safe_line_text" agent_sdk/models/content_types.py` and confirm none sit in a renderer whose rows share that shape.

## Prevention
When planning any change that drops separator neutralisation for a text slot, list the renderer's row formats and prove no sibling line can match, or keep `_sanitize_cell`. Add the forgery test per renderer and fix DESIGN.md section 4.0 claims.
