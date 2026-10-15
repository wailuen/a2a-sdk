---
id: LRN-373
title: Test named for a field never asserts it; text drops wire field
category: testing
severity: high
source: redteam
date: 2026-10-15
---

## What happened
GH-177 AC 2 requires the plain-text fallback to show `modified_by`. `DocumentList._body_text` never renders it, yet `test_plain_text_still_shows_date_and_modified_by` passed because it only checked the date. Text-only clients never saw a field wire() carries (LRN-241 pattern).

## Root cause
The test name claimed coverage the assertions lacked, so the missing field went unnoticed.

## Check
grep `modified_by` in `DocumentList._body_text` (agent_sdk/models/content_types.py) and confirm a match. In tests/test_gh177_document_contract_keys.py confirm the test asserts `"Ann" in text`.

## Prevention
When planning tests for an AC, require one assertion per field named in the test title. For any model with documented wire extensions, require a test that every extension field value appears in `to_plain_text()` (LRN-241).
