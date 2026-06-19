---
id: LRN-054
title: uv sync without --extra dev omits test deps and breaks pytest
category: ops
severity: high
source: redteam
date: 2026-06-18
---

## What happened
Phase 5 of the setup skill changed `uv pip install -e ".[dev]"` to `uv sync --frozen`, then immediately ran `.venv/bin/python -m pytest -q`. Because `pytest`, `pytest-asyncio`, and `httpx` are declared under `[project.optional-dependencies].dev` (PEP 621 extras), bare `uv sync` does not install them — the test step fails with `No module named pytest`.

## Root cause
`uv sync` excludes all PEP 621 optional-dependency extras by default; the only way to include the `dev` extra is to pass `--extra dev`. The prior `uv pip install -e ".[dev]"` made the extra explicit; the replacement dropped it silently.

## Check
```bash
# In any skill/Dockerfile/CI step that runs pytest after uv sync, verify
# the sync command includes the dev extra:
grep -n 'uv sync' harness/skills/setup/SKILL.md | grep -v '\-\-extra dev'
# Any hit that is followed by a pytest invocation is a bug.
```

## Prevention
When planning a `uv sync` step that precedes a pytest invocation, ensure the command is `uv sync --frozen --extra dev`. Never drop `--extra dev` from a sync that needs test-only packages declared under `[project.optional-dependencies].dev`. The upgrade skill's pattern (`uv sync --frozen --extra dev`) is the canonical reference.
