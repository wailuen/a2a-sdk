# w054 — GitHub issues 185, 187

Sourced from open issues on wailuen/a2a-sdk. The two items touch different files and are independent.
Run in parallel (group:G1). GH-186 is deferred by ruling and NOT in this wave.
Target: 0.16.0 (new public API `current_identity`).

---

- [ ] `GH-187` Retry after a failed task inherits its partial tool results, so the retry emits no data part ‖ group:G1
  - Creates: (modifies `agent_sdk/tasks/memory.py` (`context_messages`, `context_reusable_messages`), `agent_sdk/tasks/store.py` (abstract docstrings), new `tests/test_gh187_retry_after_failed_task.py`, updated existing tests `tests/test_rt002_context_messages_max_turns_cliff.py`, `tests/test_rtb002_cancel_repair_failure_still_publishes_final.py`, `tests/test_rtb003_taskstore_persist_status_hook.py`, `tests/test_rtb007_persist_status_ordered_after_repair.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/models/a2a.py` (`TERMINAL_STATES`, ~line 106), `agent_sdk/routes/a2a.py` (`_create_task_record`), `agent_sdk/agent/reuse.py` (`scan_resolved`)
  - Severity: medium
  - Root cause: `context_messages()` seeds a new task from the most recent task in `TERMINAL_STATES`, which includes FAILED. A task that fails part-way (e.g. model 429 after a tool round) leaves tool calls and results in its transcript; the retry inherits them, the model answers from the stale results and calls no tool, so no data part / A2UI card is emitted.
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/187#issuecomment-6217406480
  - AC: `context_messages()` picks the most recent COMPLETED task in the context (same identity scoping and `_turn_boundary_slice` cap as today); FAILED, CANCELED and REJECTED tasks are skipped entirely, including their user message.
  - AC: `context_reusable_messages()` applies the same rule: `__resolved__` markers from FAILED/CANCELED/REJECTED tasks are not reused.
  - AC: Test reproduces the issue: turn 1 completes; turn 2 runs a tool, then the model call fails → task FAILED; turn 3 in the same contextId is seeded from turn 1's transcript only (no turn-2 tool results), and with a scripted fake model that calls the tool, turn 3 emits its own artifact/data part.
  - AC: A context whose only prior tasks failed gives an empty seed (fresh start), not an error.
  - AC: Existing contextId continuation tests (completed → completed) stay green unchanged.
  - AC: CHANGELOG `[Unreleased]` Fixed entry names the behaviour change and the accepted trade-off (a bare "try again" after a failure has no memory of the failed request), with the ruling URL.
  - GH: https://github.com/wailuen/a2a-sdk/issues/187
  - Reuses: C-005  # Put the new completed-only rule in the TaskStore contract (agent_sdk/tasks/store.py abstract docstrings for context_messages and context_reusable_messages) and in InMemoryTaskStore (agent_sdk/tasks/memory.py:299-304 and :328-333, today two copies of the same TERMINAL_STATES filter). Do not add a second state filter downstream in C-016 scan_resolved (agent_sdk/agent/reuse.py) or in routes/a2a.py::_create_task_record. The store is the only place durable subclasses in agent repos inherit the rule from.
  - Reuses: C-017  # Keep the _turn_boundary_slice cap (built on C-017 is_user_turn_boundary) applied to the chosen COMPLETED task exactly as today. Changing which task is picked must not change or re-implement the boundary slice.

- [ ] `GH-185` Expose the request's Identity to tools and SourceAdapters (request-scoped) ‖ group:G1
  - Creates: (new `agent_sdk/auth/context.py` (ContextVar + `bind_identity`/`unbind_identity`/`current_identity`), modifies `agent_sdk/auth/__init__.py` (export `current_identity`), `agent_sdk/routes/a2a.py`, `agent_sdk/routes/ag_ui.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/agent/runner.py` (post-resume rebind in `run_task_worker.wait_resume`), `docs/` page that documents tool/adapter APIs, `harness/skills/add-tool/SKILL.md` and `harness/skills/add-source/SKILL.md` + their `template/.claude/skills/` mirrors (one short usage note each, only if they list request-scoped helpers), new `tests/test_gh185_current_identity.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/credentials/forwarding.py` (the binding pattern to copy), `agent_sdk/auth/identity.py`, `agent_sdk/auth/middleware.py`, `agent_sdk/agent/runner.py`, `agent_sdk/agent/loop.py`
  - Severity: medium
  - Root cause: `require_identity` resolves the caller's `Identity` at the route, but nothing carries it into the worker, the loop or an MCP `tools/call`, so tools and SourceAdapters cannot attribute usage, scope data per user, or audit who triggered a paid call.
  - Ruling: Checkable reference: https://github.com/wailuen/a2a-sdk/issues/185#issuecomment-6217407102
  - AC: `agent_sdk.auth.current_identity() -> Identity | None` is public, read-only, and returns the frozen `Identity` only (no tokens, raw headers or credentials).
  - AC: Bound before the worker task is created on A2A `message:send` and `message:stream` (the worker snapshots the context), so a tool and a SourceAdapter inside the run see the caller.
  - AC: A2A interrupt resume and `tasks/resubscribe` bind the resuming caller (the RT-005 resume path that today skips `forwarding.bind`).
  - AC: AG-UI `/ag-ui/run` binds before the run task starts.
  - AC: MCP `tools/call` on POST /mcp and on legacy /mcp/messages binds around dispatch and unbinds in `finally`.
  - AC: Returns None outside a request (boot, scheduler, plain unit test).
  - AC: Isolation test: two concurrent requests from different identities each see only their own identity in their tool, on A2A, AG-UI and MCP; after the request ends the value does not leak into the next request on the same worker.
  - AC: No identity value is logged by the new code (SI-2).
  - AC: CHANGELOG `[Unreleased]` Added entry with the ruling URL; docs show a 3-line usage example inside a tool.
  - GH: https://github.com/wailuen/a2a-sdk/issues/185
  - SI: SI-5  # Todo touches auth (new agent_sdk/auth/context.py) and every transport route (a2a.py, ag_ui.py, mcp.py) but has no SI: field. The bind must happen only after Depends(require_identity) has resolved, using that resolved Identity. Never bind from an ASGI middleware or route prologue that runs before auth, and never on unauthenticated paths (/.well-known/, /health). Add a test that an unauthenticated or rejected request never leaves a bound identity behind.
  - SI: SI-2  # The AC covers 'no identity value is logged by the new code'. Extend it: no Identity field (subject, user, label) may appear in exception text, error envelopes or the ContextVar's repr on any of the 5 bind sites. current_identity() must return the frozen Identity object itself (agent_sdk/auth/identity.py:13), not a copy that carries extra request fields. The docs usage example must not show logging the identity.

---
Archived 2026-10-17 by hand after the wave (archive step left it in active/). Released as v0.16.0.
