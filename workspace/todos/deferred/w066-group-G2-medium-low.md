# w066 — unit:G2 — deferred medium/low findings

- Wave: w066
- Scope: unit:G2
- Date: 2026-10-25

Non-blocking — these did not block w066's archive. Address opportunistically or fold into a future wave.

Findings accumulated across every redteam round, deduped by file + description (same defect reported in two rounds is merged; both round IDs kept).

## Medium

### D-01 — A2UI opt-in ignores acceptedOutputModes (RT-001) [sdkCandidate]
- File: agent_sdk/routes/a2a.py:437
- Quote: `opted_in = A2UI_EXTENSION_URI in [u.strip() for u in extensions.split(",")] and a2ui_enabled`
- Problem: A2UI is turned on from the header alone. Header + acceptedOutputModes ["application/json"] builds TextPart + A2UI DataPart, no JSON dump; apply_output_modes removes both and the task fails -32005. Without the header the same request succeeds. With ["text/plain","application/json"] the client loses the structured data. tests/test_gh259_a2a_route.py::test_modes_none_remain_and_text_not_accepted_is_32005 locks this in.
- Fix: set opted_in only when acceptedOutputModes is missing/empty or some mode media_type_match(m, {A2UI_MIME_TYPE}). build_artifact then falls back to the JSON DataPart. Change the -32005 test to expect a completed task with one data part.
- Codify: Decide on A2UI before building the artifact, using both the client opt-in and acceptedOutputModes; filtering after the build cannot bring back the JSON fallback that was never built.

### D-02 — acceptedOutputModes filtering listed as Fixed, not Breaking (RT-002) [sdkCandidate]
- File: CHANGELOG.md:26
- Problem: GH-259 changes response shape: ["text/plain"] now gets text only; ["application/json"] drops the TextPart; ["application/a2ui+json"] without header, or ["application/json"] with header, fails -32005 after the tool ran.
- Fix: move that part under `### 🔴 Breaking changes` with a Migration line: send the modes you can render, or omit acceptedOutputModes to get every part.
- Codify: Applying a request field that used to be only checked changes the response shape, so record it as Breaking with a migration line.

### D-03 — a2ui_enabled defaults to True (fail-open) (RT-004 r1, RT-005 r1, RT-004 r2) [sdkCandidate]
- Files: agent_sdk/routes/a2a.py:430 (`_capabilities`), agent_sdk/routes/a2a.py:443 (`_config_error`), agent_sdk/routes/ag_ui.py:538 (`_capabilities`)
- Quotes: `message: Message, request: Request, *, a2ui_enabled: bool = True` / `def _capabilities(body: dict[str, Any], *, a2ui_enabled: bool = True) -> A2uiCapabilities:`
- Problem: a caller that omits the flag re-enables A2UI (A2A DataParts, a2ui output mode, AG-UI CUSTOM events) when the card says off. build_agent_card defaults to False. Violates C-006 / LRN-046 fail-closed.
- Fix: make a2ui_enabled a required keyword (no default) in all three, or default False. Call sites already pass request.app.state.a2ui_enabled.
- Codify: A capability-gate parameter must never default to enabled; make it required or default it to off.

### D-04 — Ingress mode check uses app-wide set, not per-request opt-in (RT-006 r1) [sdkCandidate]
- File: agent_sdk/routes/a2a.py:456
- Quote: `if not any(media_type_match(m, supported) for m in config.accepted_output_modes):`
- Problem: A2UI on, acceptedOutputModes ["application/a2ui+json"], no X-A2A-Extensions header passes ingress; the whole turn runs, then fails -32005.
- Fix: in _config_error include A2UI_MIME_TYPE in the supported set only when a2ui_enabled AND the header opts in; reject up front with -32005 before task creation. Add a build_app() test.
- Codify: An acceptedOutputModes check must use the set this request can actually receive, not the app-wide set.

