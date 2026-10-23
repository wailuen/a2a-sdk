# w059 — Group G2 deferred findings (medium/low)

- **Wave:** w059
- **Scope:** unit:G2
- **Date:** 2026-10-22
- **Status:** Non-blocking — these did not block w059's archive. Address opportunistically or fold into a future wave.

Findings accumulated across every redteam round, deduped by file + description. Where several rounds reported the same defect, one entry is kept and the combined fix notes are merged. All entries are SDK candidates.

## Medium

### D-01 — ag_ui.py: route-made RUN_ERROR suppresses disconnect-cancel
- **File:** agent_sdk/routes/ag_ui.py (`_cancel_if_unfinished` ~689; RUN_ERROR sites ~679, ~831/832, ~837/838)
- **Issue:** `_cancel_if_unfinished` treats `mapper.terminal_sent` as "run is over". Route-synthesised RUN_ERRORs (`_emit` serialization fallback "invalid agent response", catch-all "internal error" when `mapper.map()` raises, "stream ended unexpectedly" on StreamTerminated/None) also set it while the worker is still running. Client sees a terminal frame, stream closes, worker is never cancelled and keeps calling model/tools — the GH-217 cost leak. Task may later reach COMPLETED after the client was told it failed.
- **Fix:** Track worker-origin terminal separately (e.g. `mapper.worker_terminal = True` only when DoneEvent/InterruptEvent is mapped), or decide from the record (not in TERMINAL_STATES and not parked on an interrupt). Alternatively call `cancel_task_record` directly on each route-level RUN_ERROR path after `_start_worker`. Test: domain translate()/ContentModel raises mid-run → RUN_ERROR sent, `worker.done()`, state == canceled.
- **Codify:** "Terminal frame sent to the client" and "run reached a terminal state" are different facts; a transport-made error frame is not proof the worker stopped.

### D-02 — ag_ui.py: resume-branch ownership for disconnect-cancel (conflicting findings — needs ruling)
- **File:** agent_sdk/routes/ag_ui.py (fresh-run `owned.append` ~799; resume branch ~736-761)
- **Issue A (earlier round):** A resumed run never registers in `owned`, so a disconnect during a resumed run does not cancel it — same cost leak; CHANGELOG claims cancel with no resume exception.
- **Issue B (later round, after `owned.append(record)` added at ~761):** `store.find_interrupt` matches A2A-created tasks and honors the admin api_key cross-identity override (tasks/memory.py:185, 213). An AG-UI resume disconnect can therefore CANCEL an A2A `message:stream` task (otherwise resubscribable) or another identity's task. Violates the SI-5 note: the disconnect path may cancel only the record its own run created under the request identity.
- **Fix:** Cancel on disconnect only for records that started on AG-UI and are owned by the exact request identity, never through the admin override (e.g. tag `record.origin == 'ag_ui'` in the fresh-run branch and check origin + owner before appending in the resume branch). Or limit `owned` to fresh runs and document that resumed runs survive disconnect. Tests: (a) A2A-created interrupt resumed over AG-UI then disconnected → not canceled; (b) admin-key resume of another identity's interrupt then disconnect → not canceled; (c) AG-UI-origin resume with blocking model then disconnect → CANCELED (if that option chosen).
- **Codify:** A disconnect-triggered cancel must cover every branch that drives a worker, but may tear down only records its own request created under the caller's own identity.

### D-03 — ag_ui.py: teardown hooks not exception-safe (slot leak)
- **File:** agent_sdk/routes/ag_ui.py (`_finish` ~685-698; `stream()` finally ~849-851)
- **Issue:** `_cancel_if_unfinished()` then `await slot.release()` with no guard. If `cancel_task_record` raises (custom TaskStore publish/close_streams/persist, `_task_wire` on a bad record), the exception replaces the unwinding CancelledError, skips slot release (in `_finish` entirely; in `stream()` the BackgroundTask never runs), leaving only the `_prune_a2a_streams` backstop — LRN-193 slot-leak pattern. `owned.pop()` runs first, so a partial failure is never retried.
- **Fix:** `try: _cancel_if_unfinished() except Exception as exc: logger.warning('ag-ui disconnect cancel failed error_type=%s', type(exc).__name__) finally: await slot.release()` in both places. Never log str(exc) (SI-2). Test: store whose `publish` raises on cancel → slot released after disconnect.
- **Codify:** Teardown hooks inside a generator `finally` or response BackgroundTask must swallow and log (type only) store-teardown exceptions.

