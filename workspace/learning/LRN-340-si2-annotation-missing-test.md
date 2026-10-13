---
id: LRN-340
title: SI-2 annotation landed without its named no-leak test
category: testing
severity: high
source: redteam
date: 2026-10-13
---

## What happened
The GH-162 todo carried an SI-2 annotation requiring a test that the single-replica WARNING leaks no part of a connection string, account or table name. No such test existed. Tests used only the fixed 'UseDevelopmentStorage=true' and never asserted its absence.

## Root cause
The SI-2 annotation was treated as satisfied because the log text is static today, so no marker-based test was written (same class as LRN-292 / LRN-128).

## Check
Verify tests/test_gh162_single_replica_warning.py sets AZURE_STORAGE_CONNECTION_STRING and AZURE_STORAGE_TABLE_PREFIX to marker values and asserts no marker substring appears in caplog.

## Prevention
When planning, ensure every SI-2 annotation maps to a named no-leak test using marker values, even when the log text is static.
