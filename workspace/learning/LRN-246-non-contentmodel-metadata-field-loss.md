---
id: LRN-246
title: Hoisting metadata onto ContentModel silently dropped it from a _Wire sub-shape
category: protocol
severity: high
source: redteam
date: 2026-09-03
---

## What happened
`CategoryValue.metadata` was deleted from `content_types.py` on the
assumption it now inherits `metadata` from `ContentModel`. `CategoryValue`
subclasses `_Wire`, not `ContentModel`, so it inherits nothing. The frozen
A2UI profile's `categories` sub-shape still requires `{value, count?,
metadata?}`, `catalog.py` still documents it, but `_Wire`'s default
`extra="ignore"` accepts `metadata=...` at construction and silently drops
it from `wire()` — no error, no test coverage.

## Root cause
A base-class field hoist was applied without checking that every deletion
site actually inherits from the new base; a sibling type on a different
base class loses the field with no signal because pydantic ignores unknown
extras by default.

## Check
`CategoryValue(value=1.0, metadata={"note": "x"}).wire()` must contain
`"metadata"`. Grep every `_Wire` (non-`ContentModel`) subclass touched by
the same hoist commit for a field the sweep may have removed.

## Prevention
When planning a field hoist onto a base class, require an explicit
per-deletion-site MRO check (`issubclass(X, NewBase)`) before removing the
field, and require a wire-roundtrip regression test for every affected
type — not just the base class's own tests.
