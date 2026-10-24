---
id: LRN-475
title: Null collapse must apply only at property positions
category: protocol
severity: high
source: redteam
date: 2026-10-23
---

## What happened
The strict-mode anyOf-null collapse in agent_sdk/common/schema.py ran at every schema node. `list[Optional[str]]` items and `dict[str, Optional[int]]` additionalProperties lost `null`, yet structuredContent (exclude_none=True) keeps None inside lists and dicts. Result failed its own outputSchema.

## Root cause
exclude_none drops keys, never list or dict values, but the collapse treated all positions alike.

## Check
Test in tests/test_gh206_strict_schema_mode.py: emits model with `list[Optional[str]]` and `dict[str, Optional[int]]` holding None; jsonschema-validate structuredContent against the strict outputSchema. grep schema.py for `_nullable_inner` and confirm it is gated by `at_property`.

## Prevention
When planning schema rewrites that drop null, restrict them to property positions. Keep null at items, additionalProperties, patternProperties and prefixItems.
