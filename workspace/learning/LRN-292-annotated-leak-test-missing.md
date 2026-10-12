---
id: LRN-292
title: SI-2 annotation names a no-leak test that was never written
category: testing
severity: high
source: redteam
date: 2026-10-11
---

## What happened
GH-154's todo carried an SI-2 annotation requiring a test that a hostile timezone value (newline, NUL) never reaches logs, prompt, or task status. The tests only sent 'Nope/Zone', '../../etc/passwd' and 'A'*500, with no caplog and no control characters.

## Root cause
The SI annotation was treated as design intent, not as an acceptance criterion, so no test was tied to it.

## Check
Verify the test file has a unique marker (uuid plus "\n" and "\x00") sent via A2A metadata.timezone and AG-UI forwardedProps.timezone, run under caplog at DEBUG, asserting the marker is absent from caplog.text, every fm.calls[i]['system'], and the task status JSON: `grep -n "caplog" tests/test_gh154_current_date.py`.

## Prevention
When planning, turn every SI-N annotation that names a test into an explicit acceptance criterion. The test must use a unique marker string and inspect captured logs, not just the happy-path prompt.
