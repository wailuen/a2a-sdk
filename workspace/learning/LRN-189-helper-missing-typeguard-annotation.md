---
id: LRN-189
title: isinstance-check helper without TypeGuard breaks mypy narrowing
category: sdk
severity: high
source: redteam
date: 2026-09-03
---

## What happened
`is_content_sequence` in agent_sdk/agent/loop.py was extracted to centralize
an isinstance check but annotated `-> bool`. Neither call site narrows the
type anymore, so mypy raised 2 new errors (union-attr, misc) on an
otherwise mypy-clean HEAD.

## Root cause
A `bool`-returning helper cannot narrow its argument's type at the call
site the way an inlined `isinstance(...)` check does — only a `TypeGuard`
return annotation preserves narrowing across the function boundary.

## Check
`grep -n "def is_.*-> bool:" agent_sdk/` for any predicate helper whose name
implies a narrowing check (is_, has_) but wraps an isinstance/instance-check
without `TypeGuard` in its return type; confirm `mypy agent_sdk/` is 0 errors.

## Prevention
When planning extraction of an inline `isinstance` check into a shared
helper, require the helper's return type to be `TypeGuard[...]` (imported
from `typing`) whenever any call site relies on narrowing afterward, and add
a mypy run to the unit's acceptance check before marking it done.
