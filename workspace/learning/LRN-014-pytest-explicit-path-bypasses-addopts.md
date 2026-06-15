# LRN-014 — `pytest -q tests/` bypasses `addopts` ignore exclusions

**Source:** GH-18 (2026-06-15) — wave-cycle.js agent prompts  
**Severity:** High (caused memory-intensive suites to run during waves, compounding concurrent agent memory pressure)

## Root cause

When pytest is invoked with an explicit positional path (`pytest -q tests/`), it ignores the
`testpaths` and `addopts` settings in `pyproject.toml`. Any `--ignore=tests/performance`
flags in `addopts` are silently bypassed for directories discovered via the explicit argument.

Running `pytest -q` (no path) lets pytest read `testpaths` and `addopts` from config,
respecting all configured exclusions.

## Fix

In `harness/workflows/wave-cycle.js`, all agent prompts that instructed subagents to run
`pytest -q tests/` were changed to `pytest -q` (5 occurrences: implement serial, implement
parallel, unit-redteam fix loop, phase-redteam fix loop, proto-fix).

## Rule going forward

**Never pass an explicit directory to pytest in agent prompts.** Always use bare `pytest -q`
so `pyproject.toml` controls the test scope. This applies to all wave, redteam, and fix-loop
agent instructions.