### D-05 — A2UI-off gate tests cannot fail (RT-010 r1, RT-003 r2) [sdkCandidate]
- File: tests/test_gh257_single_a2ui_gate.py:36, :173
- Quotes: `async def plain(inp: _In) -> dict:` / `assert not [f for f in frames if f["type"] == "CUSTOM" and f["name"] == "A2UI_UPDATE"]`
- Problem: the off-app's only tool returns a dict, so no ContentModel artifact exists. test_card_state_and_runtime_agree[False] and test_ag_ui_off_drops_forwarded_caps pass with the gate removed. test_modes_with_a2ui_off (*/*, application/*) sends no header and only checks for no error.
- Fix: monkeypatch app.state.a2ui_enabled = False on an emitting app after build_app() (or emit a ContentModel with catalog_id None). Send header opt-in (A2A) / forwardedProps.a2uiClientCapabilities (AG-UI); assert no A2UI DataPart on /v1/message:send for */* and application/*, and no A2UI_UPDATE on /ag-ui/run.
- Codify: A gate test must build a case where the gate is the only thing stopping the output; check this by removing the gate and watching the test fail.

### D-06 — Duplicate-key check is a second local json.loads (RT-007 r1, RT-009 r2) [sdkCandidate]
- File: agent_sdk/credentials/forwarding.py:85
- Quote: `json.loads(decoded, object_pairs_hook=_no_duplicate_keys)`
- Problem: parse_header parses twice (loads_strict, then plain json.loads). Local re-check forbidden by C-040 note in GH-251; skips depth/encoding guards (safe only by call order); doubles parse cost.
- Fix: add `reject_duplicate_keys=True` (or object_pairs_hook) to loads_strict in agent_sdk/common/json_strict.py, register under C-040, call loads_strict once.
- Codify: Strict-JSON rules (NaN, depth, duplicates) live in json_strict.py only; a caller never adds a second json.loads pass.

### D-07 — Artifact metadata.mimeType stale after filtering (RT-003 r1, RT-011 r2) [sdkCandidate]
- File: agent_sdk/agent/runner.py:443
- Quote: `return artifact.model_copy(update={"parts": kept})`
- Problem: after the A2UI DataPart is removed (e.g. ["text/plain"] with header), artifact still has metadata.mimeType == "application/a2ui+json" with only a TextPart. Verified in wire() output.
- Fix: in the same model_copy, drop/rewrite metadata['mimeType'] when no kept part has that media type. Assert on metadata in test_modes_none_remain_text_accepted_gives_text_fallback.
- Codify: Filtering an artifact's parts must also update artifact-level metadata that describes those parts.

### D-08 — C-079 registry row stale; is_json_content_type unregistered (RT-008 r1, RT-006 r2) [sdkCandidate]
- File: workspace/components/README.md:72
- Problem: row still says "AG-UI 415 check can reuse it"; routes use body.is_json_content_type, which is listed nowhere.
- Fix: edit C-079 note: "Request Content-Type: common/body.py::is_json_content_type (normalize_media_type + exact application/json or +json, no wildcards; GH-251) used by routes/a2a.py _parse_send, routes/ag_ui.py ag_ui_run and routes/mcp.py mcp_post/mcp_messages." Delete the "can reuse it" clause.

### D-09 — C-006 registry row not updated for GH-257 (RT-007 r2) [sdkCandidate]
- File: workspace/components/README.md:10
- Quote: `| C-006 | A2uiCapabilityGate | agent_sdk/a2ui/translator.py (alongside A2uiCapabilities) | present |`
- Fix: list callers routes/a2a.py::_capabilities (header opt-in and a2ui_enabled) and routes/ag_ui.py::_capabilities (forwardedProps and a2ui_enabled); single gate is routes/agent_card.py::a2ui_enabled, computed once in build_app() (GH-257).

### D-10 — Stale AG-UI body-cap comment (GH-251 item 6 not done) (RT-005 r2) [sdkCandidate]
- File: agent_sdk/routes/ag_ui.py:87
- Quote: `_MAX_BODY_BYTES = 1 * 1024 * 1024  # 1 MB — mirrors MCP/OAuth caps`
- Problem: MCP is 2 MB, OAuth 16 KB; CHANGELOG claims "Stale comments fixed".
- Fix: `# 1 MB, same as the A2A body cap (MCP 2 MB, OAuth 16 KB)`.

### D-11 — mcp.py `_is_json_content_type` wrapper kept (RT-009 r1 medium, RT-008 r2 low) [sdkCandidate]
- File: agent_sdk/routes/mcp.py:477
- Quote: `def _is_json_content_type(request: Request) -> bool:`
- Problem: GH-251 Reuses said delete it ("no fourth copy"). Missing-header rule now lives in three places.
- Fix: delete the wrapper; either inline `ct = request.headers.get("content-type", ""); if ct and not is_json_content_type(ct):` at mcp_post and mcp_messages, or add `allow_missing` to is_json_content_type and use it in all three routes.

## Low

### D-12 — Empty TextPart fallback; dead TextPart branch (RT-011 r1, RT-010 r2) [sdkCandidate]
- File: agent_sdk/agent/runner.py:436, :442
- Quotes: `texts = [p.text for p in artifact.parts if isinstance(p, TextPart)]` / `kept = [TextPart(text="\n".join(t for t in texts if t))]`
- Problem: fallback runs only when no part matched, so with text/plain accepted `texts` is always empty (dead). FilePart-only artifacts get TextPart(text="").
- Fix: build fallback only from DataPart dumps; when joined text is empty raise -32005 AgentError (or skip artifact). Add a unit test.

### D-13 — Deferred -32005 path untested (RT-012 r1)
- File: agent_sdk/agent/runner.py:1193
- Quote: `if isinstance(exc, AgentError) and exc.a2a_code == -32005:`
- Fix: build_app() test with a deferred tool, acceptedOutputModes ["application/json"] and an A2UI-only artifact; assert FAILED, error.code -32005, status.message set.

### D-14 — Plan vs landed file set differ (RT-013 r1)
- File: agent_sdk/tasks/store.py:120
- Quote: `accepted_output_modes: list[str] | None = None`
- Problem: tasks/store.py modified but listed only under Reads (GH-259). tests/test_gh249_a2ui_gating.py listed in GH-257 Creates but untouched; tests landed in tests/test_gh257_single_a2ui_gate.py (unlisted).
- Fix: record store.py and test_gh257_single_a2ui_gate.py in the w066 GH-257/GH-259 todo bodies; drop test_gh249 from Creates.

### D-15 — Hand-built failed tail message; resume modes not stored (RT-012 r2) [sdkCandidate]
- File: agent_sdk/routes/a2a.py:934 (and :550)
- Quote: `parts=[TextPart(text="invalid agent response")],`
- Problem: _unserializable_tail builds status.message by hand (no taskId/contextId), bypassing set_task_status (C-019); literal duplicated beside WireError.message. Resume's new acceptedOutputModes are checked but not stored.
- Fix: use runner._agent_message(record, msg) with msg shared with the WireError; on resume update record.accepted_output_modes when non-empty modes are sent.

---
Filed 2026-10-25 by /sdk-autoloop cycle 2: verified still-present mediums (and lows sharing a fix) are in #261–#267. Other lows stay here, unfiled.
