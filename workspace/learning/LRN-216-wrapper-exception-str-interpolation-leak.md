---
id: LRN-216
title: Wrapper exception must not echo str(wrapped ValidationError)
category: security
severity: high
source: redteam
date: 2026-08-15
---

## What happened
`ToolInputValidationError.__init__` (`agent_sdk/agent/registry.py`) set its
own message to `str(validation_error)`, baking in the raw rejected input
(e.g. `bad token 'sk-SUPERSECRET-123'`) — the `str(exc)` form GH-135's SI-2
forbids, arming any `except Exception as e: str(e)` handler.

## Root cause
`super().__init__(...)` passed the wrapped pydantic error through `str()`
instead of a fixed string, conflating "diagnostic" with "safe message".

## Check
```
grep -n "super().__init__" agent_sdk/agent/registry.py
```
Must pass a fixed string (e.g. `f"tool {tool_name!r} input validation
failed"`) — never `str(validation_error)`. Raw detail reachable only via
`.validation_error`, used solely by `safe_validation_message()`.

## Prevention
When wrapping a `ValidationError` (or other exception carrying
caller/body-supplied values), require the wrapper's own message be fixed —
never `str(wrapped_exc)`. Keep the wrapped exception on a named attribute;
render only via a dedicated redaction helper.
