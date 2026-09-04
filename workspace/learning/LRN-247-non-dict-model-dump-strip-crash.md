---
id: LRN-247
title: Unconditional dict-strip on model_dump() crashes for RootModel/list-shaped dumps
category: sdk
severity: high
source: redteam
date: 2026-09-03
---

## What happened
The RT-001 `__resolved__` strip in `loop.py` calls `dump.pop(...)`
unconditionally on the result of `model_dump()`. A `RootModel[list[str]]`
(or any model with a serializer returning a list/str) dumps to a non-dict,
so `.pop()` raises `TypeError`/`AttributeError`. The call sits outside any
try/except and fires after the tool's `ToolResultEvent(ok=True)` has already
streamed, so a legal, previously-working tool return crashes the whole task
mid-turn instead of just that call.

## Root cause
The strip assumed `model_dump()` always returns a dict; `RootModel` and
custom `@model_serializer`s legitimately return non-dict shapes, and this
call site has no isinstance guard even though the sibling call in
`runner.py` already does.

## Check
`fold_result_content(RootModel[list[str]](["a", "b"]))` must return a
normal folded result, not raise. `grep -n "RESOLVED_MARKER_KEY" agent_sdk/agent/loop.py`
— every `.pop(RESOLVED_MARKER_KEY` call must be preceded by an
`isinstance(dump, dict)` check.

## Prevention
When planning any post-`model_dump()` dict operation, require an
`isinstance(dump, dict)` guard (with a defined non-dict fallback shape) and
a regression test folding a `RootModel`/scalar-serializing return through
the real code path, not just a plain BaseModel.
