---
id: LRN-074
title: inspect.get_annotations collapses explicit `-> None` and missing annotation to the same value
category: correctness
severity: medium
source: redteam
date: 2026-06-19
---

## What happened
`_validate_emits` in `app.py` called `inspect.get_annotations(fn, eval_str=True)` then checked `if ret is None: continue` to skip unannotated tools. But `inspect.get_annotations` resolves both a missing return annotation AND an explicit `-> None` annotation to `None` (the Python singleton). A tool declaring `emits=SomeContentModel` but annotated `-> None` therefore skipped the SC-F1 mismatch check entirely instead of raising ValueError — an explicit contradiction was silently permitted.

## Root cause
`resolved.get("return")` returns `None` for two distinct cases:
1. `'return'` key is absent (unannotated — legitimately skip)
2. `'return'` key is present with value `None` (explicit `-> None` — must flag)

`dict.get` cannot distinguish these; a bare `if ret is None: continue` treats both identically.

## Fix
Consult `fn.__annotations__` (the raw dict, not the resolved copy) to distinguish the two cases:
```python
if ret is None:
    raw = getattr(fn, "__annotations__", {})
    if "return" not in raw:
        continue  # genuinely unannotated — permitted
    # explicit `-> None` with a non-None emits: fall through to ValueError
```

## Check
grep -n 'if ret is None' agent_sdk/app.py
# Must be followed immediately by a raw __annotations__ presence check,
# not a bare `continue`.

## Prevention
Any annotation validator that branches on `ret is None` must always check `__annotations__` key presence to avoid silently skipping the explicit-None case. This applies to all SC-F1 and similar emits/return-type consistency checks.
