---
id: LRN-565
title: Base serializer edits dict by field name not alias
category: sdk
severity: high
source: redteam
date: 2026-10-25
---

## What happened
_Wire._wire_rule applied wire_keeps_null and wire_omitted by Python field name. For an aliased field (as_of -> asOf), wire() emitted `as_of: None` and never popped the omitted `hiddenKey`, while the catalog advertised `asOf` as required.

## Root cause
The serializer edited the dumped dict using bare field names instead of the alias in use (info.by_alias).

## Check
tests/test_gh258_catalog.py must include an aliased keeps_null and aliased omitted field asserting wire() uses the alias key and required_paths(summary) <= emitted_paths(wire()). Review agent_sdk/models/content_types.py near `data[name] = None`: key must resolve via serialization_alias/alias.

## Prevention
When planning base-class serializers that edit dumped dicts, require key resolution by alias and an aliased-field test checking catalog and wire agree.
