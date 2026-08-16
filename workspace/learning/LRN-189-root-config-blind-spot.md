---
id: LRN-189
title: Root config files invisible to all four archive-gate clauses
category: sdk
severity: high
source: redteam
date: 2026-08-15
---

## What happened
`pyproject.toml` was modified mid-wave with no todo Creates:/Modifies: line,
evading `offendingPaths`, `offendingHarnessPaths`,
`offendingUndeclaredImports`, and `offendingUndeclaredScope` at once. The
undeclared change weakened `filterwarnings` to suppress ALL unraisable
exceptions in `BaseEventLoop.__del__`, masking a real `agent_sdk`
event-loop leak, not just the pytest-asyncio artifact it cites. `DESIGN.md`
§4.0 (stable-core contract) was likewise changed undeclared.

## Root cause
The four gate clauses partition tracked files by wave-scope dir,
HARNESS_DIRS, and `.py`-under-`agent_sdk` — root-level config/doc files
(`pyproject.toml`, `DESIGN.md`, `REVIEWS.md`) sit outside all three.

## Check
`git status --short | grep -E '^ ?M (pyproject\.toml|DESIGN\.md|REVIEWS\.md)$'`
at archive time; each hit needs its own Creates:/Modifies: line. Confirm an
`offendingUndeclaredRootConfig` clause exists in all four wave runners plus
`tests/test_workflows.py`.

## Prevention
When a wave touches `filterwarnings`, pytest config, or DESIGN.md's
stable-core contract, require those root files in Creates:/Modifies:, and
require the gate carry a root-config clause, ported to all four runners.
