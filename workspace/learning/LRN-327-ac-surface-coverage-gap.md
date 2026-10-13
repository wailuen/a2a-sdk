---
id: LRN-327
title: Per-model AC tested on only a sample of models for second surface
category: testing
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-156 required per-model tests checking ids in both `to_plain_text()` and the MCP `tools/call` `content[0].text`. The MCP-level tests covered only EntityList and DocumentList. EmailList, CalendarEvents, UserList and UserProfile had no MCP test.

## Root cause
The plain-text surface was parametrized over all models, but the MCP surface was hand-written for a sample, so the AC was only partly met.

## Check
Verify `tests/test_gh156_mcp_text_ids.py` parametrizes over every entry of `tests/test_content_types.py::_id_sample_instances()` and asserts each `_collect_id_values(sample)` value appears in `result.content[0].text`.

## Prevention
When an AC names N surfaces per model, ensure the plan parametrizes every model on every surface from one shared sample list. Do not hand-write tests for a subset of models on the later surfaces.