### D-04 — runner.py: "invalid agent response" coded `validation`
- **File:** agent_sdk/agent/runner.py (deferred `_fail(..., category="validation")` ~1127; `run_task_worker` catch-all ~1555)
- **Issue:** Agent-output failures (ValueError/ValidationError from build_artifact or translators, A2A -32006) get `RUN_ERROR.code = "validation"`. docs/protocols.md reserves `validation` for client-input faults. ag_ui.py `_emit` fallback (~679) gives the same message `internal`, so one failure has two codes. Clients will blame their own input.
- **Fix:** Map both sites to `ErrorCategory.INTERNAL` (per GH-220 AC "serialization, internal → internal"), or document a distinct meaning. Test that translate() ValueError gives `RUN_ERROR.code == 'internal'` at both runner and deferred sites.
- **Codify:** An error-category code describes who is at fault; agent-output validation failure is `internal`.

### D-05 — Docs: GH-217 disconnect-cancel and G2 wire changes undocumented
- **Files:** docs/protocols.md (AG-UI section); DESIGN.md §5.3 (~336-343)
- **Issue:** No mention anywhere that a fresh /ag-ui/run whose stream ends before RUN_FINISHED/RUN_ERROR is cancelled. Unrecorded asymmetries: interrupt-parked runs not cancelled, resumed-run behaviour, A2A `message:stream` disconnect leaves task running (resubscribe). DESIGN.md §5.3 also lacks the RUN_ERROR `code` vocabulary and that RUN_FINISHED always carries `outcome: {type: "success"}`. Spec-version ≥ 2.4 heartbeat-delayed cancel (see D-10) also undocumented.
- **Fix:** Add the disconnect-cancel paragraph to both docs, plus code vocabulary and always-present outcome to DESIGN.md §5.3.
- **Codify:** A wire behaviour change on a protocol route updates DESIGN.md's protocol section as well as docs/protocols.md.

### D-06 — events.py: dead public field `ToolResultEvent.code`
- **File:** agent_sdk/agent/events.py (~86)
- **Issue:** New public field, advertised in CHANGELOG as a 0.18.0 addition, outside GH-220 ACs (which only ask for `DoneEvent.code`). No producer sets it (loop.py 1468/1486/1517/1844/1864; runner.py 909/1148), no consumer reads it. Always None.
- **Fix:** Remove it and its CHANGELOG mention, or populate from `AgentError.category.value` at every `ToolResultEvent(ok=False)` site, consume it (e.g. TOOL_CALL_RESULT error code), and test.
- **Codify:** A new public event field needs at least one writer and one reader in the same change.

### D-07 — `cancel_task_record` not registered as a component
- **Files:** agent_sdk/routes/a2a.py (~1104); workspace/components/README.md
- **Issue:** New shared cross-route teardown helper (tasks/cancel + AG-UI disconnect) is not in the registry. C-018/C-019 still name `tasks_cancel` as the call site and count "five call sites, two modules" — now stale. AG-UI disconnect is a new out-of-loop writer of `record.messages`. Lives in a route module, so ag_ui.py imports teardown from another route.
- **Fix:** Add a C-NNN entry (takes an identity-scoped non-terminal record, never an id — SI-5; sole cancel teardown; callers tasks/cancel + AG-UI disconnect). Update C-018/C-019 call-site text. Consider moving it to agent_sdk/agent/runner.py beside `set_task_status`, re-exporting from routes/a2a.py.
- **Codify:** When a refactor pulls a registered component's call site into a new shared helper, register the helper and update the owner's call-site list in the same change.

## Low

