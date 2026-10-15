---
id: LRN-378
title: Removed base-class opt-out flag must be Breaking and fail loud
category: sdk
severity: high
source: redteam
date: 2026-10-15
---

## What happened
`_Wire._rejects_non_finite` (content_types.py) was removed and listed under CHANGELOG Fixed with no Migration line. A downstream `_Wire` subclass still setting it now silently coerces nan to None, because pydantic turns the name into a private attr.

## Root cause
A documented opt-out was treated as an internal detail, and removal had no guard for subclasses that still set it.

## Check
`grep -n "_rejects_non_finite" CHANGELOG.md agent_sdk/` shows it under Breaking with a **Migration:** line, and a test confirms a subclass defining it raises TypeError.

## Prevention
When planning removal of any documented base-class flag, require a Breaking entry with Migration, plus a `__init_subclass__` TypeError for subclasses still defining it, and a test.
