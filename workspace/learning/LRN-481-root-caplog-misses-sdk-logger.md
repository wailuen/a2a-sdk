---
id: LRN-481
title: Root caplog misses agent_sdk logger after build_app
category: testing
severity: critical
source: redteam
date: 2026-10-23
---

## What happened
The GH-230 SI-2 no-log-leak tests asserted `MARKER not in caplog.text` using root `caplog`. `build_app()` calls `configure_logging()`, which sets `propagate=False` on the `agent_sdk` logger, so root never sees SDK records. The assertions passed vacuously.

## Root cause
Root `caplog` only captures propagated records, and `build_app()` stops propagation.

## Check
`grep -n "caplog.text" tests/test_gh230_safe_value_error.py` must show no root `caplog` in tests that build an app. Each no-leak test must use `sdk_caplog('agent_sdk', logging.DEBUG)` and assert a probe record was captured.

## Prevention
When planning any log-leak test in an app-building fixture, require `sdk_caplog` plus an emitted probe record asserted present, so the absence check cannot pass on empty capture.
