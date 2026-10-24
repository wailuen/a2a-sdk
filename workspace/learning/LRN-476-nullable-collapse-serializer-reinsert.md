---
id: LRN-476
title: Null collapse breaks types whose serializer re-inserts null
category: protocol
severity: high
source: redteam
date: 2026-10-23
---

## What happened
Strict mode turned property-level anyOf:[X, null] into plain X. TimeSeriesDataPoint.value (float | None, no default) is put back as `value: null` by its model_serializer (LRN-110), so TimeSeriesChart structuredContent with a data gap failed the strict outputSchema ("None is not of type 'number'").

## Root cause
model_serializers can re-insert keys that exclude_none would drop; GH-206 tests used only models with defaulted Optional fields.

## Check
Test: for every built-in content type with all-None optional data, jsonschema.validate(obj.wire(), strip_schema_titles(flatten_schema(model_json_schema()))) passes. Include TimeSeriesChart with value=None.

## Prevention
When planning schema rewrites that remove null, require a loop test over the real wire() output of every built-in content type, not just SDK-test models.
