# w066 — phase redteam medium/low findings (deferred)

- Wave: w066
- Scope: phase
- Date: 2026-10-25

Non-blocking — these did not block w066's archive. Address opportunistically or fold into a future wave.

Findings were collected across every phase redteam round and deduped by file + description. Where two rounds reported the same defect, the entries are merged and both round IDs are listed. All are SDK candidates.

## Medium

### D-01 — acceptedOutputModes filtered after A2UI translation (-32005 on a satisfiable request)
- Round IDs: RT-001, RT-006
- File: `agent_sdk/agent/runner.py:419` — `def apply_output_modes(artifact: Artifact, modes: Sequence[str] | None) -> Artifact:`
- Problem: a client sends the A2UI header opt-in plus `acceptedOutputModes: ["application/json"]`. `_config_error` accepts it, tools run with side effects, build_artifact swaps the JSON DataPart for the A2UI DataPart, and apply_output_modes drops both, so the task FAILS with -32005 although an `application/json` payload was available. With `["text/plain","application/json"]` the structured data is silently lost (TextPart only). Reproduced over build_app() with demo_kpis. `test_modes_none_remain_and_text_not_accepted_is_32005` pins this outcome.
- Fix: fold accepted modes into the capability decision. In `routes/a2a.py` `_capabilities` (or `_start_worker`): `opted_in = header_opt_in and a2ui_enabled and (no acceptedOutputModes or any(media_type_match(m, {A2UI_MIME_TYPE}) for m in modes))`, so build_artifact emits the raw JSON DataPart (LRN-006). Have `_config_error` refuse an A2UI-only mode list when the request did not opt in, so -32005 comes before any tool runs. Keep the runtime -32005 only for a truly unsatisfiable part set. Add build_app() tests for header + `["application/json"]` (completed, DataPart) and header + `["text/plain","application/json"]`.
- Codify: output-mode negotiation must feed the producer's capability choice; filtering parts after an irreversible translation turns a satisfiable request into a failure.

### D-02 — resume ignores the new acceptedOutputModes
- Round IDs: RT-007 (round with RT-006..016)
- File: `agent_sdk/routes/a2a.py:550` — `record.accepted_output_modes = list(config.accepted_output_modes)`
- Problem: modes are stored only in `_create_task_record`. A taskId resume of an input-required/auth-required task passes `_config_error` but its `configuration.acceptedOutputModes` is never applied, so a resume asking for `["text/plain"]` still gets DataParts.
- Fix: on the resume branch of message_send and message_stream, set `record.accepted_output_modes` from the resume configuration when present. Add a route test that resumes with a different value.

### D-03 — A2UI gate parameters fail open (default True)
- Round IDs: RT-002 (medium), RT-010 (low)
- File: `agent_sdk/routes/a2a.py:430` — `message: Message, request: Request, *, a2ui_enabled: bool = True`
- Problem: `a2a._capabilities`, `a2a._config_error` (line 443) and `ag_ui._capabilities` (ag_ui.py:538) default `a2ui_enabled=True`, while `build_agent_card(a2ui_enabled=False)` defaults off. A call site that forgets the argument re-enables A2UI and accepts `application/a2ui+json` while the card says off — the exact GH-257 drift; contradicts C-006 fail-closed.
- Fix: make `a2ui_enabled` a required keyword-only argument with no default on all three (or default False). The two direct unit-test callers already pass it.
- Codify: a security or capability gate parameter must have no default or a fail-closed default.

### D-04 — "A2UI off" route tests cannot fail
- Round IDs: RT-003, RT-008
- File: `tests/test_gh257_single_a2ui_gate.py:160` — `async def test_ag_ui_off_drops_forwarded_caps(settings) -> None:`
- Problem: every off-case (`test_card_state_and_runtime_agree[False]`, `test_modes_with_a2ui_off` for `application/*` and `*/*`, `test_ag_ui_off_drops_forwarded_caps`) uses a tool returning a plain dict / non-ContentModel, so no A2UI DataPart or A2UI_UPDATE is possible whatever the gate does. A probe showed a no-emits tool returning KpiCard yields no artifact. Removing the gate from both `_capabilities` leaves the suite green; only the SimpleNamespace unit test covers it. `test_modes_with_a2ui_off` never asserts absence of an A2UI DataPart.
- Fix: build the emitting agent (make_agent / build_app() with an emitting tool), set `app.state.a2ui_enabled = False` after build_app, send header opt-in or `forwardedProps.a2uiClientCapabilities`, and assert no A2UI DataPart on `/v1/message:send` (header, and modes `application/*`, `*/*`) and no A2UI_UPDATE CUSTOM on `/ag-ui/run`.
- Codify: a negative-path gate test must use a fixture that would produce the gated output if the gate were removed.

