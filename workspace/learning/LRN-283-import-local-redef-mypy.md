---
id: LRN-283
title: Name imported and redefined locally breaks mypy gate
category: sdk
severity: high
source: redteam
date: 2026-10-10
---

## What happened
`routes/oauth.py` imported `_runtime` from `..auth.middleware` and also defined it locally. `mypy agent_sdk` reported `no-redef` and ruff F811. Tests passed, but the /sdk-test gate and /sdk-release were blocked.

## Root cause
An import block was widened without running mypy over the whole package.

## Check
Run `uv run mypy agent_sdk` and `uv run ruff check agent_sdk`; confirm zero errors, including no `no-redef` or F811.

## Prevention
When a todo widens an import list or adds a local helper, add an AC that `uv run mypy agent_sdk` and ruff pass on the full package before unit redteam, not just pytest.
