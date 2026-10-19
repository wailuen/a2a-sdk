---
id: LRN-429
title: Thread offload removes free atomicity of read-modify-write
category: security
severity: critical
source: redteam
date: 2026-10-19
---

## What happened
GH-202 moved ApiKeyStore verify()/revoke() into asyncio.to_thread. verify() read a record, revoke() deleted the row, then verify() wrote the whole old record back for last_used. Stores upsert, so the revoked key came back and authenticated again.

## Root cause
On the event loop, read-modify-write had no await between steps and was atomic in-process. Worker threads interleave, and whole-record upserts re-create deleted rows.

## Check
Verify tests/test_gh202_api_key_races.py forces verify/revoke interleaving (threading.Event on store.get/delete) and asserts verify(token) raises after revoke. grep api_keys.py for `_write_lock` around `_touch_last_used` and confirm it re-reads and skips if the row is gone or hash changed.

## Prevention
When planning any move of sync code into to_thread, list its read-modify-write sequences. Require a lock plus re-read-before-write, and an interleaving test. A write must never re-create a missing row.
