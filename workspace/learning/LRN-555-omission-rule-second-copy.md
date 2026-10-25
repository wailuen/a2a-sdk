---
id: LRN-555
title: Wire omission rule duplicated outside its ClassVar
category: sdk
severity: high
source: redteam
date: 2026-10-25
---

## What happened
`wire_omitted` was meant to be read by the serializers and by `_wire_required`. But `ColumnDef._omit_is_id_when_false` and `DocumentItem._wire_contract_keys` in `agent_sdk/models/content_types.py` still hard-code the key names. CHANGELOG.md and DESIGN.md claim the serializers read the ClassVar, which is false.

## Root cause
The ClassVar was added for the catalog only, so it became a second hand-synced copy of the omission rule.

## Check
grep -n 'pop("is_id"' agent_sdk/models/content_types.py returns nothing. A test adds a name to a subclass's `wire_omitted` and checks `wire()` and `_field_summary` both follow it.

## Prevention
When planning a shared rule, require one source that both the serializer and the catalog read. Add a test that mutates the source and checks both consumers, and verify doc claims against code.
