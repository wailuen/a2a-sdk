---
id: LRN-017
title: wave-cycle.js — schema-gated gate agents required at redteam and proto-fix checkpoints
category: harness
severity: high
source: GH-19/20/21/22 (2026-06-15)
---

# LRN-017 — wave-cycle.js gate architecture

## Root cause

The wave-cycle lacked test-gate checkpoints after fix batches, meaning:

- **GH-19**: Unit/phase redteam fix loops ran `parallel(fixTasks)` but never
  re-ran pytest to confirm the fixes actually turned red→green.  A fix that
  introduced a new failure could proceed silently to archive.

- **GH-20**: After `proto:fix` patched a protocol violation, no gate ran before
  the recheck dispatch.  A proto fix that broke tests was never caught.

- **GH-21**: Implement agents were told `do not run pytest` blanket — leaving them
  unable to confirm their own RED→GREEN transition, and sometimes running the full
  suite (causing memory pressure).

- **GH-22**: Archive ran regardless of test-suite colour, allowing red commits
  into the learning store.

## Fix

`GATE_SCHEMA = {exitCode, passCount, failCount, failures[]}` added.

Gate agents using this schema inserted at four checkpoints:
1. After each unit-redteam fix batch — `gate:unit:<group>:r<N>`
2. After each phase-redteam fix batch — `gate:phase:r<N>`
3. After `proto:fix` before recheck dispatch — `gate:proto:fix`
4. At the top of Archive phase — `gate:pre-archive`

Each gate: if `exitCode !== 0` → set `testsRed = true`, dispatch targeted
`fix:tests:*` agent with the specific failing test names.  `testsRed` returned
in the wave result object alongside `protocolBlocked`.

Implement agents: now run **scoped** tests only (`pytest -q tests/test_<specific>.py`)
to confirm their own RED→GREEN.  Full suite is the gate's job.

## Rule going forward

**Every fix batch in the wave cycle must be followed by a schema-gated pytest
gate.** The gate's `exitCode` is the authoritative pass/fail signal — never rely
on a fix agent self-reporting success.  Archive is unconditionally blocked when
`testsRed` or `protocolBlocked` is true.

Never add `pytest -q tests/` (explicit path) to any agent prompt — always use bare
`pytest -q` so `pyproject.toml` controls scope (see LRN-014).
