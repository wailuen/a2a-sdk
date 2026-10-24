---
id: LRN-480
title: Allowlist narrower than the ruling that created it
category: sdk
severity: high
source: redteam
date: 2026-10-23
---

## What happened
GH-230 turned the validation-error echo into an allowlist. The ruling named all pydantic built-in codes plus SDK codes, but `_VALIDATION_TYPE_PHRASES` held only 24. Built-ins such as `too_long`, `int_from_float` and date errors now render the generic "input failed validation" and lose the guidance the model needed.

## Root cause
The allowlist was built from codes that already had phrases, not from the set the ruling named.

## Check
Verify `_validation_type_phrase` in `agent_sdk/agent/loop.py` allows `typing.get_args(pydantic_core.core_schema.ErrorType)` plus `UNKNOWN_ARGUMENT_ERROR_TYPE`. Test: `too_long` and `int_from_float` render a phrase or the bare code; `PydanticCustomError("leak_x")` renders the generic phrase.

## Prevention
When planning a switch from echo to allowlist, derive the allowlist from the set the ruling names, and add a test per category: known built-in, SDK code, and custom or leaky code.
