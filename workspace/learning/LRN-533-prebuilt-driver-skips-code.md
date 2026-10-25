---
id: LRN-533
title: Real-app test with a pre-built driver skips the code under test
category: testing
severity: high
source: redteam
date: 2026-10-25
---

## What happened
The only build_app()-over-ASGI A2UI test in `tests/test_gh237_testing_clients.py` passed a bare `ChatDriver(client)`. So `turns.py` `_card_driver` and the run_turn catalog path never ran against the real app. The assertion `cid in caps["catalogs"]` could not fail, because the card lists only the standard id that ChatDriver always adds.

## Root cause
The test supplied the driver itself, bypassing the helper under test. Its card data matched the defaults, so the check was vacuous.

## Check
In `tests/test_gh237_testing_clients.py`, confirm a real-app test calls `_a2a_attempt(client, "q", {})` or `run_turn(..., client=client)` with no driver. Confirm it asserts a domain catalog id (not the standard id) in the posted `a2uiClientCapabilities.catalogs`.

## Prevention
When an AC is about how a helper builds its driver, require the test to call the helper without a driver. Require a real-app card whose data differs from the defaults, so the assertion can fail.
