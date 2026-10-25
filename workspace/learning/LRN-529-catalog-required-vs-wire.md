---
id: LRN-529
title: Catalog required-ness must match what wire() really writes
category: protocol
severity: high
source: redteam
date: 2026-10-25
---

## What happened
In agent_sdk/a2ui/catalog.py, `_summary_at_depth` did not skip `exclude=True` fields, and `_wire_required` treated any default_factory as required. A `Field(default_factory=list, exclude=True)` field showed as REQUIRED though wire() never writes it.

## Root cause
Required-ness was derived from defaults only, ignoring other ways wire() omits a field (exclude, exclude_none, serializer pops).

## Check
Run tests/test_gh258_catalog.py: for an excluded default_factory field, assert it is absent from the summary and `required_paths(summary) <= emitted_paths(wire())`.

## Prevention
When planning schema or summary derivation, require a test that compares against a real wire() output for each omission mode: exclude, exclude_none, and serializer pops.
