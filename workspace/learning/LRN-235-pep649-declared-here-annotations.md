---
id: LRN-235
title: PEP 649 breaks raw __annotations__ "declared-here" check
category: sdk
severity: high
source: redteam
date: 2026-09-03
---

## What happened
`_field_summary` in `agent_sdk/a2ui/catalog.py` reads
`vars(klass).get("__annotations__", {})` to decide whether a domain
card redeclared a field. On Python 3.14 (PEP 649) this returns `{}`
for any class whose module lacks `from __future__ import annotations`,
so `declared_here` is always False and redeclared fields (e.g. a
card's own `metadata`) silently drop from the LLM teaching string.

## Root cause
Raw `vars(cls)["__annotations__"]` is not a portable per-class
annotation read under PEP 649 lazy evaluation — it depends on whether
the defining module opted into the PEP 563 future import.

## Check
grep `agent_sdk/a2ui/catalog.py` for `vars(` near `__annotations__`
and confirm it instead uses `inspect.get_annotations(cls)`. Confirm a
regression test's domain-card class lives in a helper module WITHOUT
`from __future__ import annotations`.

## Prevention
When planning code that asks "did this exact class declare this
field", require `inspect.get_annotations(cls)`, never raw
`vars(cls)["__annotations__"]`, and require the pinning test to live
in a module lacking the PEP 563 future import.
