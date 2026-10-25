---
id: LRN-566
title: Public base-class hook names are reserved and need guards
category: sdk
severity: high
source: redteam
date: 2026-10-25
---

## What happened
GH-270 added `_wire_rule` (a model_serializer) and `_wire_reshape` to the public `_Wire` base with no CHANGELOG callout. A domain card with an unrelated `_wire_reshape()` helper began raising PydanticSerializationError. A card with its own @model_serializer silently replaced `_wire_rule`, dropping `wire_keeps_null` fields.

## Root cause
Moving per-class serializer logic into a public base reserves its names, and a subclass model_serializer overrides it, with no guard.

## Check
grep -n "_wire_reshape\|_wire_rule" CHANGELOG.md agent_sdk/models/content_types.py; confirm CHANGELOG lists both under Breaking and tests/test_gh270_reserved_hooks.py covers wrong-signature and own-serializer cases.

## Prevention
When planning a new method or serializer on a public base class, list the names as reserved (LRN-233), guard them in `__pydantic_init_subclass__`, and add tests for collisions.
