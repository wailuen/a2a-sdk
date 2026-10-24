---
id: LRN-477
title: Strict outputSchema must match exclude_none serialization
category: protocol
severity: high
source: redteam
date: 2026-10-23
---

## What happened
In strict mode an output field `X | None` with no default stayed in `required`. structuredContent uses exclude_none=True, so `Out(x=None)` dumps to `{}` and fails "'x' is a required property". This breaks MCP 2025-06-18 (structuredContent MUST conform) and the GH-206 AC that the field leaves `required`.

## Root cause
The keep-required rule assumed serializers re-emit null, true only for TimeSeriesDataPoint.

## Check
Test: emits ContentModel with `x: str | None` (no default) returning x=None; structuredContent validates against the strict outputSchema. grep schema.py for `keep_required` and confirm nullable output props are never required.

## Prevention
In output mode always drop nullable fields from `required`, but keep them nullable (`type:[X,"null"]`) so both serializer behaviours validate.