### D-08 — a2a.py: dead `body = _task_wire(record)` in `cancel_task_record`; `store: Any`
- **File:** agent_sdk/routes/a2a.py (~1162; tasks_cancel recomputes ~1212)
- **Issue:** Unused full Task serialization on every cancel and every AG-UI disconnect. Runs before the try/finally guaranteeing `store.close_streams`, so a raise skips publish/close for subscribers and feeds D-03. `store` typed `Any`.
- **Fix:** Delete line ~1162. Type `store` as the TaskStore protocol/base class.

### D-09 — a2a.py: cancellation DoneEvent carries no code
- **File:** agent_sdk/routes/a2a.py (~1174)
- **Issue:** `DoneEvent(ok=False, error=_CANCELLED_RUN_ERROR_TEXT)` has no code, so an AG-UI subscriber of a user-requested tasks/cancel gets `RUN_ERROR {message:'task canceled', code:'internal'}` — looks like a server fault.
- **Fix:** Pick an explicit code (e.g. new `ErrorCategory.CANCELLED`, or a documented existing value) and document it in docs/protocols.md. Test an AG-UI subscriber seeing a tasks/cancel.

### D-10 — runner.py: deferred AgentError category dropped
- **File:** agent_sdk/agent/runner.py (`_run_deferred_background` ~969)
- **Issue:** AgentError from a long_running tool's deferred handle (RATE_LIMITED, UPSTREAM, auth) hits generic `except Exception` → `_fail('deferred job failed')` with `internal`, against the GH-220 AC that runner codes come from `AgentError.category`.
- **Fix:** Add `except AgentError as err: _fail('deferred job failed', category=err.category.value)` before the generic branch (fixed message, SI-2). Test deferred AgentError(RATE_LIMITED) → `RUN_ERROR.code == 'rate_limited'`.

### D-11 — loop.py / runner.py / ag_ui.py: `DoneEvent.code` is an untyped string
- **File:** agent_sdk/agent/loop.py (plus ~12 sites in runner.py, ag_ui.py)
- **Issue:** `DoneEvent.code: str | None` filled with raw literals ('internal', 'timeout', 'budget', 'validation'); mypy cannot catch misspelt or off-vocabulary codes reaching the wire.
- **Fix:** Type `DoneEvent.code`, `_RunMapper.run_error`'s code and `runner._fail`'s category as `ErrorCategory | None`; pass enum members; serialize with `.value`.

### D-12 — Tests: disconnect lifecycle and GH-220 code coverage gaps
- **Files:** tests/test_gh217_agui_disconnect_cancel.py; tests/test_gh220_agui_run_error_code.py
- **Issue:** Raw-ASGI driver uses `asgi={'version':'3.0'}` with no spec_version and disconnects only while awaiting `sub.get()`, so only the `listen_for_disconnect` path and the generator `finally` are exercised; removing `_cancel_if_unfinished()` from `_finish` would fail no test (AC requires lifecycle hook, LRN-193). Starlette 1.3.1 spec_version ≥ 2.4 raises ClientDisconnect, skips `background`, and cancel then waits for the next heartbeat failure (up to STREAM_HEARTBEAT_SECONDS=15s) plus generator finalization — untested and undocumented. No resume-disconnect case, no disconnect-after-route-RUN_ERROR case. GH-220 tests pin only rate_limited/success/validation/not_found: missing deadline→`timeout`, token budget / max-turns→`budget`, sealed→`internal`, deferred timeout→`timeout`, non-text part→`validation`, "interrupt is no longer resumable"→`not_found`, worker AgentError/Exception paths (runner ~1514/~1555), and tasks/cancel code seen by an AG-UI subscriber.
- **Fix:** Parametrize `_drive` over spec_version '2.3' and '2.4' (2.4: `send` raises OSError after disconnect; assert still cancelled, else aclose the body iterator or hook elsewhere). Add a test disconnecting while paused at a `yield` with `send()` blocked, asserting CANCELED (proves `_finish`). Add parametrised GH-220 tests per DoneEvent code site and the cases above.
