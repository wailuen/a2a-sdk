---
id: LRN-352
title: Validator message formats the rejected value despite hide_input_in_errors
category: security
severity: high
source: redteam
date: 2026-10-15
---

## What happened
GH-173 SI-2 required errors to never show the value. `_assert_finite` raised `f"non-finite float not allowed: {value!r}"`, so `str(ValidationError)` for `BriefingKpiItem`, `KpiCard.metadata` and `ChartSection.data` still contained `nan`. The tests skipped these models.

## Root cause
`hide_input_in_errors=True` only hides pydantic's `input_value=` suffix, not text a validator writes into its own ValueError.

## Check
grep `_assert_finite` in agent_sdk/models/content_types.py and confirm no `{value` in the message. Confirm a test asserts nan/inf absent from `str(exc)` and from the A2A/MCP tool-error text.

## Prevention
When planning an SI-2 (no value echo) fix, require raising static-message ValueErrors (field named by error location) and tests that grep `str(exc)` and the wire error text for the value, not just the config flag.
