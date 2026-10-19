---
id: LRN-432
title: Process-wide lock across store I/O starves the to_thread pool
category: sdk
severity: high
source: redteam
date: 2026-10-19
---

## What happened
_touch_last_used blocked on one process-wide _write_lock across two store round trips, and revoke() held it across a full list_items scan. With about 56k keys, waiting threads filled the shared default to_thread pool and stalled authenticated traffic, like GH-202 but in threads.

## Root cause
A best-effort write used a blocking global lock, so per-request threads queued behind slow I/O.

## Check
Verify api_keys.py `_touch_last_used` uses `acquire(blocking=False)` (or per-key locks) and skips on contention. Verify a test pauses revoke inside list_items and asserts verify of a different stale key returns within a short bound.

## Prevention
When planning locks on per-request paths in the shared to_thread pool, forbid holding a global lock across blocking I/O. Make best-effort writes non-blocking or per-key, and keep scans under a separate lock.
