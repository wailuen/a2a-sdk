---
id: LRN-448
title: Deliverable gate classifies files by name substring
category: ops
severity: high
source: redteam
date: 2026-10-22
---

## What happened
DELIVERABLE_GATE_PY treated any Creates path with "acceptance" in its name as an acceptance record. Real files (acceptance-api.js, test_gh71_acceptance_api_stream.py) were reported missing, marking the group INCOMPLETE. The verdict regex also rejected "## Verdict" then "PASS" and accepted a later PASS over a first FAIL.

## Root cause
Record detection keyed on a word in the name, not the record directory; verdict parsing ignored the first-verdict rule.

## Check
Script tests: non-record file named *acceptance* passes; heading-form PASS accepted; first verdict FAIL with later PASS rejected. `grep -n "startswith('workspace/acceptance/')"` in wave-cycle.js and sdk-wave.js.

## Prevention
When planning gate scripts, key record checks to the record directory and extension, read only the first verdict, and require tests for each case.
