# w034 — GitHub issues 119–121

Sourced from Leg 3 (/agent-stack-check static conformance) findings surfaced
while gating /sdk-release 0.5.41. All items are independent. Run in parallel
(group:G).
Target: 0.5.42 (or same 0.5.41 if release hasn't tagged yet).

Group G redteam ran to round 5 / budget-exhausted with 2 remaining findings
(RT-001 medium, RT-002 low) — deferred to
`workspace/todos/deferred/w034-group-G-budget-exhausted.md`. Both fixed
2026-07-14: RT-001 in `agent_sdk/agent/loop.py` (generator-branch
DeferredResult handoff, mirrors the coroutine branch), RT-002 in
`agent_sdk/agent/runner.py` (serialize the artifact wire frame before
mutating `task.artifacts`, both call sites). Regression tests:
`tests/test_rt001_gen_tool_terminal_deferred_result.py`,
`tests/test_rt002_failed_task_no_stranded_artifact.py`. Full suite (1093
tests) + mypy clean after the fix. Codified as LRN-122/LRN-123.

RT-002's fix round in `agent_sdk/agent/runner.py` landed a wider
control-flow refactor than the "serialize before mutating `task.artifacts`"
headline above: (1) a new `_fail()` helper (`runner.py:244`) consolidating
every pre-delivery FAILED exit of `_run_deferred_background` — timeout,
cancellation, generic tool failure, and artifact-build/serialize failure —
into one terminal path; (2) `_fail()` now publishes a synthetic
`ToolResultEvent(ok=False, ...)` on ALL of those deferred FAILURE branches
(`runner.py:274-282`), where the prior code published none, so the AG-UI
`TOOL_CALL_START` opened before the `DeferredEvent` always gets a matching
`TOOL_CALL_RESULT` even on failure, symmetric with the existing success-path
synthetic `ToolResultEvent(ok=True)`; (3) `run_task_worker`'s terminal
`DoneEvent` publish moved outside the surrounding `try` into the `else:`
clause (`runner.py:567-569`), and `_run_deferred_background`'s success-path
`try` narrowed to cover only `build_artifact()`/`.wire()`/the artifacts
append (`runner.py:336-368`) — so a publish/close-streams failure AFTER the
real terminal frame already reached subscribers cannot re-enter the FAILED
path and emit a duplicate terminal frame. These three changes were
regression-tested (`tests/test_rt002_deferred_failed_tool_result.py`,
`tests/test_rt002b_deferred_terminal_frame_no_duplicate.py`,
`tests/test_rt002c_sync_worker_terminal_frame_no_flip.py`) but were absent
from this note until RT-003 (2026-07-14) flagged the gap; codified as
LRN-124.

Also regression-tested under the same RT-001/RT-002 fix but omitted from
both paragraphs above until RT-002 (2026-07-15) flagged the gap:
`tests/test_rt001_deferred_artifact_build_failure.py` (RT-001's deferred
SUCCESS path — a raise inside `build_artifact`/`.wire()` on the background
awaiter must FAIL the task, not strand it in WORKING, and must still close
subscriber streams), `tests/test_rt001_deferred_task_handle_cancel.py`
(RT-001's max-depth nested-`DeferredResult` cleanup must `.cancel()` an
abandoned `asyncio.Future`/`Task`-backed handle, not just `.close()` a
coroutine one — a Task-backed handle has no `.close()`), and
`tests/test_rt002_close_streams_finally_on_publish_failure.py` (RT-002's
`store.close_streams()` must run even when an *earlier* step in the
terminal sequence — the artifact-frame `publish()` on the deferred path, or
the terminal `DoneEvent` `publish()` on the synchronous path — raises, not
only when `close_streams()` itself is the failing call as in
`test_rt002b_deferred_terminal_frame_no_duplicate.py`).

---

- [x] `RT-002` RT-cleanup: `InterruptEvent.expires_at` -> `expires_in` field rename ‖ group:G
  - Creates: (already landed — `agent_sdk/agent/events.py:107`, `agent_sdk/agent/runner.py:418`, `agent_sdk/routes/ag_ui.py`)
  - Severity: low
  - Root cause: this rename rode along in this wave without being named in any GH-119/120/121 AC (LRN-119-class untracked scope creep on an internal loop-event surface field). Codified here for archive traceability, not because the change itself was wrong — `expires_in` correctly names a relative seconds-remaining duration (see `TaskStore.interrupt_ttl_remaining`), distinct from the wall-clock `expiresAt` wire field ag_ui.py computes from it.
  - AC:
    - Confirmed no code outside this wave references `InterruptEvent.expires_at` (grep across `agent_sdk/`, `tests/`, `examples/`, `harness/`, `template/`): the only remaining `.expires_at` hits are unrelated domains (`oauth_tokens.py`, `api_keys.py`, `azure_table.py` token/cache expiry) or comments citing the *upstream* ag-ui-protocol wire field name, which is untouched.
    - `events.py`, `runner.py`, `routes/ag_ui.py` are internally consistent on `expires_in` (verified — no residual reads/writes of the old name).
  - SI: none (internal dataclass field, not a public export or wire field)

- [x] `GH-119` Origin allow-list default excludes the deployment's own origin ‖ group:G
  - Creates: (modifies `agent_sdk/app.py`)
  - Reads: `agent_sdk/config.py`, `agent_sdk/app.py`, `tests/test_gh110_origin_allowlist.py`
  - Severity: high
  - Root cause: `agent_sdk/app.py:612` builds `_cors_origins` as `{o.rstrip("/") for o in settings.cors_origins} | {"https://claude.ai"}` — never unions in `settings.resolved_base_url` (defined `config.py:202`, unused here). Now that `guard_origin()` (GH-110/w033) is applied uniformly across MCP/AG-UI/A2A, this default gap blocks the bundled console's own same-origin requests on any non-`claude.ai` deployment.
  - AC:
    - `app.py:612`'s `_cors_origins` set includes `settings.resolved_base_url` (normalized, trailing slash stripped) in addition to the configured `cors_origins` and `https://claude.ai`.
    - New test in `tests/test_gh110_origin_allowlist.py` (or a new file) covering: `Origin` header equal to the deployment's own resolved base URL, with `CORS_ORIGINS` unset, is allowed (not 403) on MCP, AG-UI, and A2A surfaces.
    - Existing `test_gh110_origin_allowlist.py` cases (allowed / evil origin) still pass.
  - GH: https://github.com/wailuen/a2a-sdk/issues/119
  - SI: SI-5  # Modifies _cors_origins / app.state.cors_origins (app.py:612) — the transport-security Origin allow-list that C-009 guard_origin enforces across MCP/AG-UI/A2A — yet carries NO SI: field (GH-120/GH-121 both state 'SI: none'; GH-119 omits it, the one todo that actually widens a security allow-list). Add an SI analysis to the AC: (1) never widen to '*'; (2) union resolved_base_url in the SAME normalized, trailing-slash-stripped form as the existing set-comprehension so guard_origin's exact-match compare still holds; (3) confirm resolved_base_url stays operator-config-sourced (config.py:202 = PUBLIC_URL/localhost fallback, NOT Host/X-Forwarded-Host derived) so no request-controlled origin can be reflected into the allow-list.

- [x] `GH-120` registry.py invoke_any() leaks nested DeferredResult repr onto MCP wire ‖ group:G
  - Creates: (modifies `agent_sdk/agent/registry.py`; new test file)
  - Reads: `agent_sdk/agent/registry.py`, `agent_sdk/routes/mcp.py`, `tests/test_rt002_invoke_any_deferred_result.py`, `tests/test_admin_try_tool_deferred_result.py`
  - Severity: high
  - Root cause: `agent_sdk/agent/registry.py:432-441` (`invoke_any`) awaits `result.handle` exactly once when `result` is a `DeferredResult`, never rechecking whether the awaited value is itself another `DeferredResult`. `mcp.py`'s `_tool_text()` has no branch for this and falls through to `str(artifact)`, baking the dataclass repr (incl. an unawaited inner coroutine's memory address) into `content[0].text` under a false `isError: false`.
  - AC:
    - `invoke_any()` re-checks `isinstance(result, DeferredResult)` after each await (bounded depth, e.g. max 1 extra resolution or raise on further nesting) — a nested `DeferredResult` is either resolved or raises a clean internal error that maps to the existing generic-exception → `isError: true` path.
    - No code path can produce `content[].text` containing `"DeferredResult("` or `"coroutine object"`.
    - New regression test: a `long_running=True` tool whose `handle` resolves to another `DeferredResult` — asserts the MCP `tools/call` response is a clean `isError: true` (or fully resolved value), never a raw repr.
  - SI: none (no HTTP/credential/path-param surface touched)
  - GH: https://github.com/wailuen/a2a-sdk/issues/120
  - Reuses: C-010  # invoke_any (registry.py:432-441) IS C-010, the single tool-dispatch/DeferredResult-resolution point. Land the nested-DeferredResult re-check INSIDE invoke_any (C-010) per the AC — do NOT add a parallel str()-guard branch in mcp.py's _tool_text. Any depth-bound/rejection logic belongs in C-010, not a second copy on the MCP route.

