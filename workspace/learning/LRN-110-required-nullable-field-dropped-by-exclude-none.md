---
id: LRN-110
title: Required-but-nullable field silently dropped by blanket exclude_none
category: protocol
severity: high
source: protocol-audit
date: 2026-07-10
---

## What happened
`TimeSeriesDataPoint.value` (`agent_sdk/models/content_types.py:213`) is typed
`float | None` with no default — required-but-nullable. `_Wire.wire()` dumps
with `exclude_none=True`, which Pydantic v2 applies recursively, so a
`value=None` point (a legitimate series gap) loses its `value` key entirely
instead of emitting `"value": null`, breaking the frozen `{date, value}`
Standard Profile v1 contract.

## Root cause
`_Wire.wire()` uses one blanket `model_dump(..., exclude_none=True)` for all
fields, which does not distinguish "optional, omit if absent" fields from
"required, may be null" fields.

## Check
Assert `TimeSeriesChart(chart_type='line', title='t',
data=[TimeSeriesDataPoint(date='2026-01-02', value=None)]).wire()["data"][0]`
contains key `"value"` mapped to `None`. Also grep
`agent_sdk/models/content_types.py` for the pattern `: \w+ \| None$` (no
trailing `= None`) across all `_Wire`/`ContentModel` subclasses to catch other
required-but-nullable fields.

## Prevention
When planning any new A2UI Profile/domain content type, forbid declaring a
field as `X | None` with no default if it must always appear on the wire
(even as `null`); either give it a default and add a serializer override that
re-inserts the key, or model gaps with a sentinel/explicit presence flag
instead of relying on `_Wire.wire()`'s blanket `exclude_none=True`.
