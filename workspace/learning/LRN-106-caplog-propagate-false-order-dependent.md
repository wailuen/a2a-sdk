---
id: LRN-106
title: caplog assertions on agent_sdk.* loggers false-green outside full-suite order
category: testing
severity: critical
source: redteam
date: 2026-07-10
---

## What happened
`test_tool_suffix_without_name_override_warns` (tests/test_gh101_tool_suffix_name_warning.py:37) asserts the registry's tool-suffix warning via `caplog.records`. It passes in isolation but fails when run after any test that calls `build_app()`, because the warning is emitted correctly (visible in captured stderr JSON) yet never reaches pytest's caplog handler.

## Root cause
`configure_logging()` (agent_sdk/observability/logging.py:46, invoked from `build_app()` at app.py:474) sets `logging.getLogger('agent_sdk').propagate = False`. Once any prior test builds an app, `agent_sdk.agent.registry` records stop propagating to caplog's root handler — an order-dependent false-green in per-file gating.

## Check
Run `pytest -q` (full suite, not the single file) and confirm `test_tool_suffix_without_name_override_warns` stays GREEN. `grep -rn "caplog" tests/*.py` and verify each match either attaches a handler directly to an `agent_sdk*` logger, temporarily sets `propagate=True` with restoration, or asserts on captured stderr instead of root caplog.

## Prevention
When planning tests that assert on `agent_sdk.*` logger output, require attaching a `logging.Handler` to the specific `agent_sdk*` logger (or toggling its `propagate` in a fixture with teardown) rather than relying on root-level `caplog`. Any wave that adds a logging-assertion test must re-run the full suite (`pytest -q`) before archiving, never just the new test file in isolation.
