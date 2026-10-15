---
id: LRN-353
title: Non-finite coercion misses nullable int fields and runs too late
category: sdk
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The GH-173 ruling said nullable numeric fields coerce nan/inf to None. The guard only covered float annotations and ran after validation. `CategoryValue(value=1.0, count=float('nan'))` raised ValidationError instead of giving `count=None`; other `int | None` fields had the same gap.

## Root cause
The guard and its test walk looked only at float types, and pydantic rejects non-finite floats for int fields before any after-validator runs.

## Check
Run `CategoryValue(value=1.0, count=float('nan')).count is None`. Confirm the walk in tests/test_gh173_non_finite_values.py includes `int | None` fields.

## Prevention
When a ruling says "numeric fields", plan the guard and test walk to cover int and float, and require coercion in a `mode="before"` validator, not after type validation.
