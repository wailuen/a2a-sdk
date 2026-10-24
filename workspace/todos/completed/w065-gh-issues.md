# w065 — GitHub issues 243–250

Sourced from open issues on wailuen/a2a-sdk filed 2026-10-24 from the w064 deferred lists and the v0.21.0 release-gate audits (each re-checked at v0.21.0, 88a045e). GH-186 is deferred by ruling. GH-224 is design-only.
Groups run in parallel unless a todo names a `Depends:` on another group's item; items inside one group share files and run in order.
Target: 0.22.0. The agent card drops an empty A2UI extension (GH-249), AG-UI refuses a bad resume `status` (GH-247), and A2A refuses `role: "agent"` from a client (GH-248).

Each issue body lists file:line, the probe and the fix for every numbered item; implement every numbered item in the issue body exactly as described there, with the ruling comment overriding the body where they differ. Do NOT edit `template/` except the peer copy named in GH-245 (G2) (LRN-085/LRN-071: it lands via commit+push to wailuen/a2a-agent-template inside this wave; the commit stages only that path). Shared files edited by more than one group (`CHANGELOG.md`, `DESIGN.md`, `docs/protocols.md`, `workspace/components/README.md`): each item edits only its own row or section with in-place Edit, never a whole-file rewrite. Each item adds its own entry to `CHANGELOG.md` `[Unreleased]`, naming every changed `agent_sdk/` file by repo path (LRN-491), and keeps exactly one `## [Unreleased]` heading (LRN-494). Tests run against `build_app()` over the ASGI transport, not hand-written fake clients (LRN-496). Every new client-facing error string is fixed text that never echoes input (SI-2).

---

## G1 — console (chat.js, a2ui.js)

- [x] `GH-243` AG-UI chat client reset race, resume-form guard and history parity with ChatDriver ‖ group:G1
  - Creates: (modifies `agent_sdk/console/static/chat.js`, `agent_sdk/console/static/a2ui.js`, `tests/test_gh234_agui_chat_driver.py`, `tests/test_gh239_console_caps.py`, `DESIGN.md` (§7 console section only), `workspace/components/README.md` (C-074 row only), `CHANGELOG.md`)
  - Reads: `agent_sdk/testing/chat.py`, `tests/test_card_console.py`
  - Severity: medium
  - Root cause: chat.js compares the thread only on the failed-resume path; the resume form bypasses `send()`'s busy guard; the fold and user-message timing differ from ChatDriver (C-072).
  - AC (item 1): `sendAgui` captures `threadAtSend` on every send. The RUN_FINISHED interrupt capture, `interruptForm()` and the post-run history fold are skipped when `state.threadId !== threadAtSend`. Node test: change `state.threadId` mid-stream, feed text + an interrupt RUN_FINISHED, assert `aguiMessages` and `pendingInterrupt` stay empty and no form is shown.
  - AC (item 2): RUN_ERROR calls `removeInterruptForm()`. The form submit returns early unless `pendingInterrupt === pending`, and runs through the same busy guard + try/catch as `send()` (one shared wrapper). Node tests for both.
  - AC (item 3): chat.js follows C-072: an explicit string role is recorded per message id and only `assistant` ids are folded; a TEXT_MESSAGE_CONTENT with no START gets a buffer and is kept as assistant; the POST body is built from `[...state.aguiMessages, userMsg]` and the user message is appended only on RUN_FINISHED. The "chat.py agrees" comment is true afterwards. Node test per case.
  - AC (item 4): `tests/test_gh234_agui_chat_driver.py` and `tests/test_gh239_console_caps.py` each gain a `test_*_available_in_ci` that fails when `CI` is truthy and `node` is absent (pattern `tests/test_card_console.py:291`); the module-level `pytestmark` in test_gh239 becomes per-test so the guard is never skipped.
  - AC (item 5): node test: `renderA2ui` creates surface S, `resetSurfaces()`, then an `updateDataModel` for S reports `unknown/closed surface S`; a chat.js harness case runs the Reset handler and asserts `pendingInterrupt === null` and no form left.
  - GH: https://github.com/wailuen/a2a-sdk/issues/243
  - Reuses: C-072  # AG-UI history fold rule (agent_sdk/testing/chat.py + chat.js). chat.js must match it; reference only, GH-245 owns the C-072 row edit.
  - Reuses: C-074  # Item 3 changes the chat.js half of C-074 agui_history_fold_rule (explicit string role per id, only assistant ids folded, user message appended on RUN_FINISHED); C-072 (agui_terminal_stream_reader) stays the reference behaviour. Update the C-074 row; GH-245 edits the same row after this todo.

