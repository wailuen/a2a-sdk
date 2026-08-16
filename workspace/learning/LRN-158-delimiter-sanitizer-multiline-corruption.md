---
id: LRN-158
title: Single-line sanitizer applied to a multi-line markdown field corrupts it
category: security
severity: high
source: redteam
date: 2026-08-15
---

## What happened
GH-130's single-line `_sanitize_cell` was applied to
`MarketBriefing.to_markdown()`'s prose/`TextSection.content`, which carries
multi-line markdown on the A2A/AG-UI DataPart and MCP `structuredContent`
wire. Collapsing newlines to spaces and `|` to `/` destroys headings, lists,
and tables in the SDK's prose-exception type.

## Root cause
The delimiter-safety fix was widened to every free-form `str` field
uniformly, without classifying single-line joins vs multi-line markdown
payloads first.

## Check
Confirm `_sanitize_cell` is NOT applied to prose/`TextSection.content` in
`to_markdown()`; confirm a newline-preserving `_sanitize_block` helper is
used instead; keep a positive test asserting multi-line markdown
(headings/lists/`|` tables) survives intact.

## Prevention
When widening a delimiter sanitizer, classify each field as "single-line
delimited join" vs "multi-line markdown payload" first — never route a
multi-line markdown field through a single-line-safe sanitizer.
