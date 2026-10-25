# w065 — deferred medium/low findings (phase scope)

- Wave: w065
- Scope: phase
- Date: 2026-10-24

Non-blocking — these did not block w065's archive. Address opportunistically or fold into a future wave.

Findings were raised across several redteam rounds. Repeats of the same file and issue are merged below; the original round IDs are listed for each item.

## Medium

### D-01 — A2A echoes A2UI extension the card does not declare (GH-249 seam)
- Files: agent_sdk/routes/a2a.py:318/365 (`_echo_extensions`, `_capabilities`), agent_sdk/routes/agent_card.py:156, agent_sdk/console/static/chat.js
- Rounds: RT-006, RT-005, RT-006, RT-002
- Issue: card drops A2UI when no tool `emits`, but `_echo_extensions` still echoes the A2UI URI, `_capabilities` still opts in from the header, and `runner.build_artifact` still sends A2UI DataParts. chat.js always sends the A2UI header. `testing/turns.py::_a2ui_advertised` reads the card, so acceptance quietly tests text-only (A2A v0.3.0 §5.1).
- Fix: shared `a2ui_advertised(registry, allowed_components)` in a2ui/catalog.py, computed once at build_app and stored on app.state; used by card, `_capabilities`, `_echo_extensions`, `_echo_a2ui_if_present`. chat.js sends the header only when `loadCatalogIds` found the extension. Test: no-emits agent + A2UI header -> no echo, no A2UI DataPart. Or record a ruling that runtime A2UI needs `emits=` and document it.
- Codify: when a card capability becomes conditional, every route that activates/echoes it must use the same condition.