### D-05 — Todo file declarations do not match the landed tree
- Round IDs: RT-009 (round with RT-006..016)
- File: `workspace/todos/active/w066-gh-issues.md:56`
- Problem: GH-257 lists `tests/test_gh249_a2ui_gating.py` under Creates, but that file is unchanged; tests went into undeclared `tests/test_gh257_single_a2ui_gate.py`. GH-260 lists `agent_sdk/routes/oauth.py`, which was not modified.
- Fix: change the GH-257 Creates list to `new tests/test_gh257_single_a2ui_gate.py` (drop test_gh249). Drop `agent_sdk/routes/oauth.py` from GH-260 or record why it was unchanged.

### D-06 — C-079 registry row does not name is_json_content_type
- Round IDs: RT-004
- File: `workspace/components/README.md:72` (C-079 row)
- Problem: GH-251's Reuses note requires adding `is_json_content_type` (common/body.py) and its three route callers to the C-079 note. The row never names it and still says the AG-UI 415 check "can reuse it". The helper is an unregistered reusable utility (Dimension 8).
- Fix: update the note: "is_json_content_type (agent_sdk/common/body.py; reuses normalize_media_type only, no wildcards) serves the request Content-Type check on /v1/message:send|stream, /ag-ui/run, POST /mcp and /mcp/messages (GH-251)". Remove "can reuse it".
- Codify: when a todo's Reuses note names a registry edit, the archive gate must grep the registry row for the new symbol, not just check that the row changed.

## Low

### D-07 — mcp.py keeps an `_is_json_content_type` wrapper
- Round IDs: RT-005, RT-016
- File: `agent_sdk/routes/mcp.py:477` — `def _is_json_content_type(request: Request) -> bool:`
- Problem: GH-251 said to delete it. It is kept as a same-named wrapper (Request vs str signature) holding the missing-header pass-through rule, while a2a.py and ag_ui.py inline `if ct and not is_json_content_type(ct)`. Two spellings of one rule; invites misuse.
- Fix: delete the wrapper; at mcp.py:1120 and :1525 inline `ct = request.headers.get("content-type", ""); if ct and not is_json_content_type(ct): ...`. Or move the missing-header rule into one shared body.py helper used by all three routes.

### D-08 — X-Agent-Credentials parsed twice
- Round IDs: RT-006 (low), RT-011
- File: `agent_sdk/credentials/forwarding.py:85` — `json.loads(decoded, object_pairs_hook=_no_duplicate_keys)`
- Problem: parsed once with loads_strict and again with plain json.loads plus a local duplicate-key hook (result discarded). This is the local re-check outside C-040 that GH-251 forbids; doubles parse cost; duplicate-key rejection exists on this surface only.
- Fix: add opt-in `reject_duplicate_keys: bool = False` to `agent_sdk/common/json_strict.py::loads_strict`, call `loads_strict(decoded, reject_duplicate_keys=True)` once, delete `_no_duplicate_keys`. Update the C-040 row.

### D-09 — `_check_structured` mislabels every exception as an unresolvable $ref
- Round IDs: RT-007 (low), RT-012
- File: `agent_sdk/testing/mcp.py:244` — `except Exception:`
- Problem: RecursionError, TypeError from a format checker, validator bugs or library changes are all reported as "outputSchema has an unresolvable $ref".
- Fix: catch only `referencing.exceptions.Unresolvable` and jsonschema's RefResolutionError / referencing-wrapped error (imported defensively) for the $ref message; map anything else to a separate fixed text such as "outputSchema could not be checked (<type>)", or let it propagate.