- [x] `GH-244` a2ui.js chart/column caps and replayed-createSurface wording + tests ‖ group:G1
  - Creates: (modifies `agent_sdk/console/static/a2ui.js`, `DESIGN.md` (§5.4 replay sentence and §7.1 cap sentence only), `tests/test_gh239_console_caps.py`, `tests/test_a2ui_wire.py`, `tests/test_gh214_no_delete_surface.py`, `workspace/components/README.md` (C-059 row only), `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/a2a.py`
  - Severity: medium
  - Depends: GH-243
  - Root cause: GH-239 capped lists, tables and BarChart only; docs call a replayed createSurface a no-op while the renderer logs a protocol error.
  - AC (item 1): `renderWaterfallChart` segments and `renderMultiCategoryChart` periods (and categories/legend) use `capRows`/`moreNote`; `renderTimeSeriesChart` is capped at `MAX_ROWS` points with a note; `renderComparisonTable` caps columns at 10 with an "N more" note; no `Math.max(...x)` / `Math.min(...x)` spread over payload arrays remains. DESIGN.md §7.1 lists exactly what is capped. Node test with `MAX_ROWS + 5` items for each renderer.
  - AC (item 2): DESIGN.md §5.4 and §7.1 say: replay reuses the same surfaceId; the console ignores a duplicate createSurface for an open surface (with a warning) and still applies updates; third-party renderers may treat it as an error; replay happens on `tasks/get` and `tasks/resubscribe`. The a2ui.js warning text matches.
  - AC (item 3): node test folds the same artifact messages through `renderA2ui` twice: one surface, one painted node, no error notes. A `tasks/resubscribe` case in `tests/test_a2ui_wire.py` checks the same surfaceId.
  - AC (item 4): `tests/test_gh214_no_delete_surface.py:76-86` docstring corrected as in the issue; the source grep is replaced by a node test (create+update+data, then deleteSurface: node stays attached, a later updateComponents is dropped).
  - AC (item 5): `test_registry_keeps_connected_surfaces` asserts no `unknown/closed surface p` note and that the repainted node text shows `2`.
  - GH: https://github.com/wailuen/a2a-sdk/issues/244
  - Reuses: C-059  # Item 1 extends the shared MAX_ROWS cap (capRows/moreNote) to waterfall, multi-category, time-series and comparison-table renderers in agent_sdk/console/static/a2ui.js. Every new cap calls the existing capRows/moreNote (no per-renderer copy); update the C-059 row to list the capped renderers and the 10-column limit.

## G2 — test clients and acceptance gate

- [x] `GH-245` test clients and acceptance gate lows ‖ group:G2
  - Creates: (modifies `agent_sdk/testing/chat.py`, `agent_sdk/testing/mcp.py`, `agent_sdk/testing/turns.py`, `harness/workflows/acceptance-api.js`, `template/.claude/workflows/acceptance-api.js`, `harness/skills/acceptance/SKILL.md`, `.claude/skills/acceptance/SKILL.md`, `docs/testing.md`, `workspace/components/README.md` (C-056, C-069, C-072 and C-074 rows only), `tests/test_gh237_testing_clients.py`, `tests/test_gh234_agui_chat_driver.py`, `tests/test_chat_driver.py`, `tests/test_gh131_acceptance_api_args_normalization.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/mcp.py`, `agent_sdk/agent/loop.py`, `agent_sdk/app.py`, `tests/test_gh209_testing_mcp.py`
  - Severity: medium
  - Depends: GH-243
  - Root cause: key-presence role check, name-only load_skill exclusion, hard-coded MCP version, no A2UI activation in turns.py, unvalidated acceptance-api args.
  - AC (item 1): `ChatDriver` records a role only when it is a non-empty string (START and first-CHUNK paths); `role: null` text is kept. `ROLE_CASES` rows for `role: None` on START and on CHUNK.
  - AC (item 2): `_check_list` excludes only the SDK's built-in load_skill (matched by its fixed shape, or an explicit `skills_tool` option on `run_gate`), importing `LOAD_SKILL_TOOL`. Tests: a domain tier-1 `load_skill` without `skills_dir` is counted; with the built-in present, a wrong `expected_count` still fails. Real `build_app()` over ASGI.
  - AC (item 3): `McpClient` uses `SUPPORTED_PROTOCOL_VERSIONS[0]` and sends the negotiated version as `MCP-Protocol-Version` on every request after initialize. Test asserts the header.
  - AC (item 4): `run_gate` validates each called tool's `structuredContent` against its `outputSchema` with `jsonschema` and fails on mismatch or absence. Test with a conforming and a non-conforming tool.
  - AC (item 5): `turns.py` `_a2a_attempt` reads the agent card once, sends `X-A2A-Extensions` with the A2UI URI when advertised, and puts `a2uiClientCapabilities` in message metadata as `ChatDriver` does. Test asserts header + metadata.
  - AC (item 6): `NOT_AUTHENTICATED` is renamed to the spec meaning (old name kept as a deprecated alias, test updated); missing `preferredTransport` defaults to `"JSONRPC"` (rejected with the existing clear error); posted AG-UI messages carry `id`; the `agui_turn` docstring is corrected.
  - AC (items 7, 8): in BOTH acceptance-api.js copies (byte-identical), `transports` entries other than `a2a`/`agui` push the fixed `transports (allowed: a2a, agui)` bad-arg text, and a non-empty `onlyIds` matching no scenario throws `acceptance-api: onlyIds matched no scenario` (no id or keyFile echo). Node mutation cases for `["A2A"]`, `[5]`, `["a2a","x"]`, `onlyIds: ["s-1"]`. Template copy committed and pushed to wailuen/a2a-agent-template (stage only that path).
  - AC (item 9): the test, docs/testing.md, acceptance SKILL.md and C-072 row changes listed in the issue.
  - AC (item 9, mirror): `harness/skills/acceptance/SKILL.md` and its local copy `.claude/skills/acceptance/SKILL.md` get the same edit and stay byte-identical (`tests/test_rt004_r5_acceptance_skill_mirror_parity.py::test_the_two_halves_are_byte_identical` and `tests/test_workflow_sync.py::test_skill_runtime_and_harness_copies_are_identical` stay GREEN). `template/.claude/skills/acceptance/SKILL.md` is NOT edited.
  - GH: https://github.com/wailuen/a2a-sdk/issues/245
  - Reuses: C-056  # McpTestClient/run_gate in agent_sdk/testing/mcp.py; item 2 changes its load_skill rule (built-in matched by fixed shape or a skills_tool option) and item 4 adds outputSchema checks of structuredContent. Update the C-056 row.
  - Reuses: C-069  # acceptance-api.js normalizedArgs guards (harness + template mirror); items 7 and 8 extend the GH-242 guard with identical lines in both copies. Update the C-069 row.
  - SI: SI-2  # acceptance-api.js args carry the service-key file path; the new errors are fixed text and never echo args.
  - Reuses: C-072  # Item 1 changes role recording on START and first-CHUNK paths, the assistant-role reply filter owned by C-072 agui_terminal_stream_reader (agent_sdk/testing/chat.py::ChatDriver._run_agui).
  - Reuses: C-055  # Items 5 and 6 change agent_sdk/testing/turns.py (throttled-turn client). turns.py already imports ChatDriver: the card read, X-A2A-Extensions header and a2uiClientCapabilities metadata call ChatDriver's _discover_card / _caps / A2UI_EXTENSION_URI path, no second copy.
  - Reuses: C-074  # Item 6 (ids on posted AG-UI messages, corrected agui_turn docstring) changes the turns.py half of C-074 agui_history_fold_rule; GH-243 changes the chat.js half first. Update the C-074 row after GH-243's edit.

## G3 — MCP route

- [x] `GH-246` body buffered before size cap, id-less tools/call runs, version-future tool fields, legacy /mcp/messages parity ‖ group:G3
  - Creates: `agent_sdk/common/body.py`; (modifies `agent_sdk/routes/mcp.py`, `agent_sdk/routes/oauth.py` (/oauth/register and _parse_form use read_capped_body), `DESIGN.md` (MCP version sentence ~380 only), `docs/protocols.md` (MCP section only), `workspace/components/README.md` (C-070 row, C-076 row, and one new row for the body helper), `tests/test_gh205_mcp_skills.py`, `CHANGELOG.md`; new `tests/test_gh246_mcp_route.py`, `tests/test_rt001_oauth_capped_body.py`)
  - Reads: `agent_sdk/contrib/webhooks/graph.py`, `agent_sdk/routes/a2a.py`
  - Severity: medium
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/246#issuecomment-6381440418
  - Root cause: `request.body()` before the cap; `_dispatch` treats only `notifications/*` as notifications; DESIGN.md contradicts itself on version gating.
  - AC (item 1): new `agent_sdk/common/body.py` exposes one async helper that rejects a declared Content-Length over the cap and otherwise reads `request.stream()`, stopping once the cap is passed (pattern `contrib/webhooks/graph.py:88-104`). `POST /mcp` and `POST /mcp/messages` use it; same 413 response as today. Test: an over-cap streamed body is refused without being fully read (chunk counter), and a declared over-cap Content-Length is refused before any read.
  - AC (item 2): a non-notification method with a missing, null or non-(str|int) id → `-32600 Invalid Request` with `id: null` before any handler runs, on both routes. Test that the tool did not run.
  - AC (item 3, ruling (b)): tool `title`, `outputSchema` and `structuredContent` stay on for every negotiated version; DESIGN.md ~380 states tools/list is version-independent by choice and only `serverInfo.title`/`icons` in initialize are version-gated. No version threading into `_dispatch`.
  - AC (items 4–9): the comment fix at ~541; `/mcp/messages` gets the Content-Type check, the JSON-RPC response-ack branch and a JSON 503 body; the Content-Type compare is case-insensitive; `_skill_catalog` uses `continue` not `break` (test: long first entry, short later ones listed); load_skill success carries `"isError": false`; one shared `_page(entries, cursor)` helper for tools/list and prompts/list, and the C-070 row is updated without line anchors.
  - GH: https://github.com/wailuen/a2a-sdk/issues/246
  - Reuses: C-070  # MCP cursor paging; the duplicated try/decode/slice moves into one helper.
  - SI: SI-2  # new 413/-32600/503 paths are fixed text; nothing from the body is echoed.
  - Reuses: C-076  # Item 6 changes _skill_catalog (agent_sdk/routes/mcp.py:628, break at :642) from break to continue, which changes the C-076 bounded_catalog_listing contract (GH-236). Update the C-076 row.
  - AC: the body.py helper reports over-cap as a signal (raise or sentinel), not a ready-made 413 response, so callers like contrib/webhooks/graph.py can keep their own drop+202 behaviour.

## G4 — AG-UI route

- [x] `GH-247` resume input validation lows ‖ group:G4
  - Creates: (modifies `agent_sdk/routes/ag_ui.py`, `docs/protocols.md` (AG-UI resume paragraph only), `tests/test_gh235_nested_json_and_resume.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/common/json_strict.py`, `agent_sdk/common/body.py`
  - Severity: low
  - Depends: GH-246
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/247#issuecomment-6381440613
  - Root cause: non-list `resume` coerced to `[]`; `_resume_interrupt_id` ignores the one-entry rule; `status` unchecked; tool deltas use lenient `json.dumps`.
  - AC (item 1): a present, non-null, non-list `resume` → RUN_ERROR `invalid resume entry`, code `validation`. Tests with a dict and a string carrying a hostile marker (absent from the frame).
  - AC (item 2): `_resume_interrupt_id` returns `""` unless `len(resume_raw) == 1`. Test: at the per-task cap, a two-entry body gets RUN_ERROR, not 429.
  - AC (item 3, ruling (a)): a present non-null `status` outside `{"resolved","cancelled"}` → RUN_ERROR `invalid resume entry` before any lookup or delivery; missing/null status is still delivered as `None`. Tests for `"banana"`, `5`, missing.
  - AC (item 4): TOOL_CALL_ARGS deltas and tool result content use `dumps_strict` (C-040) with a fixed fallback; test with a NaN argument.
  - AC (item 5): docs/protocols.md states `resume` holds exactly one entry and what more than one, a non-list, or a bad status returns.
  - AC: `POST /ag-ui/run` reads its body through the GH-246 helper in `agent_sdk/common/body.py` with its existing cap and error.
  - GH: https://github.com/wailuen/a2a-sdk/issues/247
  - SI: SI-2  # resume errors carry no entry content.
  - Reuses: C-040  # Item 4 moves the TOOL_CALL_ARGS delta (agent_sdk/routes/ag_ui.py:328 json.dumps(..., default=str)) and tool-result content (:336) to dumps_strict.

## G5 — A2A route

- [x] `GH-248` text/plain 500s, output-mode and media-type matching, historyLength, role check, subscribe GET, response-shape docs ‖ group:G5
  - Creates: (modifies `agent_sdk/routes/a2a.py`, `agent_sdk/app.py`, `DESIGN.md` (§1 A2A wire-shape note and ~274 only), `docs/protocols.md` (A2A section only), `CHANGELOG.md`; new `tests/test_gh248_a2a_route.py`)
  - Reads: `agent_sdk/models/a2a.py`, `agent_sdk/models/errors.py`, `agent_sdk/common/body.py`
  - Severity: medium
  - Depends: GH-246
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/248#issuecomment-6381440791
  - Root cause: no generic exception handler on `/v1/*`; exact-string MIME matching; history length not passed on resume/stream; no role check.
  - AC (item 1): an `Exception` handler scoped to `/v1/…` returns `{"error":{"code":-32603,"message":"internal error"}}` (JSON, fixed text), logging the exception type only; MCP and AG-UI behaviour unchanged. Probe test (patched store raises) → JSON -32603.
  - AC (items 2, 3): `acceptedOutputModes` matching is case-insensitive, ignores parameters and treats `*/*` and `type/*` as wildcards (`"text"` kept as documented legacy alias); request Content-Type compare is case-insensitive. Tests for `*/*`, `text/*`, `Text/Plain`, `Application/JSON`.
  - AC (item 4): `historyLength` is honoured on the resume branch of message:send and on the message:stream first snapshot. Tests with `historyLength=0`.
  - AC (item 5): a client message with `role != "user"` → 400 `-32602` "message.role must be user". Test.
  - AC (item 6): one HTTP status for `-32004` (501, per `models/errors.py`) or the 405 documented as transport-level; tests pin the choice.
  - AC (item 7): on `GET /v1/tasks` (agent_sdk/routes/a2a.py `tasks_list`), a non-empty `pageToken` that does not match the task-id shape the SDK mints (uuid4 hex, `^[0-9a-f]{32}$`, see `new_task` in agent_sdk/agent/runner.py), including any token longer than 32 characters, gets 400 `-32602` "invalid pageToken" (fixed text, token never echoed). An absent or empty token still means the first page (the route returns `nextPageToken: ""` on the last page). The check lives at the route only; `agent_sdk/tasks/store.py` and `agent_sdk/tasks/memory.py` are not changed. Tests: a non-hex token, a 33-char hex token and a hostile marker → 400 (marker absent from the body); empty token → first page; the `nextPageToken` from page 1 → page 2.
  - AC (item 8, ruling (a)): `GET /v1/tasks/{id}:subscribe` is served by the same handler, auth and admission cap as POST. Test both verbs.
  - AC (item 9, ruling (a)): wire stays bare; DESIGN.md §1 and docs/protocols.md record the reason and the difference from the proto's wrapped `SendMessageResponse`/`StreamResponse`.
  - AC: A2A send/stream body reads use the GH-246 helper in `agent_sdk/common/body.py`.
  - GH: https://github.com/wailuen/a2a-sdk/issues/248
  - SI: SI-2  # -32603 and -32602 texts are fixed; no exception text or token value is echoed.
  - Reuses: C-070  # Item 7 reuses only mcp_paginate's fixed-text -32602 error shape, not its base64 cursor decode (_decode_cursor): A2A pageTokens are raw task ids.
  - Reuses: C-005  # Item 7 validates the pageToken shape at the route, before TaskStore.list_tasks_for_identity; the store contract (opaque token) and agent_sdk/tasks/store.py / agent_sdk/tasks/memory.py stay unchanged.
  - SI: SI-5  # Item 8 mounts a new data route GET /v1/tasks/{task_id}:subscribe beside the POST at agent_sdk/routes/a2a.py:1219.
  - AC (item 8, SI-5): the GET verb has Depends(require_identity), guard_origin, the per-identity 404 for foreign or unknown tasks, and a 401 + WWW-Authenticate resource_metadata reply (LRN-003). Test both verbs without credentials.

## G6 — A2UI gating and catalog

- [x] `GH-249` empty-catalog card extension, tier match, catalog summary, gating docstring, GH-240 test gaps ‖ group:G6
  - Creates: (modifies `agent_sdk/a2ui/translator.py`, `agent_sdk/a2ui/catalog.py`, `agent_sdk/routes/agent_card.py`, `docs/protocols.md` (agent card paragraph only), `workspace/components/README.md` (C-006 row and detail only), `tests/test_gh240_a2a_catalog_negotiation.py`, `tests/test_gh240_field_summary_alias.py`, `CHANGELOG.md`; new `tests/test_gh249_a2ui_gating.py`)
  - Reads: `agent_sdk/routes/ag_ui.py`, `agent_sdk/routes/a2a.py`, `tests/test_a2ui_wire.py`
  - Severity: medium
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/249#issuecomment-6381440938
  - Root cause: the card always appends the A2UI extension; tier uses a substring test; `_field_summary` reads `is_required()`.
  - AC (item 1, ruling (a)): when `supportedCatalogIds` would be empty the agent card carries no A2UI extension; existing card tests updated; docs say so.
  - AC (item 2): `extended` is true only for `tier == "core+extended"` (plus any explicitly listed legacy token); `non-extended` → core. Test.
  - AC (items 3, 4): `_field_summary` marks a field required when the serialization-mode schema lists it, and expands nested models one level; the compact-schema header says "required fields and common optional fields shown". Tests on a custom type.
  - AC (item 5): the translator module docstring describes `allows()` as in the issue; the duplicated C-006 GH-240 sentence is merged.
  - AC (item 6): `SurfaceRegistry` / `apply_data_model_update` are marked internal in their docstrings and left out of `__all__` (no behaviour change).
  - AC (item 7): the GH-240 test gaps in the issue: AG-UI case goes through `routes/ag_ui.py::_capabilities`; mixed domain/Standard A2A case; Extended Standard type under negotiation; pin for `{"catalogs": [], "v0.9": {...}}`; `_Aliased` gets its own `catalog_id`, a `Field(alias=...)` field and a docstring with the ruling URL.
  - GH: https://github.com/wailuen/a2a-sdk/issues/249
  - Reuses: C-006  # A2uiCapabilities gating (agent_sdk/a2ui/translator.py).

## G7 — core ingress and safe text

- [x] `GH-250` depth-cap docs and message, Graph webhook parser, boot store leak, bidi safe-text hardening ‖ group:G7
  - Creates: (modifies `agent_sdk/common/json_strict.py`, `agent_sdk/common/redact.py`, `agent_sdk/agent/loop.py`, `agent_sdk/models/errors.py`, `agent_sdk/contrib/webhooks/graph.py`, `agent_sdk/app.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/routes/a2a.py`, `agent_sdk/routes/ag_ui.py`, `docs/protocols.md` (ingress paragraph only), `docs/content-types.md`, `DESIGN.md` (ingress sentence only), `workspace/components/README.md` (C-040 row/detail, C-034 row, C-050 row/detail, C-030 detail, C-073 row, one new row for the format-char helper), `tests/test_gh235_nested_json_and_resume.py`, `tests/test_gh205_mcp_skills.py`, `tests/test_rt001_strict_required_nullable_output.py`, `tests/test_gh212_id_safe_text.py`, `tests/test_gh230_safe_value_error.py`, `CHANGELOG.md`; new `tests/test_gh250_core_hardening.py`)
  - Reads: `agent_sdk/__init__.py`
  - Severity: medium
  - Depends: GH-246, GH-247, GH-248
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/250#issuecomment-6381441157
  - Root cause: depth cap undocumented and reported as generic bad JSON; graph.py bypasses C-040; post-open boot errors leak the store; the format-char drop is private to the SafeValueError path.
  - AC (item 1, ruling): cap stays 64 and the code stays `-32700` (MCP/A2A) / the existing AG-UI RUN_ERROR, but the client-facing message for too-deep input is the fixed "nesting too deep" on MCP (both routes), A2A and AG-UI, distinct from the malformed-JSON text. Documented in docs/protocols.md, DESIGN.md, the C-040 row/detail and the `loads_strict` docstring, including ~61 levels left for tool arguments. Tests per surface.
  - AC (item 2): `contrib/webhooks/graph.py` parses with `loads_strict` and drops+202s on `json.JSONDecodeError`/`ValueError`/`UnicodeDecodeError`. Nested-body webhook test.
  - AC (item 3): SkillsRegistry load and the `exclude_from_catalog` check run before `_build_credential_store()`; remaining post-open boot code closes the store on any exception. `test_boot_checks_run_before_credential_store` gains an unknown `exclude_from_catalog` case and a `mcp_skills="tool", skills_dir=None` case.
  - AC (item 4, ruling (a)): one named helper in `agent_sdk/common/redact.py` drops Cf/bidi controls (U+202A–202E, U+2066–2069 and other Cf); `safe_line_text`, `safe_cell_text`, `safe_id_text` and the SafeValueError hint path all use it; the id alphabet is otherwise byte-exact. U+202E added to the GH-212 and GH-230 hostile sets; new helper row in the components README.
  - AC (item 5): `SafeValueError.__init_subclass__` runs the shared sanitiser and raises TypeError when the cleaned message is empty; lookup simplified; docstrings updated.
  - AC (item 6): docs/content-types.md states one id rule and the full set kept inside an is_id cell, as in the issue.
  - AC (item 7): every test-hardening bullet in the issue, including `safe_joined_id_text` in `test_exported`.
  - GH: https://github.com/wailuen/a2a-sdk/issues/250
  - Reuses: C-040  # loads_strict; the depth message change lives here and routes surface it.
  - Reuses: C-034  # safe_line_text; the format-char drop sits next to it.
  - SI: SI-2  # depth and boot errors are fixed text; no body or store path is echoed.
  - Reuses: C-050  # Items 4 and 5 change the SafeValueError hint path (format/bidi drop) and SafeValueError.__init_subclass__ (C-050 safe_validation_message, agent_sdk/agent/loop.py). Update the C-050 row/detail to point at the new redact.py format-char helper.
  - Reuses: C-030  # Item 4 makes safe_id_text drop Cf/bidi controls via the new helper, changing its documented contract. Update the C-030 detail and the C-073 safe_joined_id_text row (item 7 adds it to test_exported).
  - Reuses: GH-246 body-cap helper (agent_sdk/common/body.py)  # graph.py:88-104 is the capped-stream reader GH-246 copies into body.py.
  - AC: agent_sdk/contrib/webhooks/graph.py reads its body through the agent_sdk/common/body.py helper (no second loop), keeping its drop+202 on over-cap.
  - SI: SI-6  # Item 3 reorders boot around _build_credential_store() in agent_sdk/app.py and adds close-on-exception for the store.
  - AC (item 3, SI-6): the encrypted store stays the only credential source during the reordered boot (no env or settings fallback while the store is not yet built), and the close-on-exception path logs neither the store path nor any key material.

---

Archived by hand 2026-10-24: sdk-wave run wf_ac357ec9-2d3 finished with every advisor at 0 critical / 0 high and the pre-archive pytest gate green (4343 passed); `testsRed`/`protocolBlocked` flags came from an earlier unit round (template acceptance SKILL.md drift, fixed in-wave) and medium-only audits. The 10 sdk-candidates were re-checked against the code and all are fixed (jsonschema now a runtime dependency; `_resume_interrupt_id` checks status; U+202E in HOSTILE_STANDALONE). Wave also touched, beyond the plan: `agent_sdk/routes/oauth.py` (read_capped_body), `agent_sdk/tasks/store.py` + `memory.py` (`is_valid_page_token`), `agent_sdk/example/agent.py` (resume status), `pyproject.toml` (jsonschema runtime dep). Mediums: deferred/w065-*.
