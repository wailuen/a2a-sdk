---
id: LRN-140
title: Resolved-marker block skips JSON normalization, poisons message history
category: protocol
severity: high
source: redteam
date: 2026-09-02
---

## What happened
The `__resolved__` marker block folds `result.value` into `messages` raw, while the
sibling result block runs the same value through `fold_result_content` first. A
`Reusable` wrapping a pydantic `BaseModel` — an explicitly supported shape per
`ToolDecl.emits` matching — plants a live object inside `messages`, and the next
`json.dumps` over the transcript raises `TypeError`, breaking the whole conversation.

## Root cause
The marker-fold code path was added without reusing the existing `fold_result_content`
normalization the adjacent result block already relies on.

## Check
Register a tool returning `Reusable(value=<a pydantic BaseModel>)`, run one turn, and
confirm `json.dumps(record.messages)` succeeds. Then grep `loop.py` in two places:

1. The `RESOLVED_MARKER_KEY` marker build (`resolved_marker = {...}`) — confirm its
   `"value"` field is built from `jsonable_reuse_value(result.value)`, not `result.value`
   directly. `jsonable_reuse_value` — not `fold_result_content` — is the required
   normalizer here: `fold_result_content` returns a `{"json": ...}` / `{"text": ...}`
   *content-block* wrapper, the wrong shape to assign into a marker's `"value"` field.
2. The sibling result block (`content_blocks: list[...] = [fold_result_content(result)]`)
   — confirm it still normalizes through `fold_result_content`.

Both symbol names are load-bearing for this guard; if either is renamed again, update
this Check in the same wave, per LRN-140's own Prevention below.

## Prevention
Any code folding a new value into `messages` must route it through the same
JSON-normalization helper the rest of that message uses — never assume a value is
JSON-safe just because a nearby sibling block already normalizes it.
