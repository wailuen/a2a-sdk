---
id: LRN-315
title: New untrusted value needs sanitization test per renderer
category: testing
severity: high
source: redteam
date: 2026-10-13
---

## What happened
GH-156 added `{_safe_id(x.id)}` at many renderer sites (EmailList, CalendarEvents, UserList, UserProfile, DocumentList, FundPerformance.pb_id). Only EntityList had a hostile-id test; the others only checked the id appeared. Reverting any site to a raw `{x.id}` would still pass every test. This repeats LRN-152.

## Root cause
Tests were presence-only or single-model, and the renderer-wide guard only greps for `_sanitize_cell(`.

## Check
Verify a test parametrized over `_id_sample_instances()` sets every `id`/`*_id` field to a hostile value (ESC, newline, `(`, `|`, 1000 chars) and asserts none leaks into the text.

## Prevention
When planning a change that adds an untrusted value to several renderers, require a hostile-value test covering each value in each renderer, walking the schema for fields.
