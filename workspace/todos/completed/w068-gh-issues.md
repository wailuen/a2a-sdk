# w068 — GitHub issues 268–274

Sourced from open issues on wailuen/a2a-sdk, filed 2026-10-25 by /sdk-autoloop cycle 3 from the verified w067 deferred lists (each re-checked at v0.24.0, 45f8358). Rulings were posted on every issue before this wave (links per todo). GH-186 and GH-224 are labelled `deferred`.
Groups run in parallel. Items in one group share files.
Target: 0.25.0. RESERVED data_types are refused at registration (GH-270). A mismatched MCP-Protocol-Version on a known session gets 400 (GH-273). The failed-bearer 429 now carries the invalid_token challenge (GH-272).

Each issue body lists file:line and the fix for every numbered item. Implement every numbered item exactly as described there; where the ruling comment differs from the body, the ruling wins. Do NOT edit `template/` (GH-274 item 1: `template/` has no copy of the example resume code — verified by grep — so nothing lands there). Shared files edited by more than one group (`CHANGELOG.md`, `DESIGN.md`, `docs/protocols.md`, `workspace/components/README.md`) are edited with in-place Edit, each item touching only its own row or section, never a whole-file rewrite. Each item adds its own entry to `CHANGELOG.md` `[Unreleased]` (create the heading once if absent; exactly one `## [Unreleased]` heading, LRN-494, LRN-542), naming every changed `agent_sdk/` file by full repo path (LRN-491, LRN-541). Breaking items go under `### 🔴 Breaking changes` with a Migration line and the ruling URL (LRN-557). Tests run against `build_app()` over the ASGI transport, not hand-written fake clients (LRN-496). Every new client-facing error string is fixed text that never echoes input (SI-2). A test that guards a behaviour must fail when that behaviour is removed (LRN-544, LRN-560).

---

## G1 — testing helpers

- [x] `GH-268` testing: malformed SSE frames escape as tracebacks; failed card fetch cached; catalog list uncapped ‖ group:G1
  - Creates: (modifies `agent_sdk/testing/chat.py`, `agent_sdk/testing/turns.py`, `workspace/components/README.md` (C-080 and C-055 rows only), `tests/test_gh237_testing_clients.py`, `tests/test_gh234_agui_chat_driver.py`, `docs/testing.md` (only if a documented behaviour changes), `CHANGELOG.md`)
  - Reads: `agent_sdk/testing/mcp.py`
  - Severity: medium
  - Root cause: frame parsing has no shape guard; the card driver memo caches failures; card_catalog_ids has no bounds.
  - AC: items 1–5 of the issue as ruled. One test per bad shape (`data: {bad`, `data: []`, non-object status, non-string text, non-list parts) on the transport it belongs to, each asserting a failed attempt with reason `malformed-stream` and no exception. A 429 card fetch on attempt 1 followed by success on attempt 2 gets the real card. A card with 100 catalog IDs, an empty ID and a 1000-char ID gives at most 32 IDs, none empty, none over 512 chars, standard first.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/268#issuecomment-6398502309
  - GH: https://github.com/wailuen/a2a-sdk/issues/268
  - Reuses: C-080  # card fetch stays the one fetch_agent_card / ChatDriver._discover_card path (no second card parser); the C-080 row is rewritten to name fetch_agent_card, every caller (ChatDriver, turns.py _a2a_attempt and _agui_attempt), and to say catalogs come only from extra_catalogs.
  - Reuses: C-055  # the malformed-stream failure and the http-429 card-fetch failure go through C-055's existing outer guard, AG-UI message-list rollback and 429 back-off in agent_sdk/testing/turns.py, not a new try/except per attempt; the C-055 row's failure list adds malformed-stream and card-fetch 429/5xx.
  - Reuses: C-072  # the AG-UI bad-frame guard lands in ChatDriver._run_agui (agent_sdk/testing/chat.py, the registered agui_terminal_stream_reader); a bad frame ends the run as a no-terminal outcome under C-072's append-on-finish rule (nothing appended), not a separate early return.
  - SI: SI-1  # AC: each card refetch on a failed attempt reuses the caller-supplied or turn-scoped httpx.AsyncClient (turns.py) and never constructs a new client; a test asserts no new client is built across retries (same guard w067 GH-264 pinned).
  - SI: SI-2  # AC: the malformed-stream reason and any log line are fixed text and never include the raw frame, the JSONDecodeError message or the field value; a test plants a marker in the bad frame and asserts it is absent from the failure result and logs.