### D-10 — McpClient.initialize falls back silently on missing protocolVersion
- Round IDs: RT-013
- File: `agent_sdk/testing/mcp.py:120` — `if negotiated is None:`
- Problem: falls back to PROTOCOL_VERSION when the server omits `protocolVersion`, which MCP 2025-06-18 requires; the conformance client hides a non-conforming server even though GH-256 rejects empty/unsupported versions.
- Fix: raise `McpError("mcp initialize result has no protocolVersion")`; list it under the GH-256 Breaking bullet.

### D-11 — TimeSeriesChart x_key/y_key typed `str`
- Round IDs: RT-014
- File: `agent_sdk/models/content_types.py:773` — `x_key: str = "date"`
- Problem: a field_validator accepts only "date"/"value" but the generated JSON schema (MCP outputSchema, A2A skill schemas) advertises any string; `_COMPACT_SCHEMAS` was hand-patched, so the contract lives in three places.
- Fix: `x_key: Literal["date"] = "date"`, `y_key: Literal["value"] = "value"`; keep the fixed error message via SafeValueError or a custom error type if needed.

### D-12 — GH-257 CHANGELOG Breaking bullet out of date
- Round IDs: RT-015
- File: `CHANGELOG.md:11`
- Problem: says `_mode_accepted` takes the per-app supported set, but GH-259 deleted it in favour of `agent_sdk/common/media.py::media_type_match`. Lists `agent_sdk/agent/runner.py` as changed by GH-257, but runner.py has no GH-257 edit.
- Fix: reword: accepted output modes use `media_type_match` against the per-app supported set (GH-259). Remove runner.py from the Changed list, or say artifact building is gated through the capabilities `_capabilities` passes in.

### D-13 — Dead TextPart line in apply_output_modes fallback
- Round IDs: RT-008 (low)
- File: `agent_sdk/agent/runner.py:436` — `texts = [p.text for p in artifact.parts if isinstance(p, TextPart)]`
- Problem: the fallback runs only when no part was kept and text/plain is accepted, so every TextPart would already be kept; the list is always empty. A FilePart-only artifact yields `TextPart(text="")`.
- Fix: drop the line, build the fallback from DataParts only (`dumps_strict(p.data)`); if empty, raise the same -32005 AgentError. Add a FilePart-only unit test.

### D-14 — Unclipped surfaceId in console tombstone note
- Round IDs: RT-009 (low)
- File: `agent_sdk/console/static/a2ui.js:138` — ``notes.push(`createSurface rejected: surface ${surfaceId} is closed`);``
- Problem: server-supplied surfaceId is printed with no length cap (chat.js:346 prints every note), against GH-255's clip-everything intent.
- Fix: use `clip(surfaceId, MAX_TEXT)` here and in the other surfaceId notes in renderA2ui.

### D-15 — Dead `turns._a2ui_advertised` pass-through
- Round IDs: RT-010 (low)
- File: `agent_sdk/testing/turns.py:132` — `async def _a2ui_advertised(driver: ChatDriver) -> bool:`
- Problem: one-line pass-through to `ChatDriver._a2ui_advertised` with no production caller; only `tests/test_gh237_testing_clients.py:743/751` import it. A second entry point next to C-080.
- Fix: delete it; point the two tests at `ChatDriver._a2ui_advertised` (or `a2ui_client_activation`).

### D-16 — `a2ui_enabled` parameter shadows the `a2ui_enabled()` helper; hand-built FAILED message
- Round IDs: RT-011 (low)
- File: `agent_sdk/routes/agent_card.py:142` — `a2ui_enabled: bool = False,`
- Problem: inside build_agent_card the name is the bool, so calling the helper there raises `TypeError: 'bool' object is not callable`. Separately, a2a.py:932 builds a FAILED status.message by hand, against GH-259's C-019 note to build it once in set_task_status.
- Fix: rename the helper (e.g. `compute_a2ui_enabled`) or the parameter (`a2ui_on`); update the app.py import and CHANGELOG. For a2a.py:932, build via `runner._agent_message`, or note why the frame-serialization fallback cannot use set_task_status.
