# w029 — GitHub issues GH-95–GH-101

Sourced from open issues on wailuen/a2a-sdk. All items are independent.
Run in parallel (group:G).
Target: 0.5.37.

Reconciled: All 7 items landed and verified against code (0.5.37). Deferred
findings RT-001..RT-004 (group G, budget-exhausted round 5) all confirmed
fixed in landed code — see resolution note in
`workspace/todos/deferred/w029-group-G-budget-exhausted.md` history / this
commit. Full suite green: 949 passed.

Note: GH-96 and GH-97 both edit `agent_sdk/routes/ag_ui.py`'s `stream()`/`ag_ui_run()`
region (GH-96 touches the try/except/finally at ~391-446; GH-97 touches the
`_validate()` call site at ~382 and `_validate()` itself at ~98-111). Land these two
sequentially within the group, or diff-review together, to avoid a merge collision —
their edited line ranges don't directly overlap but sit in the same function.

---

- [x] `GH-95` models/content_types: MarketBriefing family has no finite-float guard, breaking the dual-part artifact contract ‖ group:G
  - Creates: (modifies `agent_sdk/models/content_types.py`, creates/modifies test file for finite-float validation)
  - Reads: `agent_sdk/models/content_types.py`
  - Severity: high
  - Root cause: No `isfinite`/`isnan` guard exists anywhere in `content_types.py` (confirmed by grep — zero hits). `BriefingKpiItem.value`/`.delta` (float|int|str, line ~323) and `ChartSection.data`/`TableSection.data` (free-form `dict[str, Any]`, lines ~336/~342) accept `inf`/`nan` with zero validation, at any nesting depth for the dict fields. `model_dump_json()` serializes non-finite floats as JSON `null` while `to_markdown()`/`to_plain_text()` render `"inf"`/`"nan"` literally, so the two halves of the dual-part artifact diverge. `content_type_for('market_briefing')` resolves directly to this unguarded class via the plain `_REGISTRY` dict, so every agent importing `MarketBriefing` inherits the gap.
  - AC: `BriefingKpiItem(value=float('inf'))` and `BriefingKpiItem(delta=float('nan'))` raise `ValidationError`; `ChartSection(data={'nested': {'deep': [float('nan')]}})` and `TableSection(data=...)` with a nested non-finite float raise `ValidationError`; a shared finite-float helper is used by both field validators (may extend the existing `MetricItem._reject_non_scalar` pattern at line ~110); valid finite payloads still construct and round-trip `model_dump_json()`/`to_plain_text()` consistently; do NOT touch `EntityList.to_plain_text()` (lines ~311-320) — unrelated pre-existing uncommitted local change, out of scope for this fix
  - GH: https://github.com/wailuen/a2a-sdk/issues/95

- [x] `GH-96` sdk/ag-ui-route: stream() skips RUN_ERROR fallback on non-StreamTerminated exceptions ‖ group:G
  - Creates: (modifies `agent_sdk/routes/ag_ui.py`, creates/modifies regression test for terminal-event coverage)
  - Reads: `agent_sdk/routes/ag_ui.py`
  - Severity: high
  - Root cause: `stream()` (lines 391-446) wraps its body in `try / except StreamTerminated: pass / finally` (unsubscribe), then the fallback `if not mapper.terminal_sent: yield mapper.run_error(...)` sits at lines 444-446, OUTSIDE the try block. Any exception other than `StreamTerminated` raised inside the try (e.g. from `mapper.map()` translating an `ArtifactEvent`/`ToolResultEvent`, or from store/subscribe calls) propagates past the fallback with no terminal frame ever yielded — the SSE connection dies with no `RUN_FINISHED`/`RUN_ERROR`, violating the AG-UI "exactly one terminal event" rule.
  - AC: a catch-all exception handler (alongside or replacing `except StreamTerminated: pass`) yields `mapper.run_error(...)` for any non-`StreamTerminated` exception before the `finally` unsubscribe runs; the existing `if not mapper.terminal_sent: yield mapper.run_error(...)` safety-net after the try/except still executes as a final guarantee; a regression test forces `mapper.map()` (or another in-try call) to raise a non-`StreamTerminated` exception and asserts the SSE stream ends with exactly one `RUN_ERROR` frame
  - GH: https://github.com/wailuen/a2a-sdk/issues/96
  - SI: SI-2  # The new catch-all exception handler yields mapper.run_error(...), and run_error() writes its message argument verbatim into the RUN_ERROR wire frame (ag_ui.py:166). The AC does not constrain that message to a static string. Passing str(exc)/f"...{exc}" would leak exception detail from mapper.map() (translating Artifact/ToolResult events carrying tool or user payload) to the SSE wire — SI-2 violation, same class as LRN-044. Require the catch-all to emit a fixed message (e.g. "internal error"), matching the existing static "run failed" fallback at ag_ui.py:314; never interpolate the exception.

