---
id: LRN-138
title: reuse_fields_for_model crashes on get_type_hints for locally-scoped pydantic models
category: sdk
severity: high
source: redteam
date: 2026-09-02
---

## What happened
`reuse_fields_for_model` calls `typing.get_type_hints` on a tool's `input_model` at
decoration time. Pydantic resolves a locally-scoped model's annotations against the
defining frame's locals, but `get_type_hints` only checks module globals — so a model
built inside a function crashes tool registration with `NameError`, even for tools
using no `ReuseKind` at all.

## Root cause
Re-resolving annotations that pydantic already resolved, instead of reading pydantic's
own resolved metadata, reintroduces a resolution gap pydantic itself doesn't have.

## Check
Register a `@tools.tool` whose `input_model` is defined inside a function body
(referencing a sibling locally-defined class) and confirm registration succeeds; grep
`agent_sdk/agent/reuse.py` for `get_type_hints` and confirm it is not used to extract
`ReuseKind` metadata.

## Prevention
When planning a change that reads `Annotated` extras off a pydantic model, read
`model_fields[...].metadata` — never re-run `typing.get_type_hints` on a model pydantic
already built.
