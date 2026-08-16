---
id: LRN-136
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
grep `logger.exception` in `mcp.py`/`admin.py` — no match; both catch-alls log only `type(exc).__name__` + `frame_locations(exc)` (see `commitments/executor.py`).

## Prevention
Planning a catch-all near a call that may raise input-embedding exceptions (e.g. pydantic `ValidationError`): require type-only logging, never `logger.exception`/`exc_info=True`, even if a narrower branch covers it.