## G2 — AG-UI text + console

- [x] `GH-269` AG-UI unscrubbed TEXT_MESSAGE leaves a dangling START; console fallback lines uncapped ‖ group:G2
  - Creates: (modifies `agent_sdk/routes/ag_ui.py`, `agent_sdk/console/static/a2ui.js`, `tests/test_gh239_console_caps.py`, a new `tests/test_gh269_agui_text_scrub.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/common/` (`scrub_unencodable`, C-040)
  - Severity: medium
  - Root cause: TextEvent.text skips scrub_unencodable; _emit breaks mid-batch; fallbackNode caps line length but not line count.
  - AC: items 1–2 as ruled. A lone-surrogate text gives START, CONTENT (scrubbed), END, RUN_FINISHED. A forced serialization failure on CONTENT gives START, END, RUN_ERROR (no dangling START). A console node test with more than MAX_ROWS fallback lines renders MAX_ROWS lines plus the more-note, with the text clipped to MAX_PROSE first.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/269#issuecomment-6398502514
  - GH: https://github.com/wailuen/a2a-sdk/issues/269
  - Reuses: C-040  # scrub_unencodable; no second scrubber.
  - Reuses: C-059  # capRows / moreNote in a2ui.js.
  - Reuses: C-084  # clip() in a2ui.js.

## G3 — A2UI content types + catalog

- [x] `GH-270` A2UI: RESERVED data_types not refused; TimeSeriesChart keys reassignable; catalog renders Annotated/IntEnum wrong ‖ group:G3
  - Creates: (modifies `agent_sdk/models/content_types.py`, `agent_sdk/a2ui/catalog.py`, `tests/test_gh258_catalog.py`, `tests/_compact_schema.py` (reverse + nested walk only), `tests/test_content_types.py`, a new `tests/test_gh270_wire_pin.py`, `workspace/components/README.md` (C-094 row only), `docs/content-types.md` (reserved names paragraph only), `CHANGELOG.md`)
  - Reads: `DESIGN.md`
  - Severity: medium
  - Root cause: the reserved check covers component names only; no assignment guard; ClassVars are re-implemented per class; _annotation_str has no Annotated/IntEnum branches.
  - AC: items 1–6 as ruled. Reserved data_types (and case variants) raise ValueError; a non-snake_case data_type logs one WARNING (logging, not warnings — pytest runs with filterwarnings=error) and registers. `chart.x_key = "ts"` raises. The pin test is written and green BEFORE the _Wire refactor and stays green after (byte-identical `wire()` for every registered type built from its sample or a minimal instance). Round-trip test is two-way and recurses into nested _Wire shapes. `_field_summary(MarketBriefing)` has no `[Annotated]` and the MarketBriefing exclusion is removed. An IntEnum renders `1|2` unquoted. Reserved data_type refusal is under Breaking with a Migration line.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/270#issuecomment-6398502746
  - GH: https://github.com/wailuen/a2a-sdk/issues/270
  - Reuses: C-094  # item 3 moves the wire_keeps_null / wire_omitted rule into _Wire.wire(); the base serializer and agent_sdk/a2ui/catalog.py::_wire_required read the same ClassVars, and the C-094 row is updated to name the _Wire base serializer.
  - Reuses: C-020  # item 4's two-way, nested round-trip test in tests/test_gh258_catalog.py is built on tests/_compact_schema.py parse_schema / required_paths / emitted_paths, extended for the reverse and nested walk; no third key walker (w067 GH-266 ruling).
  - Reuses: C-043  # Item 1 (refuse the four RESERVED data_types and their case variants) is the same reserved-name check that C-043 drives in agent_sdk/models/content_types.py::register_content_type (RESERVED_COMPONENTS at :172, casefold loops at :1585 and :1610, _case_clash_hint at :1555). Derive the reserved data_type names from RESERVED_COMPONENTS (PascalCase to snake_case: TradeActivity -> trade_activity, and so on) and compare with the same casefold rule. Do not add a second hand-typed tuple of names that can drift from RESERVED_COMPONENTS. A test should fail if a name is added to RESERVED_COMPONENTS and not refused as a data_type.

## G4 — A2A route

- [x] `GH-271` A2A: A2UI echoed when modes rule it out; mimeType deleted not rewritten; -32004 deviation + stream route undocumented ‖ group:G4
  - Creates: (modifies `agent_sdk/routes/a2a.py`, `agent_sdk/agent/runner.py` (`apply_output_modes` only), `agent_sdk/tasks/store.py` (`TaskStore.get` docstring only), `agent_sdk/common/media.py` (new `accepts_a2ui_mode` only), `workspace/components/README.md` (C-097 row only), `docs/protocols.md` (-32004 paragraph and not-awaiting-input sentence only), `tests/test_gh257_single_a2ui_gate.py`, `tests/test_gh259_a2a_route.py`, `tests/test_gh266_protocol.py`, `tests/test_rtb011_extensions_echo_gaps.py` (only if an existing echo case pinned the old echo; rewrite, do not delete), a new `tests/test_gh271_task_store_contract.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/tasks/` (store implementations for the contract test)
  - Severity: medium
  - Root cause: _echo_extensions predates the per-request A2UI decision; apply_output_modes drops mimeType; docs name only message:send.
  - AC: items 1–6 as ruled. The echo uses the same per-request decision as the build (one helper, not a second compare). Header + `["application/json"]` does not echo A2UI; header + no modes still echoes it. A direct `apply_output_modes` test starting from `mimeType=application/a2ui+json` and modes `["application/json"]` ends with `mimeType=application/json`. `test_not_awaiting_input_stream_is_400` exists. A store contract test runs over every bundled TaskStore implementation. The gate test sends the A2UI header and has an emitting-app control.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/271#issuecomment-6398502964
  - GH: https://github.com/wailuen/a2a-sdk/issues/271
  - Reuses: C-079  # media_type_match / normalize_media_type in agent_sdk/common/media.py (canonical row; C-089 is duplicate-of-C-079).
  - Reuses: C-097  # choice: create the missing accepts_a2ui_mode predicate in agent_sdk/common/media.py (built on C-079 media_type_match) and route both the A2UI build decision and _echo_extensions through it; the C-097 row then names agent_sdk/common/media.py::accepts_a2ui_mode, which now exists.
  - Reuses: C-006  # the echo reads the same per-request decision the build used: A2uiCapabilities.gated, fed by _capabilities(..., a2ui_enabled=record.a2ui_opted_in) at agent_sdk/routes/a2a.py:753; never a recomputed one.
  - Reuses: C-005  # item 5's store contract test is parametrised over TaskStore subclasses (today only agent_sdk/tasks/memory.py InMemoryTaskStore) and driven through Agent(task_store=...) + build_app(), not a hand-written fake (LRN-496).
  - SI: SI-5  # AC: the store contract test over TaskStore.get(task_id, identity) (agent_sdk/tasks/store.py:217) also asserts a second identity gets None for a live task, so the runtime-only fields (a2ui_opted_in, accepted_output_modes) are never readable across identities.

## G5 — auth limiter

- [x] `GH-272` auth: revoke bypasses bearer_limiter; failed-bearer 429 lacks WWW-Authenticate; GH-265 docs/tests stale ‖ group:G5
  - Creates: (modifies `agent_sdk/auth/middleware.py`, `agent_sdk/routes/oauth.py`, `DESIGN.md` (:447 paragraph only), `docs/protocols.md` (rate-limit paragraph only), `tests/test_gh260_rate_limit.py`, `tests/test_gh152_api_key_optout.py`, `workspace/components/README.md` (C-096 row only), `CHANGELOG.md`)
  - Reads: `agent_sdk/app.py` (no edit: the `_a2a_auth_envelope` OAuth 429 branch already copies `exc.headers` into its response), `agent_sdk/common/limits.py`
  - Severity: medium
  - Root cause: GH-265 wired bearer_limiter into the middleware only; its 429 reuses the generic helper; docs were not refreshed.
  - AC: items 1–4 as ruled. A drained bearer_limiter plus a bad bearer gives 429 with Retry-After and `WWW-Authenticate: Bearer error="invalid_token", resource_metadata="<that surface's PRM URL>"` on /v1, /ag-ui/run and /mcp. Revoke with a bad bearer counts and 429s when drained. A bearer-less request is never counted (GH-260 tests stay green unchanged). The token never appears in any 429 body or header.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/272#issuecomment-6398503212
  - GH: https://github.com/wailuen/a2a-sdk/issues/272
  - Reuses: C-099  # the limiter 429's `Bearer error="invalid_token", resource_metadata=...` is built by the registered _prm_challenge(prm_url, invalid_token=True) (agent_sdk/auth/middleware.py:80); no second hand-built challenge string in _rate_limited() or oauth.py.
  - Reuses: C-096  # /oauth/revoke counts in the same runtime.bearer_limiter (AuthRuntime, middleware.py:51/134/157) keyed by the existing _client_key / client_ip (C-027), never request.client.host or a new RateLimiter; the C-096 row lists revoke as a caller.
  - Reuses: C-083  # the revoke 429 raises an HTTPException(429, headers=...) handled by the existing OAuth 429 branch of _a2a_auth_envelope (agent_sdk/app.py:929-947: JSON body + Retry-After + Cache-Control: no-store), not a hand-built JSONResponse in oauth.py; the branch already carries exc.headers, so no app.py edit is needed.
  - SI: SI-5  # AC: missing, invalid and expired bearers still 401 with resource_metadata when the limiter is not spent; a spent limiter never lets an unverified request through (429 is returned before identity, never after); bearer-less requests are never counted (GH-260).
  - SI: SI-2  # AC: the new WWW-Authenticate on the 429, the /v1 -32000 body, the OAuth JSON 429 and the HTML 429 page are fixed text; the presented bearer, its prefix and client_id never appear in header, body or log, tested on /v1, /ag-ui/run, /mcp and /oauth/revoke.

## G6 — MCP session version

- [x] `GH-273` MCP: header MCP-Protocol-Version overrides the session's negotiated version ‖ group:G6
  - Creates: (modifies `agent_sdk/routes/mcp.py`, a new `tests/test_gh273_mcp_session_version.py`, `tests/test_mcp_gh77_absent_version_header.py` (only `test_present_supported_version_header_echoed`: session now inits 2025-03-26, as the old case is the GH-273 400), `docs/protocols.md` (MCP version paragraph only), `CHANGELOG.md`)
  - Reads: GH-200 absent-header tests in `tests/test_mcp_gh77_absent_version_header.py` (all but the one case listed under Creates must stay green unchanged)
  - Severity: medium
  - Root cause: the session record is read only when the header is absent.
  - AC: as ruled. initialize at 2025-06-18 then tools/list with 2025-11-25 gives 400 with the existing unsupported-version body; a matching header works; an absent header works and echoes 2025-06-18. An early-exit 415 on that session echoes 2025-06-18. The mismatch 400 is decided only from the owned-session version returned by the owner-checked _session_alive lookup: an unknown, expired or other-owner Mcp-Session-Id with any valid header (matching or mismatched) still gets the unchanged 404 'session not found', never the mismatch 400 (tested with a second identity's session id and both a matching and a mismatched header). A rejected early-exit request (e.g. the 415) does not refresh the session's last-seen (tested by checking the stored timestamp is unchanged). Version-future tool fields are unchanged (#246). Under Breaking with a Migration line.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/273#issuecomment-6398503498
  - GH: https://github.com/wailuen/a2a-sdk/issues/273
  - Reuses: C-054  # change _session_alive(sessions, session_id, owner, *, touch: bool = True) -> str | None (agent_sdk/routes/mcp.py:313) to return the owned, live session's negotiated version (rec[2]) or None. touch=False never refreshes last-seen and never calls move_to_end, so a rejected request cannot keep a session alive. touch=False MAY still pop an expired record (same as _prune_sessions). It never pops on owner mismatch. mcp_post calls it once with touch=False right after owner = _identity_key(identity) (mcp.py:1109), before the 415 at :1115-1121, and only when Mcp-Session-Id is present and at most 64 chars. The result (session_version) picks the echoed version on the early exits: 415 :1115-1121, 413 :1128, parse error :1134, invalid request :1140, unknown-version 400 :1155. The oversize-id 400 at :1176 always echoes SUPPORTED_PROTOCOL_VERSIONS[0]. The :1183 check calls it with touch=True, and its return value feeds the GH-200 absent-header fallback and the new mismatch 400. The raw sessions.get at :1193 is deleted. mcp_get at :1281 is a changed caller: it keeps its truthiness test, now on str | None. This wave does NOT land the planned _check_mcp_session helper (C-054 stays planned).
  - SI: SI-5  # AC: the session version is read only from a session the caller owns; an unknown, expired or other-owner Mcp-Session-Id gets SUPPORTED_PROTOCOL_VERSIONS[0] on the early exits (415 at mcp.py:1115-1121 and the others before the :1183 owner check), so the echo cannot confirm another owner's session exists or leak its version. Tested with a second identity's session id.
  - SI: SI-5  # the new mismatch 400 sits after the :1183 owner-checked lookup, never next to the unknown-version 400 at :1150-1160, so it cannot act as an existence or version oracle for another identity's session.

## G7 — example, tests, registry

- [x] `GH-274` example resume reads payload.status; vacuous ingress/metadata tests; registry C-085 phantom ‖ group:G7
  - Creates: (modifies `agent_sdk/example/agent.py`, `tests/test_gh235_nested_json_and_resume.py`, `tests/test_gh251_ingress.py`, `workspace/components/README.md` (C-085 row only), `CHANGELOG.md` (also corrects the v0.24.0 deep-metadata claim in place))
  - Reads: `agent_sdk/contrib/action_gate/`, `agent_sdk/credentials/forwarding.py`
  - Severity: medium
  - Root cause: the example kept a status fallback; two tests are rejected for a reason other than the one they guard; a registry row names a missing symbol.
  - AC: items 1–5 as ruled. `payload.status="approved"` with no decision does not publish; `decision="approved"` still does (both tests in `tests/test_gh235_nested_json_and_resume.py`). Each rewritten test fails when the guarded check is removed (state how in the test docstring). C-085 is marked duplicate-of C-040. A CHANGELOG Changed line names `referencing>=0.28.4`.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/274#issuecomment-6398503863
  - GH: https://github.com/wailuen/a2a-sdk/issues/274
  - SI: SI-6, SI-2  # AC: item 3's rewritten X-Agent-Credentials header-too-deep test sends a deep header carrying a unique marker value and asserts the marker never appears in logs or the response, and that agent_sdk/credentials/forwarding.py parse_header stays fail-closed.

---

Archived by hand 2026-10-26 (/sdk-autoloop cycle 3). Wave ended with spurious testsRed/protocolBlocked flags; re-verified: 4772 passed, 11 skipped (CI-only guards and catalog param skips; node console tests pass with CI=true, 274 passed); mypy clean; protocol audit 0 critical/high (mediums in deferred/w068-protocol-medium.md).
