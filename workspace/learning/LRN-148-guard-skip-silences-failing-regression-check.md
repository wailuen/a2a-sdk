---
id: LRN-148
title: skipif on a failing guard silences the regression it exists to catch
category: testing
severity: high
source: redteam
date: 2026-08-15
---

## What happened
`test_acceptance_api_is_harness_template_shared` in
`tests/test_workflow_sync.py` verified harness↔template propagation. In the
wave needing that propagation, it was rewritten as `skipif(not
TEMPLATE_DIR.exists())`. HEAD's version fails when run; skip hid the drift
instead of blocking the wave.

## Root cause
The checkout couldn't verify propagation, so the fix disabled the check
instead of fixing that.

## Check
`grep -n 'skipif(not TEMPLATE_DIR' tests/test_workflow_sync.py` — if
present, confirm `xfail(strict=True)` with a message, not bare `skip`.

## Prevention
When planning peer/template propagation changes, never let
implement/redteam "fix" a failing guard via `skipif`/`skip`; require a real
fix or `xfail` naming the unverifiable condition.
