---
id: LRN-326
title: Registry meta-test vacuous for unset sample fields
category: testing
severity: high
source: redteam
date: 2026-10-13
---

## What happened
The GH-156 meta-test `test_registry_wide_every_id_field_reaches_text` only checks a type has some id field, then collects ids the hand-built sample populates. A new optional field like `EmailMessage.thread_id: str | None = None` stays None, is never collected, and the test passes. This is the hand-list drift LRN-241 warns about.

## Root cause
Coverage was derived from the sample, not from the schema's `model_fields`.

## Check
In `tests/test_content_types.py`, confirm the test walks `model_fields` recursively (including list item models), collects every `id` / `*_id` path, and asserts each is a non-empty string in the sample or listed in `_ID_TEXT_EXEMPT`.

## Prevention
When planning registry-wide meta-tests, require the field list be derived from the schema. Assert the hand-made samples populate every such field, so new optional fields fail until covered.
