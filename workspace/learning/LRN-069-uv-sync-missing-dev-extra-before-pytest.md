---
id: LRN-069
title: uv sync without --extra dev breaks pytest steps
category: testing
severity: high
source: redteam
date: 2026-06-18
---

## What happened
`harness/skills/new-agent/SKILL.md` Phase 5 step 1 ran `uv venv --python 3.12 && uv sync --frozen` (no dev extra), then step 2 immediately ran `.venv/bin/python -m pytest -q`. Because `pytest`, `pytest-asyncio`, and `httpx` live under `[project.optional-dependencies].dev`, the venv contained no test dependencies and the green-baseline test step failed at import time.

## Root cause
`uv sync --frozen` installs only core dependencies; extras are opt-in. Any harness step that calls `pytest` after a bare `uv sync` silently produces a broken venv — the error surfaces only at runtime, not at install time.

## Check
`grep -rn 'uv sync' harness/skills/ | grep -v '\-\-extra dev'` — every match followed (within 5 lines) by a `pytest` invocation is a violation. Also run: scaffold a new agent with the skill and confirm `pytest -q` exits 0.

## Prevention
When planning any harness install step that is followed by `pytest` or any test runner, always use `uv sync --frozen --extra dev` (not bare `uv sync --frozen`). Flag bare `uv sync` in phase plans where the next step is test execution.