### D-02 — Exception handler cannot stop traceback logging (GH-248 item 1, SI-2)
- File: agent_sdk/app.py:895, 934
- Rounds: RT-005, RT-004, RT-008 (low)
- Issue: `exception_handler(Exception)` runs in ServerErrorMiddleware, which re-raises; uvicorn logs the full traceback incl. `str(exc)` (may carry input). It is outermost, so the -32603 reply skips CORS/request-id middleware. Test uses `raise_app_exceptions=False` and never checks logs. A later round notes `_A2AInternalErrorMiddleware` now catches /v1/* first, leaving `_plain_internal_error` as dead code that duplicates Starlette's default 500.
- Fix: confirm the /v1 catch lives inside the stack, logs type + frame_locations only, never re-raises (only if response not started). Remove `_plain_internal_error` and its comment. Add a test with `raise_app_exceptions=True` + caplog asserting MARKER is absent from every record.
- Codify: a Starlette Exception handler never stops the server logging the traceback; scrubbing needs a catch inside the route stack.

### D-03 — pageToken check widened the stable-core TaskStore (GH-248 item 7)
- Files: agent_sdk/tasks/store.py:491, agent_sdk/tasks/memory.py, agent_sdk/routes/a2a.py:1062, docs/protocols.md:17, DESIGN.md §5.2 / C-005 row
- Rounds: RT-003, RT-004, RT-001
- Issue: AC says route-only check, store.py/memory.py unchanged. Code adds public `TaskStore.is_valid_page_token` (default True) + in-memory override, with no ruling. Docs say every non-32-hex token gets 400, false for custom stores. CHANGELOG lists new API under Fixed, not Added. No test of a custom store's non-hex token. Only unit test is misfiled in tests/test_rt001_oauth_capped_body.py and uses `__new__`.
- Fix: escalate to user. (a) Follow AC: route-level `re.fullmatch(r"[0-9a-f]{32}", pageToken)`, revert store/memory. Or (b) record a ruling on GH-248, keep hook, move CHANGELOG entry to Added, document in DESIGN.md §5.2/C-005/docs/protocols.md ("built-in store requires 32 lowercase hex; a custom store decides"), add a custom-store route test. Either way move the test into tests/test_gh248_a2a_route.py.
- Codify: a "file X is not changed" AC must not be quietly replaced by a new public hook; stop and get a ruling.

### D-04 — Wire-breaking changes filed under Fixed, not Breaking
- File: CHANGELOG.md:12-14
- Rounds: RT-004, RT-008
- Issue: DESIGN.md §4.0 needs these under `### 🔴 Breaking changes`: GH-246 (missing/null id now -32600; /mcp/messages 415), GH-247 (AG-UI `status` approved/rejected now RUN_ERROR), GH-248 (non-user `message.role` now 400), GH-249 (card drops A2UI; tier `extended` no longer matches). Release may under-bump.
- Fix: one Breaking entry per wire change: behaviour, emit/parse impact, spec clause or ruling URL, Migration line. Keep non-breaking parts under Fixed.

### D-05 — Action-gate docstrings still teach `status="approved"` on AG-UI (GH-247)
- Files: agent_sdk/contrib/action_gate/gate.py:130-133, agent_sdk/contrib/action_gate/__init__.py:40, docs/protocols.md
- Rounds: RT-004, RT-009, RT-011, RT-005 (low)
- Issue: route now refuses any status other than resolved/cancelled; docstrings call the shorthand "this SDK's core convention". docs/protocols.md says the shorthand is "accepted on the A2A resume path only", but A2A resume has no status field.
- Fix: on AG-UI, `status` is resolved/cancelled (or absent) and the decision is `payload.decision`; other status words reach `parse_decision` only through direct callers. Fix the docs/protocols.md A2A sentence.

### D-06 — chat.js role rule does not match ChatDriver `_is_role` (C-072/C-074)
- File: agent_sdk/console/static/chat.js:617 (and ~766 comment "chat.py agrees")
- Rounds: RT-008 (low), RT-006, RT-013, RT-003
- Issue: (1) chat.js records `role: ""`; ChatDriver needs non-empty, so text with role "" is kept by ChatDriver, dropped by console. (2) On CHUNK, chat.js only checks earlier CHUNKs (`seenChunkIds`); ChatDriver also refuses a role once any text exists (`key not in reply_parts`), so CONTENT(x) then CHUNK(x, role) differs. ChatDriver also records role on TEXT_MESSAGE_CONTENT.
- Fix: `const isRole = (v) => typeof v === "string" && v !== "";` on START and CHUNK; record a role only when no text is buffered for that id yet (any frame type). Node cases: role "" on START and CHUNK; CONTENT then CHUNK with role. Run one shared case table against chat.py and chat.js.
- Codify: a JS mirror of a Python fold rule must copy the exact predicate and share one case table.

### D-07 — A2A Reset race in console (GH-243 fixed AG-UI only)
- File: agent_sdk/console/static/chat.js:399, 405
- Round: RT-004
- Issue: Reset mid-`sendA2a` stream sets contextId null, then late task/message frames write the old contextId back and keep painting into the cleared transcript.
- Fix: capture a reset generation at `sendA2a` start; skip contextId writes and painting when it changed (like `threadAtSend`). Node case: Reset mid-stream, task frame arrives, contextId stays null.
- Codify: a session-reset guard must cover every transport the console drives.

### D-08 — Unplanned template repo edit (GH-245)
- File: template/.claude/skills/acceptance/SKILL.md:210 (peer repo wailuen/a2a-agent-template, commit 6e8d820, pushed)
- Rounds: RT-007, RT-007
- Issue: AC says this file is NOT edited; wave scope was acceptance-api.js only. No ratification; not in todo, CHANGELOG or C-069 row.
- Fix: escalate to user. Either record ratification (GitHub issue comment URL) and add the change to the GH-245 CHANGELOG entry and todo, or revert 6e8d820 with a follow-up commit (never force-push).

### D-09 — jsonschema core dep without uv.lock update (GH-245)
- File: pyproject.toml:22 (and :37 dev duplicate), uv.lock
- Rounds: RT-010, RT-010
- Issue: `uv lock --check` fails; uv.lock still lists jsonschema only under dev. Every production install pulls attrs/referencing/rpds-py for a test-only module. pyproject.toml not in GH-245's Modifies list.
- Fix: (a) `uv lock`, commit uv.lock, drop dev duplicate, list both files in the todo; or (b) keep it in a dev/testing extra and lazy-import inside `_check_structured` with a clear failure when absent; adjust tests/test_rt001_testing_runtime_deps.py.

### D-10 — Body cap not tested on A2A and AG-UI routes
- File: agent_sdk/routes/a2a.py:469, agent_sdk/routes/ag_ui.py
- Round: RT-011
- Issue: send/stream/run moved to `read_capped_body`, but no test pins the A2A 400 "request body too large" or the AG-UI 413.
- Fix: in tests/test_gh248_a2a_route.py and tests/test_gh235_nested_json_and_resume.py add declared over-cap Content-Length and streamed over-cap (chunk counter shows early stop) cases; pin status/body; assert no task created.

### D-11 — run_gate fails behaviour the MCP route documents as correct
- File: agent_sdk/testing/mcp.py:226, agent_sdk/routes/mcp.py (~48-54, ~990-993)
- Round: RT-005
- Issue: `_check_structured` fails an emits-tool call with no structuredContent, but the route returns isError:false with no structuredContent for a Tier-1 `None` result and calls that "NOT a failure". Test mode 'absent' pins the contradiction.
- Fix: pick one rule (route emits conforming structuredContent/isError, or gate accepts the documented fold); update route docstring, docs/testing.md and C-056 row.

### D-12 — GH-235 regression tests deleted
- File: tests/test_gh235_nested_json_and_resume.py
- Round: RT-008
- Issue: rewrite dropped `test_oauth_register_nested_is_invalid_client_metadata`, `test_a2a_deep_metadata_never_breaks_task_list`, `test_loads_strict_depth_cap_without_recursion_error` with no replacement.
- Fix: restore them (update for "nesting too deep" text where the route uses it; oauth keeps fixed invalid_client_metadata).

### D-13 — Catalog field summary still marks defaulted fields optional (GH-249 items 3-4)
- File: agent_sdk/a2ui/catalog.py:111, 134
- Rounds: RT-007, RT-011 (low)
- Issue: serialization-mode `required` includes defaulted fields only with `json_schema_serialization_defaults_required=True`; ContentModel lacks it. `_field_summary(TimeSeriesChart)` still gives `x_key?: str ...`. Only test sets the flag. Docstrings of `_field_summary`/`_annotation_str` are stale. Nested expansion is never trimmed by the 250-char budget.
- Fix: decide required-ness from what `wire()` writes (by_alias + exclude_none): required if not excluded and `is_required()` or default (via factory) is not None. Apply in `_field_summary` and `_nested_fields`. Test on default-config type: `x_key: str`, `maybe?`. Update docstrings; apply the 250-char cap to nested expansions (fall back to class name).
- Codify: use what wire() writes, never pydantic's JSON-schema required list.

### D-14 — Content-Type check differs across MCP, A2A, AG-UI
- File: agent_sdk/routes/ag_ui.py:637
- Rounds: RT-013 (low), RT-012, RT-010 (low)
- Issue: AG-UI uses a case-sensitive substring test: `Application/JSON` gets 415, while `application/json-seq`, `application/jsonx`, `text/plain; x=application/json` pass. Three separate implementations.
- Fix: move `_is_json_content_type` into agent_sdk/common/body.py (`ct.split(';')[0].strip().lower() == "application/json"`), use on all three, register in components README. AG-UI tests: `Application/JSON; charset=utf-8` accepted, `application/json-seq` / `application/jsonx` 415.

### D-15 — gh214 deleteSurface guard skips silently without node
- File: tests/test_gh214_no_delete_surface.py:89, 111
- Round: RT-014
- Issue: no CI guard (unlike gh234/gh239); `painted.isConnected !== false` is vacuous under stub DOM.
- Fix: add `test_gh214_node_available_in_ci`; keep a cheap always-on static check; mount the node in the stub document and check it stays after deleteSurface.

## Low

### D-16 — MCP missing-method branch echoes an invalid id (GH-246 item 2)
- File: agent_sdk/routes/mcp.py:501
- Rounds: RT-010, RT-012, RT-009 (medium), RT-007
- Issue: runs before `_valid_request_id`; object/array/bool id (up to 2 MiB) is reflected instead of `id: null`.
- Fix: `reply_id = request_id if _valid_request_id(request_id) else None` at top of `_dispatch`, used in every pre-handler error. Tests on /mcp and /mcp/messages for object, array, bool ids with no method: id null, marker absent.

### D-17 — OAuth capped-body test too loose and misplaced
- File: tests/test_rt001_oauth_capped_body.py:24
- Rounds: RT-014, RT-016, RT-006
- Issue: `pytest.raises(Exception)` passes on any error; hand-built Request instead of build_app() over ASGI (LRN-496); /oauth/register, /oauth/token and consent form not tested; holds an unrelated page-token test.
- Fix: `pytest.raises(HTTPException)` with `status_code == 413`, `detail == "request body too large"`. Add build_app() + httpx.ASGITransport tests: chunked over-cap to /oauth/register (400 invalid_client_metadata), /oauth/token, consent form (413), chunk counter shows early stop. Move page-token test (see D-03).

### D-18 — `drop_format_chars` docstring overclaims
- File: agent_sdk/common/redact.py:65
- Round: RT-009
- Issue: `safe_block_text` and `safe_error_text` do not call it; U+202E still reaches the wire there.
- Fix: call it in both (bidi controls only in block text, keep ZWJ), or narrow the docstring to the four helpers that use it.

### D-19 — a2ui.js multi-category chart null-period and scaling
- File: agent_sdk/console/static/a2ui.js:838
- Round: RT-009
- Issue: null period still throws in totals reduce, bar loop, `p.period`; totals include categories hidden by `capRows`; two "N more" notes unlabelled.
- Fix: filter non-objects once before `capRows`; total over capped categories only; label "N more periods" / "N more categories".

### D-20 — C-074 row and DESIGN.md §5.5 drift
- Files: workspace/components/README.md:67, DESIGN.md §5.5
- Round: RT-011
- Issue: C-074 Location names testing/turns.py, but `agui_turn` is `ChatDriver.agui_turn` in testing/chat.py; prose sits in the Location column. DESIGN.md says an acked JSON-RPC response is "`id` plus `result`/`error`", but `_is_jsonrpc_response` acks one without an id.
- Fix: Location `agent_sdk/testing/chat.py::ChatDriver.agui_turn + agent_sdk/console/static/chat.js::sendAgui`, prose to Name. DESIGN.md: "`result`/`error` with no `method` (id may be null)".

### D-21 — PEP 8 blank lines
- Files: agent_sdk/tasks/memory.py:120, agent_sdk/routes/a2a.py:168
- Rounds: RT-015, RT-012
- Issue: one blank line after `_TASK_ID_SHAPE`; `_MAX_BODY_BYTES` sits right under `_mode_accepted`'s body.
- Fix: add blank lines; move `_MAX_BODY_BYTES` next to `_SUPPORTED_MODES` above `_mode_accepted`.

---
Filed 2026-10-25 by /sdk-autoloop cycle 1: verified still-present mediums (and lows sharing a fix) are in #251–#260. Other lows stay here, unfiled.
