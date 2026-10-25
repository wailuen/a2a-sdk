---
id: LRN-567
title: Breaking bullet needs ruling URL and accurate scope
category: sdk
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The GH-270 reserved-names Breaking bullet had no ruling URL, and the break was not in the GH-270 ruling. It also understated scope: the check uses the inherited `wire_keeps_null`/`wire_omitted`, so subclasses of TimeSeriesDataPoint, ColumnDef or DocumentItem with their own model_serializer also raise TypeError.

## Root cause
A break added during red-team rounds beyond the ruling shipped without its own ruling, and its scope was described from the code's intent rather than its behavior.

## Check
For each Breaking bullet in CHANGELOG [Unreleased], grep for `issues/[0-9]+#issuecomment-` and confirm a match. Confirm a test subclasses TimeSeriesDataPoint with a model_serializer and expects TypeError.

## Prevention
When a wave adds a break beyond the posted ruling, require a new ruling comment before it ships. Document inherited scope and pin it with a test.
