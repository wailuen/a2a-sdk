---
id: LRN-155
title: prose field skipped GH-130 sanitization applied to its render-method siblings
category: security
severity: high
source: redteam
date: 2026-08-15
---

## What happened
`MarketBriefing.prose` (agent_sdk/models/content_types.py:512) is appended raw
into `to_markdown()`'s `"\n".join(lines)` render, while every other
free-form str field in the same method now routes through `_sanitize_cell`.
An embedded newline in `prose` still fabricates a KPI/section line — the
GH-130 attack class — reaching the model-facing path (runner.py:195) and the
MCP structuredContent path (mcp.py:363).

## Root cause
The GH-130 delimiter-safety fix was applied to the fields named in the
original report, not verified against a full enumeration of the model's
free-form str fields, leaving a same-method sibling (`prose`) unsanitized.

## Check
grep `to_markdown`/`to_plain_text` in agent_sdk/models/content_types.py and
confirm every free-form str field assembled into `lines` (including
`prose`) is routed through `_sanitize_cell` or an equivalent; add a test
mirroring `test_market_briefing_text_section_newline_does_not_fabricate_section`
but targeting `prose` with an embedded-newline KPI-looking payload,
asserting no fabricated line in runner.py's model-facing output and mcp.py's
structuredContent.

## Prevention
When a delimiter-safety contract claims to cover "every untrusted free-form
str field," the todo/AC must enumerate every such field on the model class
definition itself (not just the fields named in the bug report) and require
one named test per field before the contract can be marked satisfied.
