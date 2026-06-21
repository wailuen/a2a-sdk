# w025 — GitHub issues GH-87, GH-88, GH-89

Sourced from open issues on wailuen/a2a-sdk. GH-89 and GH-88 are independent
and run in parallel (group:G). GH-87 depends on GH-88 (interim-emit channel
must land first) and runs after group:G completes (group:H).
Target: 0.5.29.

---

- [x] `GH-89` harness/workflows/acceptance-api.js: require('crypto').randomUUID() crashes ‖ group:G
  - Creates: (modifies `harness/workflows/acceptance-api.js`, modifies `harness/skills/acceptance/SKILL.md`)
  - Reads: `harness/workflows/acceptance-api.js`, `harness/skills/acceptance/SKILL.md`
  - Severity: high
  - Root cause: The workflow sandbox has no CommonJS `require`, so `require('crypto').randomUUID()` at line 70 of `acceptance-api.js` throws `ReferenceError: require is not defined` for every scenario, making `/acceptance` completely non-functional. The fix derives the run-scoping nonce from a caller-provided `args.runId` minted at the Workflow invocation site in the skill (where `require` is available), then uses `(a.runId ? a.runId + '-' : '') + s.id` in the workflow script.
  - AC: `acceptance-api.js` line 70 uses `(a.runId ? a.runId + '-' : '') + s.id` (no `require('crypto')`); `SKILL.md` Workflow invocation passes `runId: require('crypto').randomUUID()`; no other `require(` calls remain in `harness/workflows/*.js`
  - GH: https://github.com/wailuen/a2a-sdk/issues/89

- [x] `GH-88` loop/tools: tools cannot emit progressive/interim artifacts during a long-running call ‖ group:G
  - Creates: (modifies `agent_sdk/agent/registry.py`, modifies `agent_sdk/agent/loop.py`, modifies `agent_sdk/agent/events.py`, modifies `agent_sdk/routes/ag_ui.py`, modifies `agent_sdk/routes/a2a.py`, creates `tests/test_gh88_tool_interim_emit.py`)
  - Reads: `agent_sdk/agent/registry.py`, `agent_sdk/agent/loop.py`, `agent_sdk/agent/events.py`, `agent_sdk/routes/ag_ui.py`, `agent_sdk/routes/a2a.py`
  - Severity: high
  - Root cause: `@tools.tool(emits=T)` only maps the tool's single return value to one `ArtifactEvent` (loop.py:464-471 via bare `asyncio.wait_for`). `ProgressEvent`/`NoteEvent` exist in `events.py:27-33` but are only reachable at the loop/worker layer. Fix: (1) add async-generator contract to `ToolDecl`/`ToolEntry.invoke` in `registry.py` (accept `AsyncGenerator` return type, add `is_generator: bool` flag); (2) replace bare `asyncio.wait_for(entry.invoke(...))` in `loop.py` with an async drain loop that re-yields interim `LoopEvent` items and captures the terminal result; (3) wire interim events to AG-UI (`STEP_STARTED`/`STEP_FINISHED`/`CUSTOM`) and A2A (`TaskStatusUpdateEvent{state:"working", final:false}`); (4) existing coroutine tools remain unchanged (backward-compatible).
  - AC: async-generator tool can `yield ProgressEvent(...)` during execution and `return` its terminal `ArtifactEvent`-typed result; loop forwards each yielded event downstream before the terminal artifact; A2A emits `TaskStatusUpdateEvent{state:"working",final:false}` per interim event; existing coroutine tools pass unchanged; unit tests cover both paths (generator and coroutine)
  - GH: https://github.com/wailuen/a2a-sdk/issues/88

- [x] `GH-87` loop/a2a: no first-class long-running/deferred-task delivery for tools wrapping minutes-long jobs ‖ group:H
  - Depends: GH-88
  - Creates: (modifies `agent_sdk/agent/registry.py`, modifies `agent_sdk/agent/loop.py`, modifies `agent_sdk/agent/runner.py`, modifies `agent_sdk/routes/a2a.py`, creates `agent_sdk/agent/deferred.py`, creates `tests/test_gh87_deferred_task.py`)
  - Reads: `agent_sdk/agent/loop.py`, `agent_sdk/agent/registry.py`, `agent_sdk/agent/runner.py`, `agent_sdk/routes/a2a.py`
  - Severity: high
  - Root cause: Hard tier timeouts (`TIER_TIMEOUTS = {1: 130.0, 2: 180.0}` at `loop.py:44`) have no per-tool override; `ToolInterrupt` (input-required) is the only task-pinning mechanism but is semantically coupled to user-input; returning a non-final result wrongly marks the task `completed`. Fix: (1) add `long_running: bool = False` and `tool_timeout_override: float | None = None` to `ToolDecl` and `@tool` decorator in `registry.py`; (2) extend `LoopPolicies` with per-tool timeout map; (3) introduce `DeferredResult` dataclass in new `agent_sdk/agent/deferred.py` that a tool returns to signal background-job registration (carries an awaitable handle + optional `estimated_seconds`); (4) add `DeferredEvent` to loop event stream — loop must NOT advance to `DoneEvent` when a deferred tool is in flight; (5) in `runner.py`, on `DeferredEvent` launch an asyncio.Task that awaits the job handle, keeps A2A record in WORKING state, emits `ProgressEvent`s via the GH-88 interim-emit channel; (6) on job resolution, publish terminal `ArtifactEvent` + `DoneEvent(ok=True)` → COMPLETED; on timeout → FAILED with `WireError`. This wave requires GH-88 interim-emit to already be merged.
  - AC: tool returning `DeferredResult(handle)` causes A2A task to stay WORKING (not COMPLETED); task transitions to COMPLETED with terminal artifact when handle resolves; exceeding timeout lands FAILED with clear error; `long_running=True` + `tool_timeout_override=N` accepted by `@tool` decorator; A2A conformance: no task reaches COMPLETED before its artifact is ready; tests cover resolve, timeout, and working-state paths
  - GH: https://github.com/wailuen/a2a-sdk/issues/87
