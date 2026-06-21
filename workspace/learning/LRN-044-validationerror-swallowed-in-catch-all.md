---
id: LRN-044
title: ValidationError swallowed by catch-all loop — SI-2 requires explicit enrichment
category: security
severity: critical
source: redteam
date: 2026-06-17
---

## What happened
The agent task-execution loop caught all exceptions with a bare `except Exception`
block and re-raised a generic `AgentError`. `ValidationError` (input schema
violations) was silently absorbed into this path, discarding the structured
validation detail. Callers received an opaque error response with no indication
that the failure was a schema violation, defeating SI-2's requirement that input
rejection be observable and attributable.

## Root cause
The catch-all was written before `ValidationError` was introduced as a distinct
exception class. When the class was added, the loop was never updated to handle
it explicitly before the generic catch. Because `ValidationError` is a subclass
of `Exception`, it was silently swallowed every time.

## Check
```
grep -n 'except Exception' agent_sdk/agent/loop.py agent_sdk/agent/runner.py
# Each bare `except Exception` block must either:
#   (a) re-raise ValidationError explicitly before the generic handler, OR
#   (b) enrich the caught exception with exc.__class__.__name__ in the error body.
# A block that converts ValidationError to a generic AgentError without
# preserving the original class name is non-compliant with SI-2.
```

## Prevention
When planning error-handling changes in the task loop, place `except
ValidationError` (and any other structured-error subclasses) above `except
Exception`. The enriched error response must include `error.type` set to the
original exception class name so callers can distinguish validation failures from
runtime failures without parsing the message string.
