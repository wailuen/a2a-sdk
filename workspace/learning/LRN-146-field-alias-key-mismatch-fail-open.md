---
id: LRN-146
title: Reuse gate keys on Python field name, not wire alias
category: security
severity: high
source: redteam
date: 2026-09-02
---

## What happened
`reuse_fields_for_model`/`reuse_strict_for_model`/`reuse_raw_override_for_model` and
`ToolEntry.input_schema` key their maps on `model_fields` Python names. A `ReuseKind`
field with a pydantic `alias` is sent and validated under the alias, so the lookup
misses entirely — the GH-148 mismatch gate silently no-ops and `$ref:field` is passed
through as a literal string.

## Root cause
The gate was written keying on `field_name` instead of the wire name the model actually
accepts (`field_info.alias or field_info.serialization_alias or field_name`).

## Check
`grep -n "model_fields.items()" agent_sdk/agent/reuse.py agent_sdk/agent/registry.py`
— confirm each site resolves the wire key via alias before use, and a test exists with
an aliased `ReuseKind` field asserting mismatch rejection + `$ref` substitution fire.

## Prevention
When planning any field-name-keyed validation/substitution gate over a pydantic model,
require the key to be the alias-resolved wire name (matching `model_json_schema()` /
`model_validate` input), never the raw `model_fields` key — or reject aliased fields
outright at registration, matching existing RT-007 container rejections.
