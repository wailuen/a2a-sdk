---
id: LRN-150
title: Cross-turn index seeded from newest-terminal-task-only decays after one hop
category: protocol
severity: high
source: redteam
date: 2026-09-02
---

## What happened
AG-UI's reuse carriage reads `store.context_messages(thread_id, identity)`, which
returns only the single most-recent terminal task's messages
(`max(candidates, key=created_at)`). Each AG-UI run starts a fresh `TaskRecord` and does
not fold `prior` into its own persisted messages, so after one intervening unrelated run
the `__resolved__` marker is gone: `$ref` no longer resolves, and a wrong raw id is
silently accepted — reopening GH-148 on a 3-turn conversation despite CHANGELOG/DESIGN.md
claiming it fixed with no hop limit, and a shipped test that only exercises two runs.

## Root cause
The carrier was validated for exactly one hop (two consecutive runs) and the seeding
mechanism (single newest-terminal-task lookup, no forward propagation) doesn't survive a
third run.

## Check
`grep -n "context_messages" agent_sdk/tasks/memory.py agent_sdk/routes/ag_ui.py` —
confirm whether the resolved index is propagated transitively or only sourced from the
newest terminal task. Add a 3-run regression test on one `threadId` with an intervening
unrelated run, asserting both `$ref` resolution and wrong-raw-id rejection still hold.

## Prevention
When planning a cross-turn index that a planner claims survives "a conversation," require
the plan to test at least 3 turns (not 2) including an intervening unrelated turn, and to
either propagate the index transitively (each run re-seeds the next) or scan every
terminal task in the context, not just the newest.
