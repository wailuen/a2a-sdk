---
id: LRN-039
title: SC-F1 emits annotation validator must skip — not raise — when eval_str resolution fails
category: sdk
severity: high
source: redteam
date: 2026-06-16
---

## What happened
`_validate_emits()` in `app.py` calls `inspect.get_annotations(fn, eval_str=True)`.
When the annotated type (e.g. `MarketBriefing`) is imported locally inside a
function rather than at module level, Python cannot resolve the name against
`fn.__globals__` and raises `NameError`. The except clause falls back to
`fn.__annotations__`, which returns a raw string `'MarketBriefing'`. That string
passes the `ret is None` guard but fails all class checks, causing a spurious
`ValueError` at `build_app()` time even though the annotation is correct.

## Root cause
After the eval_str fallback, `ret` may be an unresolved string rather than a
type object. The validator has no branch for this case and falls through to
the unconditional `raise ValueError`.

## Check
```
grep -n "eval_str" agent_sdk/app.py
# Confirm the except branch checks: if isinstance(ret, str): log warning and continue
```
Run `pytest tests/test_mcp_conformance_w9.py::test_sc_c7_market_briefing_structured_content_is_string -x`
and confirm no `ValueError` at fixture setup.

## Prevention
When planning changes to `_validate_emits` or any annotation-inspection loop,
ensure that after the `eval_str` fallback, any `str`-typed `ret` is treated as
unresolvable and skips with a logged warning rather than raising — only raise
for positively-resolved class types that genuinely mismatch `emits`.
