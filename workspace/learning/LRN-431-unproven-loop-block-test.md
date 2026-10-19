---
id: LRN-431
title: Not-blocked-loop test must make only the code under test slow
category: testing
severity: high
source: redteam
date: 2026-10-19
---

## What happened
test_admin_listing_does_not_block_event_loop used a SlowStore where get() was slow too. The auth verify took about 1.0 s in slow gets, so the /health probe finished during auth. With the to_thread fix reverted, the test still passed. revoke and overview count() had no such test.

## Root cause
The slow auth dependency hid the slow code under test, so the probe window never overlapped list_keys.

## Check
Revert probe: patch agent_sdk.routes.admin.asyncio.to_thread to run fn() inline and confirm tests/test_gh202_api_key_store_off_loop.py fails. Confirm it records threading.get_ident() in SlowStore.list_items and asserts it differs from the loop thread, for list, revoke and overview.

## Prevention
When planning loop-blocking tests, require slowing only the target call, asserting thread identity, and a one-time revert-the-fix proof step.
