---
id: LRN-478
title: caplog no-leak asserts empty after first build_app
category: testing
severity: high
source: redteam
date: 2026-10-23
---

## What happened
SI-2 no-log-leak assertions in tests/test_gh205_mcp_skills.py (`assert MARKER not in caplog.text`, lines 243 and 253) checked nothing when run alone. build_app() calls configure_logging(), which sets propagate=False on the agent_sdk logger after the autouse conftest fixture re-enabled it. Root caplog never saw agent_sdk.routes.mcp records.

## Root cause
First build_app() in the process disables propagation (LRN-106 failure mode).

## Check
Run `pytest tests/test_gh205_mcp_skills.py` in isolation. grep the file for `caplog.text` and confirm it uses `sdk_caplog` instead, plus a self-check that a known agent_sdk.routes.mcp warning is captured.

## Prevention
When planning no-leak tests that build an app, require the conftest `sdk_caplog` fixture and a positive-capture probe, so the assertion cannot pass on empty input.
