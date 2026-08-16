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
grep -n 'except ToolInputValidationError\|except Exception' \
  agent_sdk/agent/loop.py agent_sdk/routes/mcp.py agent_sdk/routes/admin.py \
  agent_sdk/contrib/commitments/executor.py
grep -n 'frame_locations' \
  agent_sdk/common/redact.py agent_sdk/agent/loop.py \
  agent_sdk/routes/mcp.py agent_sdk/routes/admin.py \
  agent_sdk/contrib/commitments/executor.py
```
GH-135 replaced the original "re-raise or enrich" fix with a discriminator
exception type — `ToolInputValidationError` (`agent_sdk/agent/registry.py`) —
raised ONLY by the input-model coercion step, never by a `ValidationError` the
tool body itself raises downstream. Every dispatch surface (loop.py's three
tool-call sites, mcp.py's `tools/call`, admin.py's try-tool, and
`contrib/commitments/executor.py`'s `_fire` — RT-012: the FOURTH C-012
surface, easy to miss because it fires in the background with no caller
observing the failure) must place `except ToolInputValidationError` above the
generic `except Exception`, and the two branches have DIFFERENT, fixed
contracts — conflating them is non-compliant:
- `except ToolInputValidationError`: report `safe_validation_message()`
  (loc + type only, schema-walked — SI-2) to the caller as input-invalid.
  This is the ONLY branch allowed to describe the failure as the caller's
  fault.
- `except Exception`: log `type(exc).__name__` AND `frame_locations(exc)`
  (never `str(exc)`/`exc.args` — SI-2, can embed body-supplied values) via
  `logger.error`, with no `exc_info`, and return the FIXED, non-interpolating
  message `f"tool '{tc.name}' failed"` to the caller/wire. `frame_locations()`
  (`agent_sdk/common/redact.py`, next to `safe_error_text`) formats the last 5
  traceback frames' `filename:lineno` only — never `FrameSummary.line`, which
  echoes source text that could itself embed a caller-derived literal — so
  logging it satisfies SI-2 without sacrificing diagnosability (RT-010: a
  type-only log left a genuine tool-body bug undiagnosable — bare class name,
  no file/line). The exception class name AND the frame locations are
  LOG-ONLY diagnostics; neither is ever echoed into the error body the model
  or wire response receives.

  **Carve-out (RT-012):** `contrib/commitments/executor.py`'s `_fire` is the
  one dispatch surface that returns nothing to a caller — it fires in the
  background, so "the error body the model or wire response receives" does
  not apply to it. Its generic branch persists `type(exc).__name__` as the
  commitment's `last_error` column (`self._store.mark_failed(commitment.id,
  type(exc).__name__)`) in addition to logging it. This is deliberate, not a
  Check violation: `last_error` is a durable, operator-facing diagnostic on
  the commitments store row, not a caller-facing error body — the
  `Commitment` dataclass (`contrib/commitments/backend.py`) that
  `CommitmentsSource.get()`/`.list()` hand back to tool code carries no
  `last_error` field, and no FastAPI route exposes the column, so the class
  name never reaches a model or wire response. Persisting the class name
  (rather than a generic constant) is intentional here too: it is the only
  per-commitment diagnostic an operator has for a background failure nobody
  observed live. Pinned by
  `tests/test_contrib_commitments.py::test_executor_body_validation_error_keeps_class_name_reason`.
  If `last_error` (or any other commitments-store field) is ever surfaced on
  a route or handed back through `CommitmentsSource`, this carve-out lapses
  and the field must switch to a stable enumerated reason (alongside
  `INVALID_TOOL_INPUT_REASON`) in the same change.

A block that reports a body-raised `ValidationError` as caller-input error
(missing the `ToolInputValidationError` split), or whose generic branch omits
the type+frames log line (or calls its own inline frame-formatting instead of
the shared `frame_locations()` helper), or whose generic branch interpolates
the exception class name/message/frames (or `str(exc)`) into the
caller-facing message (a message, response body, or any value returned to a
tool caller — the commitments executor's persisted `last_error` column is the
one documented exception per the carve-out above), is non-compliant.

## Prevention
When planning error-handling changes to any tool-dispatch surface (the task
loop, mcp.py's `tools/call`, admin.py's try-tool), route input-schema-coercion
failures through a distinct exception type raised only by the coercion step —
never a bare `except ValidationError` wrapping both coercion and the tool
body, which cannot tell "caller sent bad arguments" apart from "the tool body
raised ValidationError for an unrelated reason" (GH-135). Keep the generic
`except Exception` branch's caller-facing message FIXED, and add a same-branch
log line binding `type(exc).__name__` plus `frame_locations(exc)` via the
shared helper — both are diagnostics, never wire content. Whenever this
branch shape changes on any one dispatch surface, update it (and its
same-branch inline comment's parity claim) on all four sites — mcp.py,
admin.py, and all three of loop.py's — in the same change, and re-verify this
Check's grep against every touched path before closing the wave (LRN-133): a
wave that changes how a live learning's Check is satisfied must rewrite that
Check in the same change, not leave it asserting the reversed behavior
(RT-004: a rewritten Check that only matched one of N "at parity" surfaces
left the other surfaces' comments — and this Check itself — silently false
until the next redteam pass caught the drift).
