---
id: LRN-349
title: Narrowing Optional field to non-None default rejects explicit null
category: sdk
severity: high
source: redteam
date: 2026-10-14
---

## What happened
EventLocation.display_name/is_online changed from `str | None`/`bool | None` to `str = ""`/`bool = False` in a patch release. EventLocation(display_name=None, is_online=None) now raises ValidationError. The CHANGELOG called it "additive, not breaking"; the todo's required mode='before' validator and test never landed.

## Root cause
Only omitted input was considered; explicit None from callers mapping upstream nulls was not.

## Check
Run `pytest tests -k event_location_null`: EventLocation(display_name=None, is_online=None).wire() == {"display_name": "", "is_online": False}. Grep `field_validator.*display_name.*mode="before"` in agent_sdk/models/content_types.py.

## Prevention
When planning a change from `X | None = None` to a non-None default, require a mode='before' validator mapping None to the default, plus an explicit-null test. Never label it non-breaking without that test.
