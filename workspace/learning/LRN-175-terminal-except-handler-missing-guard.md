---
id: LRN-175
title: Terminal exception handlers lack already-terminal guard present on other writers
category: sdk
severity: high
source: redteam
date: 2026-09-03
---

## What happened
`run_task_worker`'s terminal `except AgentError` (runner.py:1385) and `except
Exception` (runner.py:1423) handlers have no already-terminal guard. An exception
escaping `run_loop` after a concurrent `tasks_cancel` commits CANCELED overwrites it
with FAILED, persists FAILED over CANCELED via `set_task_status(store=store)`, and
publishes a second terminal frame on a stream the canceller already closed.
Reproduced live with a tool returning a value whose `__str__` raises after a
mid-call cancel.

## Root cause
The top-of-loop guard (runner.py:1212) only sees events `run_loop` yields, so it
cannot see a raise between a tool await and the next yield.
`_run_deferred_background._fail` (runner.py:826) already carries the guard; the two
worker except-handlers were never given the same one.

## Check
`grep -n "if record.task.status.state in TERMINAL_STATES" agent_sdk/agent/runner.py`
— must appear before the repair/set_task_status/publish sequence in both the
`AgentError` and catch-all `Exception` handlers at run_task_worker's tail, not only
in `_fail`. Extend tests/test_rtb102_worker_terminal_race_guard.py with an exception
(not just DoneEvent) variant.

## Prevention
When planning any change that adds or touches a terminal-state writer, require the
already-terminal bail-out on every code path that can write terminal status —
including catch-all exception handlers — not only the primary event-consumer loop.