- [x] `GH-99` sdk/loop + sdk/ag_ui: load_skill unknown-name error echoes caller-supplied input on both A2A and AG-UI transports (SI-2) ‖ group:G
  - Creates: (modifies `agent_sdk/agent/loop.py`, optionally modifies `agent_sdk/routes/ag_ui.py`, creates `tests/test_agent_skills.py`)
  - Reads: `agent_sdk/agent/loop.py`, `agent_sdk/routes/ag_ui.py`
  - Severity: high
  - Root cause: `loop.py:372` builds `f"unknown skill {tc.arguments.get('name')!r}"`, embedding the raw caller-supplied skill name verbatim into `ToolResultEvent.error`. The adjacent unknown-tool branch (`loop.py:392-393`) already sanitizes via truncate + control-char strip before use — the load_skill branch never adopted the same pattern. `ag_ui.py:222` maps `str(event.error)` straight into the `TOOL_CALL_RESULT` SSE frame with no sanitization at that layer either, so the leak reaches the wire on both A2A and AG-UI transports. Note: the regression test named in the issue (`tests/test_agent_skills.py::TestUnknownSkillSI2SurfaceCoverage::test_agui_stream_leaks_unknown_skill_name_sdk_candidate`) does not exist anywhere in the repo or git history — author it fresh, this is not an xfail flip.
  - AC: `loop.py:372`'s load_skill error message applies the same truncate+control-char-strip sanitization as `loop.py:392-393` (or is replaced with a fully static "unknown skill" message with zero caller-supplied data); `ToolResultEvent.error` for the load_skill branch never contains unsanitized `tc.arguments` content; `tests/test_agent_skills.py` with class `TestUnknownSkillSI2SurfaceCoverage` and test `test_agui_stream_leaks_unknown_skill_name_sdk_candidate` asserts a crafted caller-supplied skill name (control chars / long payload) never appears verbatim in the AG-UI `TOOL_CALL_RESULT` content; a matching A2A-transport test covers `loop.py`'s `ToolResultEvent.error` directly; existing unknown-tool sanitization tests still pass
  - GH: https://github.com/wailuen/a2a-sdk/issues/99

- [x] `GH-97` sdk/ag-ui-route: _validate() rejects synthesized threadId/runId it was supposed to tolerate ‖ group:G
  - Creates: (modifies `agent_sdk/routes/ag_ui.py`, creates/modifies regression test for threadId/runId synthesis)
  - Reads: `agent_sdk/routes/ag_ui.py`
  - Severity: medium
  - Root cause: `thread_id`/`run_id` are synthesized into local variables at lines 371-372 ("so we never emit empty correlation ids") and used for `RUN_STARTED` at line 379, but `body` itself is never mutated with the synthesized values. `_validate(body)` is called at line 382 — after `RUN_STARTED` — and re-checks the original raw `body` dict (lines 100-103), which is still missing threadId/runId, so it unconditionally returns "threadId is required" immediately after a valid `RUN_STARTED`. Per the documented invariant that `RUN_STARTED` is always emitted first and every failure after it must be `RUN_ERROR` (§5.3), the fix is to make `_validate` tolerate the already-synthesized IDs (drop the presence checks, or validate a body updated with the synthesized values) rather than rejecting before `RUN_STARTED`.
  - AC: POST to the AG-UI run endpoint with a valid-JSON body omitting `threadId`/`runId` emits `RUN_STARTED` with a non-empty synthesized id and does NOT emit `RUN_ERROR: "threadId is required"`/`"runId is required"` immediately after; a regression test covers the omitted-field case and the empty-string/non-string-value case; the unrelated `_validate` checks (messages must be a list; control-character rejection in message content) remain unchanged and covered
  - GH: https://github.com/wailuen/a2a-sdk/issues/97

