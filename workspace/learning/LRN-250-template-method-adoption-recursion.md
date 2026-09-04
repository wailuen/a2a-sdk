---
id: LRN-250
title: Template-method adoption shim recurses on concrete-subclass super() calls
category: sdk
severity: high
source: redteam
date: 2026-09-03
---

## What happened
Converting `ContentModel.to_plain_text()` into a template over a new `_body_text()`
hook broke `super().to_plain_text()` for any subclass of a CONCRETE card, not just
direct subclasses of the ABC. `class MyKpi(KpiCard): def to_plain_text(self): return
super().to_plain_text() + "x"` raised `RecursionError` — fully legal code under the
prior API.

## Root cause
`__init_subclass__` renames the override to `_body_text` and removes `to_plain_text`
from the subclass's own `__dict__`, so `super().to_plain_text()` skips past the
already-adopted parent override and resolves to `ContentModel.to_plain_text`, which
re-invokes the same subclass's `_body_text` — infinite recursion. The docstring's
claim that `super()` can only hit the abstract stub is false for grandchild classes.

## Check
Add/confirm a test subclassing a CONCRETE built-in card (e.g. `KpiCard`) that calls
`super().to_plain_text()` inside its own override — must not raise `RecursionError`.
`grep -n "__init_subclass__" agent_sdk/models/content_types.py`.

## Prevention
When planning a template-method migration (concrete method → base-class hook),
require the adoption shim be tested against subclass-of-a-subclass chains where the
middle class is concrete and itself uses the old override API — not only
direct-subclass-of-ABC cases.
