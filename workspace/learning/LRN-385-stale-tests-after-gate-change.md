---
id: LRN-385
title: Gate semantics change left old-ruling tests red
category: testing
severity: critical
source: redteam
date: 2026-10-15
---

## What happened
GH-180 made `allows()` in `agent_sdk/a2ui/translator.py` gate domain types on declared catalogs. Two GH-56 tests in `tests/test_a2ui_group_d.py` still asserted the old "emit regardless of catalog" rule, so the full suite went red (2 failed, 3437 passed) and /sdk-release would refuse to tag.

## Root cause
The todo did not list tests pinning the old ruling, and only the new test file was run.

## Check
Run the full suite (`pytest tests/`), not one file. Grep `tests/` for the old ruling's issue ID (e.g. `grep -rn "gh56" tests/`) and for direct calls to the changed gate; confirm none assert the old behaviour.

## Prevention
When planning a change to a gate's semantics, add a todo step to grep `tests/` for the old ruling's issue ID and direct gate calls, update or retire each pinning test in the same todo, and require a full-suite run before sign-off. Do not loosen the gate to satisfy old tests.