- [x] `GH-98` sdk/ag-ui-route: agent card doesn't advertise the 5 CUSTOM event names it emits ‖ group:G
  - Creates: (modifies `agent_sdk/routes/agent_card.py`, modifies `agent_sdk/console/static/chat.js`, modifies `tests/test_card_console.py`)
  - Reads: `agent_sdk/routes/agent_card.py`, `agent_sdk/routes/ag_ui.py`, `agent_sdk/console/static/chat.js`, `tests/test_card_console.py`
  - Severity: medium
  - Root cause: The earlier GH-5/w006 fix (card's `x-agui.customEvents` as objects with name+valueSchema) is real but only half-complete: `CUSTOM_EVENTS`/`_CUSTOM_EVENT_SCHEMAS` in `agent_card.py` (lines ~32-75) enumerate only 4 events (`AGENT_ARTIFACT`, `A2UI_UPDATE`, `AGENT_PROGRESS`, `AGENT_NOTE`). `TOOL_PROGRESS` was added later in w025 (GH-88) and is genuinely emitted at `ag_ui.py:256-261`, but the card constant/schema and the admin console's `handleCustom()` routing table (`chat.js` ~line 614-640) were never updated to match — the console's own reference implementation falls through to "unrecognized CUSTOM event: TOOL_PROGRESS". The existing test (`test_card_console.py`) only checks card-vs-console parity, not card-vs-actually-emitted parity, so both sides drifted together undetected.
  - AC: `TOOL_PROGRESS` is added to `CUSTOM_EVENTS` and `_CUSTOM_EVENT_SCHEMAS` in `agent_card.py` with a `valueSchema` matching the payload emitted at `ag_ui.py:258-261` (`{message: string, toolName: string}`); `chat.js`'s `handleCustom()` gets a `TOOL_PROGRESS` branch rendering that payload instead of falling into the unrecognized-event default; the `chat.js:8` frozen-payload-contracts header comment lists `TOOL_PROGRESS`; `test_card_console.py` is strengthened to derive the emitted-event-name set from `ag_ui.py`'s event types and assert it equals `CUSTOM_EVENTS` (not just card-vs-console), so this can't silently drift again
  - GH: https://github.com/wailuen/a2a-sdk/issues/98

- [x] `GH-100` sdk/build: skills catalog frozen into system_prompt before always-on skills are popped, leaving stale catalog entries ‖ group:G
  - Creates: (modifies `agent_sdk/app.py`, modifies `agent_sdk/agent/skills.py`, creates `tests/test_skills_catalog.py`)
  - Reads: `agent_sdk/app.py`, `agent_sdk/agent/skills.py`, `agent_sdk/agent/loop.py`, `DESIGN.md`
  - Severity: medium
  - Root cause: `always_on_skills` is not an actual `Agent` parameter (zero occurrences in the SDK) — the reporter's repro mutates `app.state.skills` post-`build_app()`, which is documented as frozen (`app.py:642`). That said, the underlying technical gap is real: `build_app()` folds `skills.catalog_text()` into `system_prompt` at lines 513-516 and there is no path to re-derive it from a later-mutated `app.state.skills`, so any post-boot removal leaves a stale, unusable catalog entry. The sanctioned fix is additive (Option A from the issue): add `exclude_from_catalog` support so a skill's content can be inlined via `persona`/`artifacts_dir` while being omitted from the advertised catalog at construction time — not Option B (a post-build mutation hook), which would contradict the frozen-app.state design.
  - AC: `Agent.__init__` accepts `exclude_from_catalog: list[str] | None`, validated at boot (each name must correspond to a discoverable skill, else raise); `SkillsRegistry.catalog_text()` accepts an `exclude` param that omits matching entries; `build_app()` passes `exclude_from_catalog` through so excluded names never appear in the frozen `system_prompt`; `app.state.skills.load(<excluded name>)` still succeeds (skill remains directly invocable, just not advertised); regression test in `tests/test_skills_catalog.py` covers both the catalog-exclusion and the load-still-works behavior; `Agent.__init__` docstring and `DESIGN.md`'s skills section document `exclude_from_catalog` as the recommended pattern for always-on/guardrail skills; do not implement a `rebuild_skills_catalog()` post-build mutation hook
  - GH: https://github.com/wailuen/a2a-sdk/issues/100

- [x] `GH-101` sdk/registry: function names ending in _tool are registered verbatim with no warning, causing silent skill/persona mismatch ‖ group:G
  - Creates: (modifies `agent_sdk/agent/registry.py`, modifies `docs/tools.md`, creates test for the registration-time warning)
  - Reads: `agent_sdk/agent/registry.py`, `agent_sdk/agent/loop.py`, `docs/tools.md`
  - Severity: medium
  - Root cause: `ToolSet.tool()`'s decorator resolves `_tool_name = name or fn.__name__` (registry.py:109) with no signal when `fn.__name__` ends in `_tool` and no explicit `name=` override was supplied — the mismatch only surfaces later as an unknown-tool call at runtime (`loop.py:389-396`, which does log it, but only at call time, well after a skill/persona was authored against the wrong name). Fix is additive and non-breaking: log a `WARNING` at registration time.
  - AC: `agent_sdk/agent/registry.py` gains a `logging` import and logger; immediately after the tool-name resolution, a `WARNING` fires when `name` was not explicitly supplied and `fn.__name__` ends in `_tool`, naming the function, the resolved tool name, and the `name=` override as the fix — never raises, never renames; a unit test asserts (a) a tool fn named `foo_tool` with no `name=` triggers the warning via `caplog`, (b) the same fn with explicit `name="foo"` does not, (c) a tool fn named `foo` (no `_tool` suffix) does not; `docs/tools.md` gains a short "Common pitfalls" note near its existing `name=` override documentation (~line 32)
  - GH: https://github.com/wailuen/a2a-sdk/issues/101
