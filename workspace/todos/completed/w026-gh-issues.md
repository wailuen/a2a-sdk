# w026 — GitHub issues GH-90, GH-91

Sourced from open issues on wailuen/a2a-sdk. Both items are independent.
Run in parallel (group:G).
Target: 0.5.32.

---

- [x] `GH-90` harness/acceptance: A2A multi-turn driver resends terminal taskId (404/-32001) instead of continuing via contextId ‖ group:G
  - Creates: (modifies `harness/workflows/acceptance-api.js`, modifies `harness/skills/acceptance/SKILL.md`)
  - Reads: `harness/workflows/acceptance-api.js`, `harness/skills/acceptance/SKILL.md`
  - Severity: high
  - Root cause: The A2A multi-turn driver in `acceptance-api.js` persists turn-1's `taskId` to `/tmp/acc-{RUN_KEY}-a2a-task.txt` (line 152) and on turns 2+ unconditionally injects `msg["taskId"] = task_id` (lines 123-127). Because a completed A2A task is terminal, the server returns 404/`-32001` on every subsequent turn, causing all multi-turn A2A scenarios to fail with false `transport-divergence` results. The fix: (1) capture `contextId` from the first turn's SSE stream (from the `kind:"task"` or `kind:"status-update"` event), persist it alongside the task file; (2) on turns 2+, send `contextId` with no `taskId` for continuation of a completed task — only reuse `taskId` when the prior task's status was `input-required`; (3) track `last_state` from status-update events to gate this logic.
  - AC: turn 2+ of a multi-turn A2A scenario sends `contextId` (not `taskId`) when turn 1 ended `completed`; only sends `taskId` when turn 1 ended `input-required`; SKILL.md Phase 2A prose updated to reflect the correct rule; no Python test file needed (harness-only change, but logic must be readable/verifiable from the acceptance-api.js source)
  - GH: https://github.com/wailuen/a2a-sdk/issues/90

- [x] `GH-91` app: SC-F1 emits-validation has no path for async-generator tool return annotations ‖ group:G
  - Creates: (modifies `agent_sdk/app.py`, creates `tests/test_gh91_generator_emits_validation.py`)
  - Reads: `agent_sdk/app.py`, `agent_sdk/agent/registry.py`
  - Severity: low
  - Root cause: `_validate_emits` in `agent_sdk/app.py:284-289` rejects any annotation whose `__origin__` is not `Union`. For async-generator tools (`ToolDecl.is_generator=True`, set in `registry.py:58`), the honest return annotation is `AsyncIterator[T]` or `AsyncGenerator[T, None]` — both have a non-`Union` `__origin__` — so they hit the `ValueError` branch. Fix: add an early branch in `_validate_emits` that detects `entry.decl.is_generator == True` and `__origin__` is `AsyncIterator`/`AsyncGenerator`, extracts the first type arg via `typing.get_args(ret)[0]`, and validates that yielded type against `emits` (same `issubclass`/`Union` logic as for coroutine tools).
  - AC: `@tools.tool(emits=T)` async-generator with `-> AsyncIterator[T]` annotation passes `_validate_emits` at boot; `-> AsyncIterator[WrongType]` raises `ValueError` with a clear message; `-> AsyncGenerator[T, None]` (two-arg form) also accepted; omitting the annotation still works (existing path); tests cover all four cases; no mocks
  - GH: https://github.com/wailuen/a2a-sdk/issues/91
