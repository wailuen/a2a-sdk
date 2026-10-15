---
id: LRN-370
title: Validation-order AC half-implemented; old tests pin old order
category: sdk
severity: high
source: redteam
date: 2026-10-15
---

## What happened
GH-176/GH-179 asked that the type + PascalCase check run before any casefold clash check in `register_content_type`. Only the isinstance check moved. `tradeactivity`, `kpicard`, `checkbox` still got clash messages, not the PascalCase one. CHANGELOG claimed the full reorder.

## Root cause
Tests only used inputs every order rejects, and test_gh172 still pinned the old order, so the partial move passed.

## Check
Run `pytest tests/test_gh172_component_name_rules.py tests/test_gh176_basic_catalog_names.py`: assert `register_content_type` with `tradeactivity`, `kpicard`, `text` raises a message containing "PascalCase". grep `_COMPONENT_NAME_RE.fullmatch` in agent_sdk/models/content_types.py and confirm it precedes the first `.casefold()`.

## Prevention
When planning an AC that reorders validation checks, require a test on the boundary input whose message changes (lowercase name folding onto a reserved name), and require updating tests that pinned the old order in the same change. Do not write CHANGELOG claims until the code makes them true.
