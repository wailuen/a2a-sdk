# w068 — GitHub issues 268–274

Sourced from open issues on wailuen/a2a-sdk, filed 2026-10-25 by /sdk-autoloop cycle 3 from the verified w067 deferred lists (each re-checked at v0.24.0, 45f8358). Rulings were posted on every issue before this wave (links per todo). GH-186 and GH-224 are labelled `deferred`.
Groups run in parallel. Items in one group share files.
Target: 0.25.0. RESERVED data_types are refused at registration (GH-270). A mismatched MCP-Protocol-Version on a known session gets 400 (GH-273). The failed-bearer 429 now carries the invalid_token challenge (GH-272).

Each issue body lists file:line and the fix for every numbered item. Implement every numbered item exactly as described there; where the ruling comment differs from the body, the ruling wins. Do NOT edit `template/` (GH-274 item 1: `template/` has no copy of the example resume code — verified by grep — so nothing lands there). Shared files edited by more than one group (`CHANGELOG.md`, `DESIGN.md`, `docs/protocols.md`, `workspace/components/README.md`) are edited with in-place Edit, each item touching only its own row or section, never a whole-file rewrite. Each item adds its own entry to `CHANGELOG.md` `[Unreleased]` (create the heading once if absent; exactly one `## [Unreleased]` heading, LRN-494, LRN-542), naming every changed `agent_sdk/` file by full repo path (LRN-491, LRN-541). Breaking items go under `### 🔴 Breaking changes` with a Migration line and the ruling URL (LRN-557). Tests run against `build_app()` over the ASGI transport, not hand-written fake clients (LRN-496). Every new client-facing error string is fixed text that never echoes input (SI-2). A test that guards a behaviour must fail when that behaviour is removed (LRN-544, LRN-560).

---

## G1 — testing helpers

- [ ] `GH-268` testing: malformed SSE frames escape as tracebacks; failed card fetch cached; catalog list uncapped ‖ group:G1
  - Creates: (modifies `agent_sdk/testing/chat.py`, `agent_sdk/testing/turns.py`, `workspace/components/README.md` (C-080 row only), `tests/test_gh237_testing_clients.py`, `tests/test_gh234_agui_chat_driver.py`, `docs/testing.md` (only if a documented behaviour changes), `CHANGELOG.md`)
  - Reads: `agent_sdk/testing/mcp.py`
  - Severity: medium
  - Root cause: frame parsing has no shape guard; the card driver memo caches failures; card_catalog_ids has no bounds.
  - AC: items 1–5 of the issue as ruled. One test per bad shape (`data: {bad`, `data: []`, non-object status, non-string text, non-list parts) on the transport it belongs to, each asserting a failed attempt with reason `malformed-stream` and no exception. A 429 card fetch on attempt 1 followed by success on attempt 2 gets the real card. A card with 100 catalog IDs, an empty ID and a 1000-char ID gives at most 32 IDs, none empty, none over 512 chars, standard first.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/268#issuecomment-6398502309
  - GH: https://github.com/wailuen/a2a-sdk/issues/268

## G2 — AG-UI text + console

- [ ] `GH-269` AG-UI unscrubbed TEXT_MESSAGE leaves a dangling START; console fallback lines uncapped ‖ group:G2
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

- [ ] `GH-270` A2UI: RESERVED data_types not refused; TimeSeriesChart keys reassignable; catalog renders Annotated/IntEnum wrong ‖ group:G3
  - Creates: (modifies `agent_sdk/models/content_types.py`, `agent_sdk/a2ui/catalog.py`, `tests/test_gh258_catalog.py`, `tests/test_content_types.py`, a new `tests/test_gh270_wire_pin.py`, `docs/content-types.md` (reserved names paragraph only), `CHANGELOG.md`)
  - Reads: `DESIGN.md`
  - Severity: medium
  - Root cause: the reserved check covers component names only; no assignment guard; ClassVars are re-implemented per class; _annotation_str has no Annotated/IntEnum branches.
  - AC: items 1–6 as ruled. Reserved data_types (and case variants) raise ValueError; a non-snake_case data_type logs one WARNING (logging, not warnings — pytest runs with filterwarnings=error) and registers. `chart.x_key = "ts"` raises. The pin test is written and green BEFORE the _Wire refactor and stays green after (byte-identical `wire()` for every registered type built from its sample or a minimal instance). Round-trip test is two-way and recurses into nested _Wire shapes. `_field_summary(MarketBriefing)` has no `[Annotated]` and the MarketBriefing exclusion is removed. An IntEnum renders `1|2` unquoted. Reserved data_type refusal is under Breaking with a Migration line.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/270#issuecomment-6398502746
  - GH: https://github.com/wailuen/a2a-sdk/issues/270

## G4 — A2A route

