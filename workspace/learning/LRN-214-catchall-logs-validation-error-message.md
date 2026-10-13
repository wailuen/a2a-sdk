---
id: LRN-214
title: Catch-all logs raw ValidationError via logger.exception
category: security
severity: critical
source: redteam
date: 2026-08-15
---

## What happened
GH-135's `ToolInputValidationError` branch catches only input-model coercion. A tool-body `ValidationError` falls into `except Exception` in `mcp.py`'s `_handle_tools_call` and `admin.py`'s `try_tool`, where `logger.exception(...)` logs pydantic's message incl. `input_value='<raw>'`.

## Root cause
The narrow branch was assumed to cover all validation errors, so the catch-all kept `logger.exception`, logging `str(exc)`, not the type.

## Check
grep `logger.exception\|exc_info=True` in `agent_sdk/routes/` — no match. Every catch-all around tool dispatch or content rendering (`wire()`/`translate()`/`to_plain_text()`) — `mcp.py`, `admin.py`, `ag_ui.py` stream handler — logs only `type(exc).__name__` + `frame_locations(exc)` (see `commitments/executor.py`). Regression tests: `tests/test_rt001_mcp_dispatch_no_value_log.py`, `tests/test_rt001_agui_stream_no_value_log.py`.

## Prevention
Planning a catch-all near a call that may raise input-embedding exceptions (e.g. pydantic `ValidationError`): require type-only logging, never `logger.exception`/`exc_info=True`, even if a narrower branch covers it.
