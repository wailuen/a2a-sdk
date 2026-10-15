---
id: LRN-382
title: Removal guard must catch the documented declaration form
category: sdk
severity: high
source: redteam
date: 2026-10-15
---

## What happened
The _rejects_non_finite removal guard in _Wire.__pydantic_init_subclass__ only checked __private_attributes__. The documented form `_rejects_non_finite: ClassVar[bool] = True` is not a private attribute, so it was accepted silently and floats were coerced instead of rejected. The CHANGELOG promised a TypeError.

## Root cause
The guard was tested against a variant form, not the exact form the removed hook was documented with.

## Check
Verify a test defines a _Wire subclass with `_rejects_non_finite: ClassVar[bool] = True` and asserts TypeError at class definition; also check the unannotated form.

## Prevention
When planning removal of a public hook, list every declaration form from the old docs and require a test per form (LRN-064).