- [ ] `GH-271` A2A: A2UI echoed when modes rule it out; mimeType deleted not rewritten; -32004 deviation + stream route undocumented ‖ group:G4
  - Creates: (modifies `agent_sdk/routes/a2a.py`, `agent_sdk/agent/runner.py` (`apply_output_modes` only), `agent_sdk/tasks/store.py` (`TaskStore.get` docstring only), `docs/protocols.md` (-32004 paragraph and not-awaiting-input sentence only), `tests/test_gh257_single_a2ui_gate.py`, `tests/test_gh259_a2a_route.py`, `tests/test_gh266_protocol.py`, `tests/test_rtb011_extensions_echo_gaps.py` (only if an existing echo case pinned the old echo; rewrite, do not delete), `CHANGELOG.md`)
  - Reads: `agent_sdk/common/media.py`, `agent_sdk/tasks/` (store implementations for the contract test)
  - Severity: medium
  - Root cause: _echo_extensions predates the per-request A2UI decision; apply_output_modes drops mimeType; docs name only message:send.
  - AC: items 1–6 as ruled. The echo uses the same per-request decision as the build (one helper, not a second compare). Header + `["application/json"]` does not echo A2UI; header + no modes still echoes it. A direct `apply_output_modes` test starting from `mimeType=application/a2ui+json` and modes `["application/json"]` ends with `mimeType=application/json`. `test_not_awaiting_input_stream_is_400` exists. A store contract test runs over every bundled TaskStore implementation. The gate test sends the A2UI header and has an emitting-app control.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/271#issuecomment-6398502964
  - GH: https://github.com/wailuen/a2a-sdk/issues/271
  - Reuses: C-089  # media_type_match.

## G5 — auth limiter

- [ ] `GH-272` auth: revoke bypasses bearer_limiter; failed-bearer 429 lacks WWW-Authenticate; GH-265 docs/tests stale ‖ group:G5
  - Creates: (modifies `agent_sdk/auth/middleware.py`, `agent_sdk/routes/oauth.py`, `DESIGN.md` (:447 paragraph only), `docs/protocols.md` (rate-limit paragraph only), `tests/test_gh260_rate_limit.py`, `tests/test_gh152_api_key_optout.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/app.py`, `agent_sdk/common/limits.py`
  - Severity: medium
  - Root cause: GH-265 wired bearer_limiter into the middleware only; its 429 reuses the generic helper; docs were not refreshed.
  - AC: items 1–4 as ruled. A drained bearer_limiter plus a bad bearer gives 429 with Retry-After and `WWW-Authenticate: Bearer error="invalid_token", resource_metadata="<that surface's PRM URL>"` on /v1, /ag-ui/run and /mcp. Revoke with a bad bearer counts and 429s when drained. A bearer-less request is never counted (GH-260 tests stay green unchanged). The token never appears in any 429 body or header.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/272#issuecomment-6398503212
  - GH: https://github.com/wailuen/a2a-sdk/issues/272

## G6 — MCP session version

- [ ] `GH-273` MCP: header MCP-Protocol-Version overrides the session's negotiated version ‖ group:G6
  - Creates: (modifies `agent_sdk/routes/mcp.py`, a new `tests/test_gh273_mcp_session_version.py`, `docs/protocols.md` (MCP version paragraph only), `CHANGELOG.md`)
  - Reads: `tests/test_mcp_gh77_absent_version_header.py` (GH-200 absent-header tests; must stay green unchanged)
  - Severity: medium
  - Root cause: the session record is read only when the header is absent.
  - AC: as ruled. initialize at 2025-06-18 then tools/list with 2025-11-25 gives 400 with the existing unsupported-version body; a matching header works; an absent header works and echoes 2025-06-18. An early-exit 415 on that session echoes 2025-06-18. Version-future tool fields are unchanged (#246). Under Breaking with a Migration line.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/273#issuecomment-6398503498
  - GH: https://github.com/wailuen/a2a-sdk/issues/273

## G7 — example, tests, registry

- [ ] `GH-274` example resume reads payload.status; vacuous ingress/metadata tests; registry C-085 phantom ‖ group:G7
  - Creates: (modifies `agent_sdk/example/agent.py`, `tests/test_gh235_nested_json_and_resume.py`, `tests/test_gh251_ingress.py`, `workspace/components/README.md` (C-085 row only), `CHANGELOG.md` (also corrects the v0.24.0 deep-metadata claim in place), the example's test file under `tests/`)
  - Reads: `agent_sdk/contrib/action_gate/`, `agent_sdk/credentials/forwarding.py`
  - Severity: medium
  - Root cause: the example kept a status fallback; two tests are rejected for a reason other than the one they guard; a registry row names a missing symbol.
  - AC: items 1–5 as ruled. `payload.status="approved"` with no decision does not publish; `decision="approved"` still does. Each rewritten test fails when the guarded check is removed (state how in the test docstring). C-085 is marked duplicate-of C-040. A CHANGELOG Changed line names `referencing>=0.28.4`.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/274#issuecomment-6398503863
  - GH: https://github.com/wailuen/a2a-sdk/issues/274
