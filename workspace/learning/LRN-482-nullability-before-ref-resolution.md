---
id: LRN-482
title: Strict schema decides nullability before $ref resolution
category: protocol
severity: high
source: redteam
date: 2026-10-23
---

## What happened
In strict mode, `agent_sdk/common/schema.py` checks nullability on the raw property. A nullable alias (`TypeAliasType('MaybeInt', Optional[int])`) emits `{"$ref": ...}`, so the field stays in `required`. With `exclude_none`, `structuredContent` omits it and fails its own outputSchema, which MCP 2025-06-18 forbids.

## Root cause
`_nullable_inner` and the required/keep_null logic run on the unresolved node, not the node after `$ref` inlining.

## Check
Run the TypeAliasType Optional regression test: validate `O(b=None)` structuredContent against the strict outputSchema with `jsonschema`, and confirm no error. Also confirm `grep -n "_nullable_inner" agent_sdk/common/schema.py` is called on a resolved node.

## Prevention
When planning schema rewrites that change `required`, resolve the `$ref` chain (with the recursion guard) first, then decide nullability. Always test with alias and nested-ref cases.