- [x] `GH-121` runner.py _run_deferred_background leaks nested DeferredResult into persisted A2A Task artifact ‖ group:G
  - Creates: (modifies `agent_sdk/agent/runner.py`; new test file `tests/test_gh121_nested_deferred.py`; new cross-surface parity test `tests/test_rt001_deferred_nesting_parity.py` — RT-001's guard that `invoke_any` (GH-120) and `_run_deferred_background` (GH-121) stay outcome-identical, owned by this todo since it is the surface this wave's RT-001 unification lands on)
  - Reads: `agent_sdk/agent/runner.py`, `agent_sdk/agent/deferred.py`, `agent_sdk/common/sse.py`, `tests/test_gh87_deferred_task.py`
  - Severity: high
  - Root cause: `agent_sdk/agent/runner.py:232-235` (`_run_deferred_background`) awaits `event.deferred.handle` once into `raw_result`, never rechecking for a nested `DeferredResult`. The nested value flows into `ArtifactEvent(model=raw_result)` → `build_artifact()`'s plain-scalar fallback, baking `str(raw_result)` (raw repr) into a `TextPart` and an unserializable object into a `DataPart`. Task transitions to COMPLETED (false success); the actual crash only surfaces later at `sse.py`'s unguarded `json.dumps`, which can kill the SSE stream before `final: true` is ever emitted while the store already believes the task is done — persisted artifact corruption, not just a single-response failure.
  - AC:
    - `_run_deferred_background` re-checks `isinstance(raw_result, DeferredResult)` after the await (mirror the guard added for GH-120) instead of falling through to `build_artifact()` unchecked.
    - RT-001 unification (reconciled during this wave): the bounded-depth contract must match `invoke_any`/GH-120 exactly, not diverge by surface. A single level of nesting (handle resolves to one more `DeferredResult`, whose own handle resolves to a plain value) fully resolves -> task transitions to COMPLETED, matching `invoke_any`'s `isError:false`. A second level of nesting (double-nested) raises internally and routes through the existing FAILED-transition path (same shape as the `except Exception` branch) -> task transitions to FAILED, matching `invoke_any`'s `isError:true`.
    - No path can append an artifact containing a raw `DeferredResult` repr or an unserializable `DataPart` to `record.task.artifacts`, at any nesting depth.
    - New regression test mirroring `test_gh87_deferred_task.py`'s existing cases but with nested-`DeferredResult`-returning tools: asserts single-level nesting transitions to COMPLETED and double-level nesting transitions to FAILED, with no raw object ever reaching `build_artifact()`/`sse_data()`. See `tests/test_gh121_nested_deferred.py` for the surface-local cases and `tests/test_rt001_deferred_nesting_parity.py` as the cross-surface (MCP `invoke_any` vs. A2A/AG-UI runner) parity guard enforcing this contract stays identical on both surfaces.
  - SI: none
  - GH: https://github.com/wailuen/a2a-sdk/issues/121
