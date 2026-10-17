---
id: LRN-420
title: Unknown-key allowlist must match what model_validate accepts
category: sdk
severity: high
source: redteam
date: 2026-10-17
---

## What happened
GH-196 rejects unknown tool arguments. `_declared_argument_keys` counted the Python field name of an aliased field as declared. Pydantic drops that name unless populate_by_name/validate_by_name is on, so `{"sector":"TECH"}` passed the check and the tool ran with `sector=None`.

## Root cause
The allowlist was built separately from pydantic's real acceptance rule, so the two disagreed for aliased fields.

## Check
Run a test: an aliased optional field without populate_by_name, called by its field name, raises `ToolInputValidationError` naming the key. Confirm `grep -n "_accepts_field_name_alias" agent_sdk/agent/registry.py` shows the helper from reuse.py is used (no second copy).

## Prevention
When planning any strict-input or allowlist check, derive declared keys from the same rule the validator uses (reuse `_accepts_field_name_alias`), and require a test for aliased fields called by field name.
