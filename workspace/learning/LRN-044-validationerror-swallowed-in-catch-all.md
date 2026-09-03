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
#   (b) enrich a LOG line (e.g. logger.warning(..., type(exc).__name__)) with
#       the caught exception's class name — never the error body/message a
#       caller receives.
# A block that converts ValidationError to a generic AgentError while logging
# nothing is non-compliant with SI-2. A block that instead interpolates the
# class name into the WIRE message/error body is ALSO non-compliant — see the
# amendment below.
```

## Prevention
When planning error-handling changes in the task loop, place `except
ValidationError` (and any other structured-error subclasses) above `except
Exception`. Log `exc.__class__.__name__` (e.g. `logger.warning("... error_type=%s",
type(exc).__name__)`) so an operator can distinguish validation failures from
runtime failures without parsing the message string — but keep the wire-facing
error message/body a FIXED, generic string. Never set it (or any field a
caller reads) to the exception's class name.

### Amendment (RT-006 / RT-002, agent/bedrock.py + agent/runner.py)
This LRN's original Check/Prevention text told implementers to put the class
name in the error BODY — `error.type`, or interpolated into the message
string — reaching the caller. That was wrong and got implemented literally in
two places before being caught: `BedrockModelClient.converse` (RT-006) and
`agent/runner.py`'s deferred (GH-87) background awaiter, `_run_deferred_background`
(RT-002), both wired `f"... ({type(exc).__name__})"` straight into
`WireError.message` / the user-facing status `Message` — letting an untrusted
A2A/AG-UI caller learn the exact upstream failure mode (e.g.
`NoCredentialsError`, `ThrottlingException`) an arbitrary tool or model
provider raised. The class name is an **operator-facing diagnostic**: log it,
never wire it. The Check/Prevention text above reflects the corrected policy;
treat any earlier reading of this LRN that says "the enriched error response
must include `error.type`" as superseded.
