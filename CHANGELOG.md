# Changelog

All notable changes to `agent-sdk`. SemVer applies to the stable core
(DESIGN.md §4.0); provisional surfaces (`agent_sdk.testing`, console
internals, `contrib/`) may change in minors with notice here.

## [Unreleased]

### 🔴 Breaking changes
- GH-273: `POST /mcp` now answers 400 `unsupported MCP-Protocol-Version` when a request on an owned, live session carries an `MCP-Protocol-Version` that differs from the version that session negotiated at `initialize` (it was accepted before). An unknown, expired or other-owner `Mcp-Session-Id` still gets 404 `session not found`. Early exits (415, 413, parse error, invalid request, unknown-version 400) echo the owned session's negotiated version, else the newest; they no longer refresh the session's last-seen. `_session_alive` (`agent_sdk/routes/mcp.py`) gains keyword-only `touch=True` and returns the session version or None (was bool). Ruling: https://github.com/wailuen/a2a-sdk/issues/273#issuecomment-6398503498. **Migration:** send the same `MCP-Protocol-Version` on every request of a session that you negotiated at `initialize`, or omit the header. Tests: `tests/test_gh273_mcp_session_version.py`; `tests/test_mcp_gh77_absent_version_header.py` (`test_present_supported_version_header_echoed` now inits the session at 2025-03-26, because the old case, session 2025-06-18 with header 2025-03-26, is now the GH-273 400). Docs: `docs/protocols.md`.
- GH-270 (item 1): `register_content_type` now raises `ValueError` for a `data_type` that matches a RESERVED component name ignoring case: `trade_activity`, `company_info`, `deal_list`, `investor_profile` and variants such as `TRADE_ACTIVITY` or `TradeActivity` (`agent_sdk/models/content_types.py`). The names are derived from `RESERVED_COMPONENTS`, so a new reserved name is refused automatically. A `data_type` that is not snake_case is only logged as a warning (`logging`, once per class) and still registers. Ruling: https://github.com/wailuen/a2a-sdk/issues/270#issuecomment-6398502746. **Migration:** rename the `data_type` of any domain card that used a reserved one.
- GH-270 (item 2): `TimeSeriesChart.x_key` and `y_key` are frozen fields; assigning to them (`chart.x_key = "ts"`) raises `ValidationError`. (`agent_sdk/models/content_types.py`). **Migration:** stop assigning `x_key`/`y_key`; build a new `TimeSeriesChart` instead. Ruling: https://github.com/wailuen/a2a-sdk/issues/270#issuecomment-6398502746.

### Changed
- GH-274: `referencing>=0.28.4` is now a declared dependency (`pyproject.toml`); it was already pulled in by `jsonschema`. `agent_sdk/example/agent.py` `publish_note` resumes on `payload.decision` only; a DataPart with only `status: "approved"` no longer publishes, and a resume with status `cancelled` never publishes even with `payload.decision: "approved"` (it uses `contrib.action_gate.parse_decision`, reject-wins) (example agent only, not the stable core). Tests: `tests/test_gh235_nested_json_and_resume.py`, `tests/test_gh251_ingress.py`. Registry: C-085 marked duplicate of C-040. Ruling: https://github.com/wailuen/a2a-sdk/issues/274#issuecomment-6398503863
- GH-272: a 429 from the failed-bearer limiter on `/v1`, `/ag-ui` and `/mcp` now also carries `WWW-Authenticate: Bearer error="invalid_token", resource_metadata="<that surface's PRM URL>"` next to `Retry-After`; the cap and setting are unchanged and bearer-less requests are still never counted. `POST /oauth/revoke` with a bad bearer now counts in `bearer_limiter` and answers the OAuth JSON 429 when it is spent. Docstrings and DESIGN.md / docs/protocols.md rate-limit text refreshed; GH-265 Migration note: the four browser routes answer 429 with the branded HTML page. Files: `agent_sdk/auth/middleware.py`, `agent_sdk/routes/oauth.py`. Tests: `tests/test_gh260_rate_limit.py`, `tests/test_gh152_api_key_optout.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/272#issuecomment-6398503212
- GH-271: `X-A2A-Extensions` on `message:send` and `message:stream` now lists the A2UI extension only when the per-request A2UI decision is true (app gate, header opt-in and `acceptedOutputModes` accepting `application/a2ui+json`); the header with `["application/json"]` no longer echoes A2UI, and the header with no modes still does. Files: `agent_sdk/routes/a2a.py` (`_echo_extensions`, `_a2ui_decision`), `agent_sdk/agent/runner.py` (`_build_capabilities`), `agent_sdk/common/media.py`, `workspace/components/README.md` (C-097 row). `_echo_extensions` gains keyword-only `a2ui_active` (default `True`). New `accepts_a2ui_mode` in `agent_sdk/common/media.py` (C-097) is the one compare for the build and the echo. Ruling: https://github.com/wailuen/a2a-sdk/issues/271#issuecomment-6398502964
- GH-270 (item 3): the `wire_keeps_null` / `wire_omitted` rule now lives in one serializer on `_Wire` (`agent_sdk/models/content_types.py`); the per-class copies in `TimeSeriesDataPoint`, `ColumnDef` and `DocumentItem` are gone (`DocumentItem` keeps a `_wire_reshape` hook for its alias fill and transcript skip). `wire()` output is byte-identical, pinned for every registered type in `tests/test_gh270_wire_pin.py`. A `wire_omitted` field that holds `True` is kept (that is how `ColumnDef.is_id` works). The serializer calls a per-class `_wire_reshape(self, data, info) -> bool` hook. A subclass `_wire_reshape` with another signature is skipped (the nearest valid one up the class chain runs) and logs a warning; a subclass that has non-empty `wire_keeps_null`/`wire_omitted` and also defines its own `model_serializer` logs a warning, because that serializer replaces the shared rule (as it already did in v0.24.0). Neither case raises, so no subclass that built in v0.24.0 fails now. Tests: `tests/test_gh270_reserved_hooks.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/270#issuecomment-6398502746.
- GH-270 (items 5-6): `agent_sdk/a2ui/catalog.py::_annotation_str` (new helper `_values_str`) unwraps `Annotated` (no more `[Annotated]` in `MarketBriefing`'s summary) and renders enum and `Literal` values as JSON when they are not all strings (`1|2`, `true|false`). Tests: `tests/test_gh258_catalog.py`, `tests/_compact_schema.py` (`undeclared_paths`, the reverse nested walk behind the two-way round-trip test).

### Fixed
- GH-269: AG-UI `TEXT_MESSAGE_CONTENT.delta` now passes through `scrub_unencodable` (lone surrogates become U+FFFD), so the run finishes normally. When a frame in a batch cannot be serialized after `TEXT_MESSAGE_START`, `_emit` now writes the matching `TEXT_MESSAGE_END` before the single `RUN_ERROR` (no dangling START). The console `fallbackNode` clips the text to `MAX_PROSE` first, then shows at most `MAX_ROWS` lines plus a "N more" note. Ruling: https://github.com/wailuen/a2a-sdk/issues/269#issuecomment-6398502514. Changed: `agent_sdk/routes/ag_ui.py`, `agent_sdk/console/static/a2ui.js`. Tests: `tests/test_gh269_agui_text_scrub.py`, `tests/test_gh239_console_caps.py` (the line-clip test no longer expects text past `MAX_PROSE`).
- GH-268 (provisional `agent_sdk.testing`): a bad AG-UI or A2A stream frame (invalid JSON, a non-object frame, a non-object `status`, a non-string `text` or `delta`, a non-list `parts`) now ends the attempt as a failed turn with reason `malformed-stream` and fixed text; no exception escapes `run_turn` or `ChatDriver.agui_turn`, and the AG-UI message list rolls back. The turn helper caches its card driver only after a successful card fetch; a 429 or 5xx card fetch is a failed attempt (`http-429` for 429) and is retried. `card_catalog_ids` drops empty and over-512-character IDs, caps the list at 32 and puts the standard catalog first. Registry rows C-055 and C-080 updated. Ruling: https://github.com/wailuen/a2a-sdk/issues/268#issuecomment-6398502309. Files: `agent_sdk/testing/chat.py`, `agent_sdk/testing/turns.py`. Tests: `tests/test_gh237_testing_clients.py`, `tests/test_gh234_agui_chat_driver.py`.
- GH-271: `apply_output_modes` rewrites artifact `metadata.mimeType` to the shared media type of the kept parts (for example `application/json`) and deletes it only when the kept parts are mixed (was: deleted when no kept part had that mimeType). Files: `agent_sdk/agent/runner.py` (`apply_output_modes`), `agent_sdk/routes/a2a.py` (the three GH-266 comment sites), `agent_sdk/tasks/store.py` (`TaskStore.get` docstring), `docs/protocols.md`. `docs/protocols.md` states the -32004 deviation (A2A v0.3.0 says 501, the SDK answers 400) and names `message:send` or `message:stream` for the not-awaiting-input case; `TaskStore.get` documents that a live task keeps `a2ui_opted_in` and `accepted_output_modes`. Tests: `tests/test_gh271_task_store_contract.py`, `tests/test_gh259_a2a_route.py`, `tests/test_gh266_protocol.py`, `tests/test_gh257_single_a2ui_gate.py`.

## [0.24.0] — 2026-10-25

### 🔴 Breaking changes
- GH-265: an invalid, expired or refused bearer now gets `WWW-Authenticate: Bearer error="invalid_token", resource_metadata="..."` (was the bare `Bearer resource_metadata="..."`); a missing bearer keeps the bare challenge. Failed bearers count in a new per-IP `AuthRuntime.bearer_limiter` (same `AGENT_SDK_UNAUTH_RATE_LIMIT`), separate from `unauth_limiter` (OAuth endpoints). The four browser OAuth routes now answer 429 with the branded HTML page; Ruling: https://github.com/wailuen/a2a-sdk/issues/265#issuecomment-6395232689. **Migration:** clients that matched the exact bare challenge string must accept the `error="invalid_token"` form; the four browser OAuth routes answer 429 with the branded HTML page (not JSON). Changed: `agent_sdk/auth/middleware.py`, `agent_sdk/routes/oauth.py`, `agent_sdk/app.py`, `DESIGN.md`, `docs/protocols.md`. Tests: `tests/test_gh260_rate_limit.py`, `tests/test_gh152_api_key_optout.py`.
- GH-261: the `a2ui_enabled` parameters of `_capabilities` (`agent_sdk/routes/a2a.py`, `agent_sdk/routes/ag_ui.py`), `_config_error` and `_supported_modes` are keyword-only and default to `False` (was `True`); a call with no argument now fails closed. Ruling: https://github.com/wailuen/a2a-sdk/issues/261#issuecomment-6395231865. **Migration:** pass `a2ui_enabled=True` explicitly.
- GH-261 (new rejections): on an A2UI-enabled app, a fresh request with `acceptedOutputModes: ["application/a2ui+json"]` and no `X-A2A-Extensions` header was accepted in v0.23.0 and now gets HTTP 415 / -32005; a resume that sends the header plus A2UI modes on a task started without the header now also gets 415 / -32005. Ruling: https://github.com/wailuen/a2a-sdk/issues/261#issuecomment-6395231865. **Migration:** send `X-A2A-Extensions` with the A2UI URI on the first message of a task that asks for `application/a2ui+json`; a resume cannot newly opt in.
- GH-266: `-32004` now answers HTTP 400 (was 501) where the message is a wrong state: terminal-task resume on `POST /v1/message:send` and `:stream`, and `message:send` to a task that is not awaiting input (`agent_sdk/routes/a2a.py`). Unsupported operations and the colon-id guard on `GET /v1/tasks/{id}:cancel` keep 501; a wrong verb stays 405. `a2a_error` gains keyword-only `status`; `agent_sdk/common/wire_errors.py` maps `-32600` to 400 and `-32601` to 404. Ruling: https://github.com/wailuen/a2a-sdk/issues/266#issuecomment-6395232882. `agent_sdk/models/errors.py` carries the GH-266 comment. Harness: `harness/skills/acceptance/SKILL.md` and `.claude/skills/acceptance/SKILL.md` line 311 now say 400 / -32004; `template/.claude/skills/acceptance/SKILL.md` is updated in wailuen/a2a-agent-template (0c6ce94). **Migration:** clients that keyed on 501 for terminal-task re-addressing must key on `error.code == -32004` (or accept 400).
- GH-262 (item 4): `TimeSeriesChart.x_key` and `y_key` are typed `Literal["date"]` and `Literal["value"]` (defaults unchanged), and the rejection message now names the allowed value (`TimeSeriesChart y_key must be fixed to 'value'`). This updates the GH-258 entry below, which showed the older message without the allowed value. Ruling: https://github.com/wailuen/a2a-sdk/issues/262#issuecomment-6395232063. Subclasses of `TimeSeriesChart` inherit the `Literal` type and the check; a subclass with its own data-point keys must map them to `date`/`value`. The two messages are `TimeSeriesChart x_key must be fixed to 'date'` and `TimeSeriesChart y_key must be fixed to 'value'`. **Migration:** drop custom `x_key`/`y_key` arguments; type checkers now flag any other value.
- GH-262 (item 1): the GH-262 ruling supersedes the GH-171 behaviour. A required nullable field (`a: str | None` with no default) is now shown as optional (`a?`) in the catalog prompt, because `wire()` drops it when `None`. Fields named in a model's `wire_keeps_null` (only `TimeSeriesDataPoint.value`) stay required. **Migration:** none for senders; prompt text only. Ruling: https://github.com/wailuen/a2a-sdk/issues/262#issuecomment-6395232063.
- GH-264: `McpClient.initialize` (`agent_sdk/testing/mcp.py`, provisional testing surface) now raises `McpError` when the initialize result has no `protocolVersion` (fixed text, the response body is not echoed); it used to fall back silently. Ruling: https://github.com/wailuen/a2a-sdk/issues/264#issuecomment-6395232473. **Migration:** make the server return a supported `protocolVersion` in the initialize result.

### Added
- GH-265: `AuthRuntime.bearer_limiter` (`agent_sdk/auth/middleware.py`), the per-IP limiter for failed bearers; `BROWSER_OAUTH_ROUTES` and `RATE_LIMITED_PAGE_TEXT` in `agent_sdk/routes/oauth.py` (the four browser OAuth routes and the text of their branded 429 page); and the `invalid_token` keyword on `_prm_challenge` / `_unauthorized` (`agent_sdk/auth/middleware.py`). Ruling: https://github.com/wailuen/a2a-sdk/issues/265#issuecomment-6395232689.
- GH-262: `wire_omitted` and `wire_keeps_null` `ClassVar[frozenset[str]]` on `_Wire`/`ContentModel` (`agent_sdk/models/content_types.py`): one shared omission rule read by the serializers and by the catalog's `_wire_required` (`agent_sdk/a2ui/catalog.py`, new optional `model` and `name` arguments). Declared on `ColumnDef` (`is_id`), `DocumentItem` (`web_url`, `last_modified`) and `TimeSeriesDataPoint` (`value`). Tests: `tests/test_gh258_catalog.py`.
- GH-264 (provisional `agent_sdk.testing`): `ChatDriver(card=...)` keyword and new function `agent_sdk.testing.chat.fetch_agent_card()` (`agent_sdk/testing/chat.py`).
- GH-267: `loads_strict` (`agent_sdk/common/json_strict.py`) gains a keyword-only `reject_duplicate_keys=False`; when true a repeated object key at any depth raises `json.JSONDecodeError("duplicate key")` (fixed text, never the key or a value). Tests: `tests/test_gh251_ingress.py`.

### Fixed
- GH-265: API OAuth 429 responses add `Cache-Control: no-store`; OAuth token responses add `Pragma: no-cache` (`agent_sdk/routes/oauth.py`).
- GH-267: w066 leftovers. `credentials/forwarding.py::parse_header` now parses `X-Agent-Credentials` once with it (was `loads_strict` plus a second `json.loads`); it still returns `{}` on every error and logs nothing. `routes/mcp.py` drops its `_is_json_content_type` wrapper and calls `is_json_content_type` like the other routes. Stale comments fixed in `routes/ag_ui.py` (body cap) and `contrib/action_gate/gate.py` (`parse_decision` A2A bullet: a DataPart resume arrives as a dict). `agent_sdk/example/agent.py` teaches `payload.decision` (not `status`) in the `publish_note` response schema. Registry: C-006, C-040, C-079 rows and the C-040 detail updated; C-089 and C-090 marked duplicate of C-079 and C-086. Files: `agent_sdk/common/json_strict.py`, `agent_sdk/credentials/forwarding.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/routes/ag_ui.py`, `agent_sdk/contrib/action_gate/gate.py`, `agent_sdk/example/agent.py`. Tests (`tests/test_gh235_nested_json_and_resume.py`, `tests/test_gh251_ingress.py`): the deep-metadata test asserted `-32700` / `nesting too deep` but its body had no `kind: message` or part `kind`, so it was rejected for that reason, not for depth (corrected in GH-274: the body is now valid and a shallow-metadata control succeeds); the header-too-deep test used a non-object source value that failed the shape check first (GH-274 now spies on `NestingTooDeep`); the AG-UI resume status test also rejects `"approved"` and `"rejected"`. Ruling: https://github.com/wailuen/a2a-sdk/issues/267#issuecomment-6395233057
- GH-263: console follow-ups to GH-254/255 (console-internal, provisional). `agent_sdk/console/static/chat.js`: a CHUNK role is recorded only from the frame's own `messageId`, never the id minted for an id-less chunk (that id only keys the buffer), matching `ChatDriver`. The A2A path reads `threadAtSend` and the abort signal before its first await and drops every frame of a run on a replaced thread, as the AG-UI path does. `send()` while busy shows the fixed "busy" note and keeps the typed text. `agent_sdk/console/static/retry.js`: `postWithRetry` takes an optional `signal` (new exported `abortableSleep(ms, signal)`), so Reset wakes the back-off wait and the call returns `null` with no further POST; an aborted request is already reported as HTTP 499 and never retried. `agent_sdk/console/static/a2ui.js`: renderer notes, fallback reasons and fallback lines clip wire values with `clip()`; inline label and `compactText` truncations use `clip()`; the time-series cap uses `capRows`; closed-surface tombstones are bounded (new export `MAX_TOMBSTONES` = 200, oldest forgotten first); a trend direction is looked up with `Object.hasOwn`. DESIGN.md §7.2 and the C-074 and C-081 rows are updated. Tests: `tests/test_gh234_agui_chat_driver.py` (including a thread flip after the 2nd frame), `tests/test_gh239_console_caps.py`, `tests/test_gh191_console_retry_policy.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/263#issuecomment-6395232277
- GH-261: the A2UI choice is made once per artifact, before `build_artifact`: app gate AND header opt-in AND (`acceptedOutputModes` absent or accepting `application/a2ui+json`). Header opt-in with `["application/json"]` now completes with a JSON DataPart instead of failing with -32005. The new 415 rejections are listed under Breaking changes. A resume checks its modes against the opt-in captured at task start (`TaskRecord.a2ui_opted_in`); a resume that sends modes replaces the stored ones through `ResumeEnvelope.accepted_output_modes` (the worker applies them to its live record). `metadata.mimeType` on the artifact is dropped when its A2UI part is filtered out. Changed: `agent_sdk/routes/a2a.py`, `agent_sdk/auth/context.py`, `agent_sdk/agent/runner.py` (`_build_capabilities`, `apply_output_modes` mimeType rewrite), `agent_sdk/routes/agent_card.py`, `agent_sdk/app.py`, `agent_sdk/tasks/store.py` (`TaskRecord.a2ui_opted_in`, docstring).
- GH-262: the catalog's 250-character budget now counts the braces and the ellipsis; integer `Literal` values are no longer quoted; the EntityList and UserProfile compact schemas carry notes (SDK extensions `title`/`showing`; partial nested keys). DESIGN.md records `DocumentItem.modified_by` and the EntityList extras as SDK extensions (no wire change). The `required` argument of `_annotation_str` stays (existing tests patch that signature).

### Changed
- GH-261: the module-level helper `agent_card.a2ui_enabled` is renamed `compute_a2ui_enabled` (`app.state.a2ui_enabled` and the `build_agent_card(a2ui_enabled=...)` keyword keep their names).
- GH-266: `docs/protocols.md` MCP section lists 2025-11-25, 2025-06-18 and 2025-03-26, the newest-version fallback, the title gate and the void-result deviation.
- GH-264 (provisional `agent_sdk.testing`; files: `agent_sdk/testing/turns.py`, `agent_sdk/testing/chat.py`, `agent_sdk/testing/mcp.py`, `docs/testing.md`, `tests/test_gh237_testing_clients.py`): `turns.py` fetches the agent card once, inside the slot limiter and the `asyncio.wait_for` budget of the turn, and gives its `supportedCatalogIds` to `ChatDriver` through public constructor parameters (new keyword `card`, existing `extra_catalogs`); catalogs are merged with the standard catalog and de-duplicated. The AG-UI path declares the same catalogs. A message-kind stream clears the stored task and state files. Also: on the A2A stream, a frame that is not valid JSON or not a JSON object fails the attempt (`malformed-stream`) instead of raising, `ChatDriver.a2a_turn` raises `ValueError` for a non-object card, and a non-`$ref` validator error in `run_gate` is no longer reported as an unresolvable `$ref`. New helper `agent_sdk.testing.chat.fetch_agent_card`. Ruling: https://github.com/wailuen/a2a-sdk/issues/264#issuecomment-6395232473

## [0.23.0] — 2026-10-25

### 🔴 Breaking changes
- GH-258: `TimeSeriesChart` now rejects any `x_key` other than `"date"` and any `y_key` other than `"value"` with a fixed `ValidationError` message (`TimeSeriesChart x_key must be fixed`); the data points cannot carry other keys, so such a chart never rendered. The A2UI prompt schema shows `"x_key":"date","y_key":"value"`. Ruling: https://github.com/wailuen/a2a-sdk/issues/258#issuecomment-6393088394. **Migration:** drop custom `x_key`/`y_key` arguments.
- GH-251 (item 4): the exported stable-core helper `safe_block_text` (`agent_sdk/common/redact.py`) now drops Unicode format characters (Cf), so its output changes for text that holds them, including U+200C (ZWNJ) and U+200D (ZWJ): Persian words lose their ZWNJ and ZWJ emoji family sequences split into separate emoji. Ruling: https://github.com/wailuen/a2a-sdk/issues/251#issuecomment-6393088850. **Migration:** none needed for text without format characters; if you need ZWJ/ZWNJ kept in MarketBriefing prose, ask for a ruling that keeps U+200C/U+200D in block text (as GH-250 handled the line helpers).
- GH-251: `POST /ag-ui/run` now answers 415 for `Content-Type: application/json-seq` (`agent_sdk/routes/ag_ui.py`), and `X-Agent-Credentials` with a duplicate key is refused, so `parse_header` (`agent_sdk/credentials/forwarding.py`) returns `{}` and every forwarded credential is dropped for that request. Ruling: https://github.com/wailuen/a2a-sdk/issues/251#issuecomment-6393088850. **Migration:** send `application/json` (or a `+json` type) and a header with no repeated keys.
- GH-257: one A2UI gate. `a2ui_enabled(allowed_components, emits)` (in `agent_sdk/routes/agent_card.py`) is computed once in `build_app()` and stored as `app.state.a2ui_enabled`; it now drives the card's A2UI extension and `application/a2ui+json` output mode, both `_capabilities` functions (`agent_sdk/routes/a2a.py` and `agent_sdk/routes/ag_ui.py`, new keyword `a2ui_enabled`), the accepted output modes (`media_type_match` in `agent_sdk/common/media.py` takes the per-app supported set; `_SUPPORTED_MODES` and `_NORMALIZED_MODES` are gone) and artifact building. `build_agent_card` gains keyword-only `a2ui_enabled=False` and `emits=None`. The console sends the A2UI header and `a2uiClientCapabilities` on A2A only when the card declares the extension. Changed: `agent_sdk/app.py`, `agent_sdk/agent/runner.py`, `agent_sdk/routes/agent_card.py`, `agent_sdk/routes/a2a.py`, `agent_sdk/routes/ag_ui.py`, `agent_sdk/console/static/chat.js`. Tests: `tests/test_gh257_single_a2ui_gate.py`, `tests/test_gh225_multi_type_emits.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/257#issuecomment-6393088260. **Migration:** an agent with no tool that emits an A2UI type no longer serves A2UI at all: a header opt-in or `forwardedProps.a2uiClientCapabilities` is ignored (TextPart/JSON fallback) and `acceptedOutputModes: ["application/a2ui+json"]` alone returns -32005 on `/v1/message:send` and `:stream`. Declare `emits=` on at least one tool to keep A2UI; callers of `build_agent_card` that expect the A2UI extension must pass `a2ui_enabled=True`.
- GH-256: provisional testing surface, stricter. `McpClient.initialize` (`agent_sdk/testing/mcp.py`) now raises `McpError` for a negotiated protocol version outside `SUPPORTED_PROTOCOL_VERSIONS`, and an empty-string version, which used to fall back to the default, now raises too; `ChatDriver` (`agent_sdk/testing/chat.py`) no longer sends the A2UI header or `a2uiClientCapabilities` to an agent whose card does not list the A2UI extension. Ruling: https://github.com/wailuen/a2a-sdk/issues/256#issuecomment-6393088084. **Migration:** make the server return a supported `protocolVersion` (an empty one is no longer accepted); declare the A2UI extension on the agent card (give a tool an A2UI `emits=`) if a test needs A2UI replies.
- GH-259: `acceptedOutputModes` is now applied to artifacts (`agent_sdk/agent/runner.py`, `agent_sdk/routes/a2a.py`): parts are filtered to the accepted types (TextPart `text/plain`, DataPart its `metadata.mimeType` or `application/json`, FilePart its `mimeType`), so a DataPart is dropped for `["text/plain"]`; if none remain and `text/plain` is accepted one TextPart fallback is kept, otherwise the task fails with `-32005`, which can happen after the tools have run. Ruling: https://github.com/wailuen/a2a-sdk/issues/259#issuecomment-6393088522. **Migration:** list every output type the client can read in `acceptedOutputModes`, or omit the field.

### Added
- GH-256: `ChatDriver.a2ui_client_activation()` and `agent_sdk.testing.chat.card_catalog_ids()` in `agent_sdk/testing/chat.py` (provisional testing surface). Ruling: https://github.com/wailuen/a2a-sdk/issues/256#issuecomment-6393088084
- GH-255: `agent_sdk/console/static/a2ui.js` exports `clip(value, max = MAX_TEXT)`, the one string-clipping helper for dedicated renderers (console-internal, provisional).
- GH-255: `agent_sdk/console/static/a2ui.js` exports `capRows(items, limit = MAX_ROWS)` and `moreNote(extra, noun)`, now parameterised (console-internal, provisional).
- GH-255: `agent_sdk/console/static/a2ui.js` exports the caps `MAX_TEXT` (256), `MAX_LONG_TEXT` (2000), `MAX_PROSE` (20000), `MAX_RAW` (50000), `MAX_SECTIONS` (10) and `MAX_CELLS` (1000) (console-internal, provisional).
- GH-254: `agent_sdk/console/static/api.js` `postSse(path, body, extraHeaders, signal)` takes an optional fourth `signal` argument (an `AbortSignal`) so Reset can abort an in-flight request (console-internal, provisional).

### Changed
- GH-260: an `/oauth/*` 429 now has the body `{"error":"temporarily_unavailable","error_description":"rate limit exceeded"}` plus `Retry-After` (`agent_sdk/app.py`, `agent_sdk/auth/middleware.py`); other 429s keep their shape. Ruling: https://github.com/wailuen/a2a-sdk/issues/260#issuecomment-6393088715. **Migration:** read `error` and `Retry-After` on an OAuth 429 instead of the old body shape.

### Fixed
- GH-254: console chat (`agent_sdk/console/static/chat.js`) matches `ChatDriver` on AG-UI history: a CHUNK role is recorded for an id only before any text for that id was buffered (CONTENT or CHUNK), the fold skips empty text and mints an id for an id-less buffer, and a Reset drops the A2A `contextId` write-back of a run started before it. Reset aborts the in-flight request (`postSse` in `agent_sdk/console/static/api.js` gains an optional fourth `signal` argument), output from a run on a replaced thread is dropped, and a Resume click while a run is busy shows a fixed "busy" note. Ruling: https://github.com/wailuen/a2a-sdk/issues/254#issuecomment-6393089186. Tests: `tests/test_gh234_agui_chat_driver.py`.
- GH-258: A2UI catalog prompt text. A field is shown as required when `wire()` always writes it (no default, or a non-None default), no longer from the serialization schema; docstrings updated; nested expansion respects the 250-character budget; `dict[K, V]` renders `{key: V}`; enum and `Literal` fields list their values; `supported_catalogs(emits=None)` adds the Standard Profile only when a Standard type passes the filter; `emits` is typed `Sequence[type]`. DESIGN.md records EntityList `title`/`showing` as SDK extensions receivers ignore. Changed: `agent_sdk/a2ui/catalog.py`, `agent_sdk/models/content_types.py`, DESIGN.md. Tests: `tests/test_gh258_catalog.py`, `tests/test_gh177_document_contract_keys.py`, `tests/test_gh179_conformance_drift.py`, `tests/test_rt001_strict_required_nullable_output.py`, `tests/test_rt003_fund_performance_kpi_parity.py`, `tests/test_rt005_fund_performance_title.py`.
- GH-251: one JSON media-type check. `agent_sdk/common/body.py::is_json_content_type` (case-insensitive, `application/json` or a `+json` type, parameters ignored) now serves `/v1/message:send`, `/ag-ui/run`, `/mcp` and `/mcp/messages`; the A2A and MCP routes now accept `application/problem+json`. A missing header still passes. AG-UI `_tool_json` catches any exception, logs only its type, and replaces a NaN or infinity per value with null instead of dropping the whole dict. `parse_header` still returns `{}` (no exception, no log) for a refused header, which is the existing fixed behaviour. Stale comments fixed. Changed: `agent_sdk/common/body.py`, `agent_sdk/routes/ag_ui.py`, `agent_sdk/routes/a2a.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/common/redact.py` (`safe_block_text`), `agent_sdk/credentials/forwarding.py` (`parse_header`). Tests: `tests/test_gh251_ingress.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/251#issuecomment-6393088850
- GH-252: docs and records match v0.22.0. No doc or docstring teaches `status="approved"` on AG-UI (`agent_sdk/contrib/action_gate/__init__.py`, `agent_sdk/contrib/action_gate/gate.py`, `docs/protocols.md`); the `agent_sdk/common/admission.py` docstring names GET and POST `:subscribe`; DESIGN.md §5.3 states the resume rules; the `:subscribe` docs name GET and POST; the DESIGN.md ChildList claim now says template expansion is out of scope; `jsonschema` is listed once (core) in `pyproject.toml` and `uv.lock` is regenerated. Tests: `tests/test_gh235_nested_json_and_resume.py` (`"status": null` published as `None`; non-serializable result content is the fixed fallback).
- GH-256: `agent_sdk/testing/turns.py` resume sends both `taskId` and `contextId`; it passes the card's A2UI `supportedCatalogIds` into `ChatDriver(extra_catalogs=...)`; it handles `kind=="message"` stream events and stops reading at `final`. `agent_sdk/testing/chat.py` gains `ChatDriver.a2ui_client_activation()` and the module function `card_catalog_ids()` (both provisional); `ChatDriver` sends the A2UI header and capabilities only when the card advertises the extension; a non-object card counts as not advertised and a card-fetch failure is logged by exception type only. `agent_sdk/testing/mcp.py`: `McpClient.initialize` raises `McpError` for a negotiated version outside `SUPPORTED_PROTOCOL_VERSIONS`, and the gate reports an unresolvable `$ref` in an `outputSchema` as a failure. `additionalInterfaces` stays a documented non-goal. `harness/skills/acceptance/SKILL.md` and `.claude/skills/acceptance/SKILL.md` (byte-identical) and the template peer `template/.claude/skills/acceptance/SKILL.md` (wailuen/a2a-agent-template 4ce9597) list `[--skills-tool]` and the structuredContent gate stop. Docs: `docs/testing.md`. Tests: `tests/test_gh237_testing_clients.py` (A2UI activation and resume run against `build_app()` over ASGI). Ruling: https://github.com/wailuen/a2a-sdk/issues/256#issuecomment-6393088084
- GH-255: console A2UI renderer (`agent_sdk/console/static/a2ui.js`) clips every string a dedicated renderer prints with one `clip(text, max)` helper (names 256 chars, previews and subtitles 2,000, prose 20,000, generic raw JSON 50,000). `capRows(items, limit)` and `moreNote(extra, noun)` are parameterised and exported, as is `clip`; new console-internal (provisional) exports `MAX_TEXT` (256), `MAX_LONG_TEXT` (2000), `MAX_PROSE` (20000), `MAX_RAW` (50000), `MAX_SECTIONS` (10) and `MAX_CELLS` (1000); `moreColumnsNote` is removed (columns use `moreNote(n, "columns")`). MultiCategoryChart survives a null period, sums totals over the shown categories only (absolute values), labels its notes ("N more periods" / "N more categories"), and caps categories so periods x categories stays at or below 1,000. Time-series keeps the newest `MAX_ROWS` points. The generic renderer shows at most 10 array sections. A `createSurface` after a `deleteSurface` for the same id is now rejected (the closed entry stays as a tombstone). DESIGN.md §7.1 lists the caps; C-059 row updated. Tests: `tests/test_gh239_console_caps.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/255#issuecomment-6393089342
- GH-259: A2A route. Every failed task now has `status.message` (role `agent`, one TextPart with the same safe text as `status.error.message`), built once in `set_task_status`; `status.error` stays as a documented SDK extension; the stream-frame serialization failure also carries it. `acceptedOutputModes` filtering is listed under Breaking changes. New `agent_sdk/common/media.py` with `normalize_media_type` and `media_type_match(mode, supported)` (C-079) replaces `_mode_accepted` in `routes/a2a.py`. `TaskRecord` gains `accepted_output_modes` (optional, runtime-only). Docs describe the `TaskStore` page-token hook and the 400 `-32602` for an over-cap body. Changed: `agent_sdk/agent/runner.py` (`set_task_status`, `apply_output_modes`), `agent_sdk/models/a2a.py`, `agent_sdk/tasks/store.py` (`TaskRecord.accepted_output_modes`), `agent_sdk/routes/a2a.py`, `agent_sdk/common/media.py`. Tests: `tests/test_gh259_a2a_route.py` (the page-token shape test moved here from `tests/test_rt001_oauth_capped_body.py`). Ruling: https://github.com/wailuen/a2a-sdk/issues/259#issuecomment-6393088522
- GH-260: a request with no bearer token now always gets the 401 + protected-resource challenge; it no longer draws from the per-IP unauth bucket, so it never 429s (invalid-bearer attempts and `/oauth/*` still do). The `/oauth/*` 429 body change is listed under Changed. Changed: `agent_sdk/auth/middleware.py`, `agent_sdk/app.py`, `docs/protocols.md`. Tests: `tests/test_gh260_rate_limit.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/260#issuecomment-6393088715

## [0.22.0] — 2026-10-24

### 🔴 Breaking changes
- GH-250: (a) a `SafeValueError` subclass whose `message` cleans to empty (only control or Unicode format characters) now raises `TypeError` when its module is imported (`agent_sdk/models/errors.py`). (b) The exported stable-core helpers `safe_line_text`, `safe_cell_text`, `safe_id_text` and `safe_joined_id_text` (`agent_sdk/common/redact.py`) now drop Unicode format characters (Cf), so their output changes for any value that holds them, including ZWJ emoji sequences, Persian ZWNJ, and ids that contain a BOM or ZWSP. Ruling: https://github.com/wailuen/a2a-sdk/issues/250#issuecomment-6381441157. Tests: `tests/test_gh250_core_hardening.py`, `tests/test_gh230_safe_value_error.py`, `tests/test_gh212_id_safe_text.py`. **Migration:** give every `SafeValueError` subclass a `message` with at least one visible character; do not rely on Cf characters surviving these helpers (compare ids before cleaning, not after).
- GH-247 (follow-up to GH-235): `POST /ag-ui/run` ends the run with `RUN_ERROR` `invalid resume entry` (code `validation`) for a `resume` that is present and not a list, for more than one entry, and for a present `status` other than `"resolved"` or `"cancelled"` (checked before any interrupt lookup or delivery; a missing or null `status` is still delivered as `None`). `_resume_interrupt_id` returns `""` unless `resume` has exactly one entry, so a two-entry body at the per-task cap gets `RUN_ERROR`, not 429. `TOOL_CALL_ARGS` deltas and tool result content use `dumps_strict` with a fixed fallback (`{}` / `tool result not serializable`). The route reads its body through `read_capped_body` (same cap, same 413). `docs/protocols.md` updated. Ruling: https://github.com/wailuen/a2a-sdk/issues/247#issuecomment-6381440613. Changed: `agent_sdk/routes/ag_ui.py`, `agent_sdk/example/agent.py` (the `publish_note` demo now reads `payload.decision` when `status` is null or resolved), `docs/protocols.md`. Tests: `tests/test_gh235_nested_json_and_resume.py`. **Migration:** an AG-UI client must send `status` `"resolved"` or `"cancelled"` (the shorthand words `approved`/`rejected` are no longer accepted on AG-UI).
- GH-248 (pageToken check): `GET /v1/tasks` asks the store via the new `TaskStore.is_valid_page_token()` (default accepts any token; `InMemoryTaskStore` requires 32 hex) so custom stores keep their own cursor format. Files: `agent_sdk/tasks/store.py`, `agent_sdk/tasks/memory.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/248#issuecomment-6381440791. **Migration:** send only a `pageToken` returned by a previous list call.
- GH-248: A2A routes (`agent_sdk/routes/a2a.py`, `agent_sdk/app.py`) return a fixed `-32603` envelope for unhandled errors on `/v1/*`; `acceptedOutputModes` and `Content-Type` match case-insensitively with `*/*` and `type/*` wildcards; `historyLength` applies to resume replies and the first stream snapshot; a non-`user` `message.role` is 400 `-32602`; `GET /v1/tasks` rejects a malformed `pageToken` with 400 `-32602`; `GET /v1/tasks/{id}:subscribe` is served beside POST; send/stream bodies use the capped reader. Wire stays bare (documented). Ruling: https://github.com/wailuen/a2a-sdk/issues/248#issuecomment-6381440791. **Migration:** send `message.role` `"user"` only.
- GH-249: the agent card leaves the A2UI extension off when `supportedCatalogIds` would be empty (no registered tool emits an A2UI type). `A2uiCapabilities.extended` is true only for `tier == "core+extended"` (`non-extended` is now core). `_field_summary` marks a field required when the serialization-mode schema lists it and expands nested models one level; the compact-schema header says "required fields and common optional fields shown". `SurfaceRegistry` / `apply_data_model_update` are documented as internal. The translator docstring now describes `allows()`; the duplicated C-006 GH-240 sentence is merged. Ruling: https://github.com/wailuen/a2a-sdk/issues/249#issuecomment-6381440938. Changed: `agent_sdk/a2ui/translator.py`, `agent_sdk/a2ui/catalog.py`, `agent_sdk/routes/agent_card.py`, `docs/protocols.md`. Tests: `tests/test_gh249_a2ui_gating.py`, `tests/test_gh240_a2a_catalog_negotiation.py`, `tests/test_gh240_field_summary_alias.py`, `tests/test_gh188_catalogs_from_emits.py`. **Migration:** a card consumer must not assume the A2UI extension is present.
- GH-246: `POST /mcp` and `POST /mcp/messages` read the body through the new `agent_sdk/common/body.py::read_capped_body`, which refuses an over-cap `Content-Length` before reading and stops reading once the cap is passed (same 413). A request with a missing, null or non-(string|integer) `id` gets `-32600` with `id: null` before any handler runs (before, a null id ran the tool and got a 202). `/mcp/messages` now checks `Content-Type` (415), acks a JSON-RPC response with 202 and answers a full queue with a JSON 503 body. The `Content-Type` compare ignores case. The `load_skill` catalog skips an entry too long to fit and still lists later short ones (was: stopped at the first misfit). `load_skill` success carries `isError: false`. `tools/list` and `prompts/list` share one `_page` helper. DESIGN.md and `docs/protocols.md` state that `tools/list` is version-independent and only `serverInfo.title`/`icons` in `initialize` are version-gated. A JSON-RPC response (no `method`, has `result` or `error`) gets 202 even with a null or missing `id`. `/oauth/register` and the consent form read their body through `read_capped_body`, same 400/413 replies. Changed: `agent_sdk/routes/mcp.py`, `agent_sdk/routes/oauth.py`, `agent_sdk/common/body.py`, `DESIGN.md`, `docs/protocols.md`. Tests: `tests/test_gh246_mcp_route.py`, `tests/test_gh205_mcp_skills.py`, `tests/test_rt001_oauth_capped_body.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/246#issuecomment-6381440418. **Migration:** send an integer or string `id` on every non-notification request.

### Fixed
- v0.22.0 release gate (A2A/A2UI): with no A2UI-emitting tool the card also drops `application/a2ui+json` from `defaultOutputModes`, and `X-A2A-Extensions` never echoes an extension the card does not declare (GH-249 follow-through). This also covers credential forwarding: an agent with no credentialed source no longer echoes that URI. Changed: `agent_sdk/routes/agent_card.py`, `agent_sdk/routes/a2a.py`, DESIGN.md. Tests: `tests/test_gh249_a2ui_gating.py`, `tests/test_protocol_fixes_w9_group_a.py`, `tests/test_forwarding_integration.py`.
- v0.22.0 release gate (AG-UI): a `str` tool result holding a lone surrogate is scrubbed instead of ending the run with RUN_ERROR; a model result whose `model_dump` raises gets the fixed fallback text. The console records a message role only when it is a non-empty string (C-072 parity). Changed: `agent_sdk/routes/ag_ui.py`, `agent_sdk/console/static/chat.js`. Tests: `tests/test_gh235_nested_json_and_resume.py`, `tests/test_gh234_agui_chat_driver.py`.
- v0.22.0 release gate (MCP): a request with no method answers with `id: null` when its id is not a valid string or integer. Changed: `agent_sdk/routes/mcp.py`. Tests: `tests/test_gh246_mcp_route.py`.
- v0.22.0 release gate (MCP): `run_gate`'s outputSchema check no longer fails a void tool result (empty text block, no `structuredContent`), which the server sends for a tool that returns nothing (§5.6). A non-empty result with no `structuredContent` still fails. Changed: `agent_sdk/testing/mcp.py`. Tests: `tests/test_gh237_testing_clients.py`.
- GH-250: JSON nested past 64 levels is answered with the fixed text `nesting too deep` (new `NestingTooDeep`, a `json.JSONDecodeError` subclass raised by `loads_strict`), apart from the malformed-JSON text, with the parse-error code kept: `-32700` on `POST /mcp`, `POST /mcp/messages` and A2A (HTTP 400), `RUN_ERROR` on AG-UI; about 61 levels remain for tool arguments. The Graph webhook reads its body through `read_capped_body` and parses with `loads_strict`, dropping with 202 on any parse failure. Boot loads skills and checks `exclude_from_catalog` before the credential store opens, and `build_app()` closes the store on any later boot error. New `agent_sdk.common.redact.drop_format_chars` (C-078) removes Unicode format and bidi characters (Cf, e.g. U+202E) in `safe_line_text`, `safe_cell_text`, `safe_id_text`, `safe_joined_id_text` and the `SafeValueError` hint. `SafeValueError` now raises `TypeError` at class definition when the message cleans to empty. `docs/protocols.md`, `DESIGN.md`, `docs/content-types.md` and the components README updated; tests hardened. Ruling: https://github.com/wailuen/a2a-sdk/issues/250#issuecomment-6381441157. Changed: `agent_sdk/common/json_strict.py`, `agent_sdk/common/redact.py`, `agent_sdk/agent/loop.py`, `agent_sdk/models/errors.py`, `agent_sdk/contrib/webhooks/graph.py`, `agent_sdk/app.py`, `agent_sdk/routes/{mcp,a2a,ag_ui}.py`. Tests: `tests/test_gh250_core_hardening.py`, `tests/test_gh235_nested_json_and_resume.py`, `tests/test_gh205_mcp_skills.py`, `tests/test_gh212_id_safe_text.py`, `tests/test_gh230_safe_value_error.py`, `tests/test_rt001_strict_required_nullable_output.py`. **Migration:** a client that matched the old parse-error text for a too-deep body now sees `nesting too deep` (same code); a text with Unicode format characters renders without them; a `SafeValueError` subclass whose `message` is only control or format characters now fails at import.
- GH-243: console chat (`agent_sdk/console/static/chat.js`) follows the `ChatDriver` AG-UI rules: `sendAgui` captures the thread on every send and skips interrupt capture, the Resume form and the history fold when the thread changed mid-run; RUN_ERROR removes the Resume form; the Resume form shares `send()`'s busy guard and error handler and is ignored unless its interrupt is still pending; an explicit string role is recorded per message id and only assistant ids are folded; text with no START is kept as assistant; the user message is appended on RUN_FINISHED only. The Reset handler removes the Resume form. DESIGN.md §7.2. Tests: `tests/test_gh234_agui_chat_driver.py`, `tests/test_gh239_console_caps.py` (each gains a `test_*_available_in_ci` guard; the gh239 module skip is now per-test).
- GH-244: console A2UI renderer caps waterfall segments, multi-category periods and categories, time-series points (all at `MAX_ROWS`) and comparison-table columns (10), and no longer spreads payload arrays into `Math.max`/`Math.min`. DESIGN.md §5.4/§7.1 now say a replayed `createSurface` reuses the same `surfaceId` and is ignored with a warning by the console. Changed: `agent_sdk/console/static/a2ui.js` (new export `MAX_COLUMNS`). Tests: `tests/test_gh239_console_caps.py`, `tests/test_a2ui_wire.py`, `tests/test_gh214_no_delete_surface.py`.
- GH-245: `agent_sdk/testing/chat.py` records an AG-UI role only when it is a non-empty string (`role: null` text is kept) and posted AG-UI messages carry an `id`. `agent_sdk/testing/mcp.py` `McpClient` uses `SUPPORTED_PROTOCOL_VERSIONS[0]` and sends the negotiated `MCP-Protocol-Version` after initialize. `agent_sdk/testing/turns.py` A2A attempts read the card once and send `X-A2A-Extensions` plus `a2uiClientCapabilities` when the A2UI extension is advertised (`_a2a_attempt` gains an optional `driver`). `harness/workflows/acceptance-api.js` and `template/.claude/workflows/acceptance-api.js` reject `transports` entries other than `a2a`/`agui` and throw when a non-empty `onlyIds` matches no scenario (harness workflow input validation, not a SemVer surface). Tests: `tests/test_gh237_testing_clients.py`, `tests/test_gh131_acceptance_api_args_normalization.py`, `tests/test_chat_driver.py`, `tests/test_gh234_agui_chat_driver.py`. The same acceptance SKILL.md edit was also made in the template repo (`template/.claude/skills/acceptance/SKILL.md`, wailuen/a2a-agent-template commit 6e8d820). **Migration:** pass only `a2a`/`agui` in `transports` and only existing scenario ids in `onlyIds`.

### Added
- GH-245: `agent_sdk/testing/mcp.py` `run_gate` gains the `skills_tool` option and the CLI flag `--skills-tool`; a domain tier-1 `load_skill` is counted (the built-in is matched by its fixed shape). `agent_sdk/testing/chat.py` `A2AError.AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED` is the new constant name.

### Changed
- GH-245 (provisional `agent_sdk.testing` surface, outside the DESIGN.md §4.0 stable core; listed here as the notice the header requires): `agent_sdk/testing/chat.py` `ChatDriver.a2a_turn` treats a card without `preferredTransport` as `JSONRPC` and rejects it with the existing error (before, it was accepted as HTTP+JSON). Spec: A2A v0.3.0 `AgentCard.preferredTransport` defaults to `"JSONRPC"` when absent. **Migration:** set `preferredTransport: "HTTP+JSON"` on the card.
- GH-245 (provisional `agent_sdk.testing` surface, notice in a minor): `agent_sdk/testing/mcp.py` `run_gate` now fails a tool whose `structuredContent` is absent or does not match its `outputSchema`, so a run that passed before can fail. Spec: MCP 2025-06-18 server/tools "Output Schema": a server that declares an `outputSchema` MUST provide `structuredContent` that conforms to it. **Migration:** make each tool's `structuredContent` match its `outputSchema`.
- GH-245 (provisional `agent_sdk.testing` surface): `A2AError.NOT_AUTHENTICATED` is deprecated; it stays as an alias of `AUTHENTICATED_EXTENDED_CARD_NOT_CONFIGURED`. `jsonschema>=4.20` is now a runtime dependency (`pyproject.toml`), because `agent_sdk/testing/mcp.py` imports it.

## [0.21.0] — 2026-10-24

### 🔴 Breaking changes
- GH-240: over A2A a Standard Profile card is sent only when the client's advertised catalogs (`catalogs`, then `v0.9.supportedCatalogIds`, then `supportedCatalogIds`) contain `urn:a2ui-profile:standard:v1`; otherwise the TextPart plus a plain model-dump DataPart (no A2UI mimeType). A client with no catalogs key is unchanged; AG-UI CUSTOM is unchanged. `A2uiCapabilities.from_metadata` / `gated` gain keyword `keep_declared_catalogs` (default False). `_field_summary` uses the wire alias. "Fresh surfaceId per turn" now reads "per artifact". The `validate_a2ui_delivery` error no longer mentions the removed split. GH-242 test fixes. Ruling: https://github.com/wailuen/a2a-sdk/issues/240#issuecomment-6379597173. Changed: `agent_sdk/a2ui/translator.py`, `agent_sdk/a2ui/catalog.py`, `agent_sdk/routes/a2a.py`, `agent_sdk/agent/runner.py`, `docs/protocols.md`, `DESIGN.md`. Tests: `tests/test_gh240_a2a_catalog_negotiation.py`, `tests/test_gh240_field_summary_alias.py`. **Migration:** add `urn:a2ui-profile:standard:v1` to `a2uiClientCapabilities.catalogs` (or send no `catalogs` key).
- GH-241: the `SafeValueError` hint is sanitised in `_validation_phrase` (`agent_sdk/agent/loop.py`) with `safe_line_text`, then Unicode format (bidi) characters are dropped; an empty result shows the generic "value failed a validation rule". `SafeValueError.__init_subclass__` (`agent_sdk/models/errors.py`) raises `TypeError` for a non-str or blank class `message` (**behaviour change**: a subclass with no `message` now fails at definition). `agent_sdk.safe_joined_id_text` is exported (`agent_sdk/__init__.py`). `docs/content-types.md` states the leftover risk inside an `is_id` cell; rendering is unchanged (GH-212 ruling). Ruling: https://github.com/wailuen/a2a-sdk/issues/241. Changed: `agent_sdk/agent/loop.py`, `agent_sdk/models/errors.py`, `agent_sdk/__init__.py`. Tests: `tests/test_gh230_safe_value_error.py`, `tests/test_gh212_id_safe_text.py`. **Migration:** give every `SafeValueError` subclass a non-blank string class `message`.

### Fixed
- v0.21.0 release gate (MCP): `structuredContent` now restores required `None` keys in models held in dict values and nested lists too (was direct models and flat lists only), and caches each model's required keys per class. `load_skill` with a missing or non-string `name` now says "required field is missing" / "expected a string" instead of "unknown argument". Changed: `agent_sdk/routes/mcp.py`. Tests: `tests/test_gh225_multi_type_emits.py`, `tests/test_gh205_mcp_skills.py`.
- GH-239: console A2UI renderer (`agent_sdk/console/static/a2ui.js`): the bar chart and the generic card's scalar key/value rows now use the shared `capRows`/`moreNote` row cap (`MAX_ROWS`, 100) instead of drawing every row; `renderA2ui` prunes registry entries whose painted node is detached (`node.isConnected === false`); the registry comment names the real fields (`_componentMap`). DESIGN.md §7.1 documents the generic card and the cap. Tests: `tests/test_gh239_console_caps.py`.
- GH-242: `acceptance-api.js` (`harness/workflows/` and the template copy) rejects a non-array `transports` or `onlyIds` with a fixed message that names the field only (no arg echo, never the `keyFile` path); `onlyIds` matches whole ids, so `S-1` does not match `S-10`. Tests: `tests/test_gh131_acceptance_api_args_normalization.py` (node mutation tests, widened no-echo regex for `e.message` and `JSON.stringify(normalizedArgs)`, bare-`args` scan of helpers above the guard), `tests/test_gh233_workflow_scripts_parse.py` (utf-8 read, `re.M` export strip, repo-relative path plus node stderr on failure, requires `.claude/workflows/sdk-wave.js`).
- GH-235: `loads_strict` (`agent_sdk/common/json_strict.py`) refuses input nested deeper than 64 levels (and maps `RecursionError` as a backstop) with a fixed-message `json.JSONDecodeError` (no input echo), so `POST /mcp`, `POST /mcp/messages`, `POST /v1/message:send`, `POST /ag-ui/run` and `POST /oauth/register` return their parse error instead of a 500 on every Python version. An AG-UI run (`agent_sdk/routes/ag_ui.py`) with more than one `resume` entry now ends with `RUN_ERROR` `invalid resume entry` (code `validation`); before, only the first entry was read. Tests: `tests/test_gh235_nested_json_and_resume.py`. Spec-conformance fix, kept under Fixed (GH-221 precedent). Ruling: https://github.com/wailuen/a2a-sdk/issues/235. **Migration:** keep JSON input at 64 nesting levels or fewer; send exactly one `resume` entry per AG-UI run.
- GH-237: `McpTestClient` gate (`agent_sdk/testing/mcp.py`) leaves the built-in `load_skill` out of the `--expected-count` comparison. The A2A message built in `agent_sdk/testing/turns.py` carries `"kind": "message"`. `ChatDriver.agui_turn` / `agui_resume` (`agent_sdk/testing/chat.py`) change `messages` only after RUN_FINISHED: `agui_turn` appends the user message, plus the assistant message when the reply is non-empty; RUN_ERROR, a stream with no terminal event, or an exception leaves `messages` unchanged. The reply leaves out text from messages with an explicit non-assistant `role`. Return types stay `str`. Tests: `tests/test_gh237_testing_clients.py`.
- GH-238: console `chat.js` restores the interrupt after a failed resume POST only when `state.threadId` is unchanged and no new interrupt is pending, and tracks the shown Resume form so at most one exists. Assistant messages (START/CONTENT/END and chunk-only) are folded into `state.aguiMessages` only after `RUN_FINISHED`, in order of their first frame; an id-less chunk with no earlier chunk id gets a `uuid()` id. Tests: `tests/test_gh234_agui_chat_driver.py` now runs the console checks under node (skipped without node) instead of source greps (GH-242), and the `http_error` case asserts `httpx.HTTPStatusError`.

### Added
- GH-240: public dataclass field `A2uiCapabilities.negotiate_standard` (`agent_sdk/a2ui/translator.py`, default False, set only by `from_metadata(keep_declared_catalogs=True)`; it takes part in `==` and `repr`) and keyword `keep_declared_catalogs` (default False) on `A2uiCapabilities.from_metadata` / `gated`. Existing callers are unchanged.

### Changed
- GH-236: `load_skill` carries `title: "Load skill"` and annotations `{"readOnlyHint": true, "openWorldHint": false}`, is served only while the MCP skill catalog is non-empty, and answers extra keys or a missing or non-string `name` with the registry's argument-error shape (key names only, never values). Its catalog is cut at whole entries within 2048 characters and ends with `…and N more`. An undecodable or negative cursor on `tools/list` and `prompts/list` is now JSON-RPC -32602 `invalid cursor` (was clamped to 0). Strict schema mode drops `null` from `anyOf` unions of 3+ members at property positions. The `mcp_skills` and reserved-name boot checks run before the credential store opens. Ruling: https://github.com/wailuen/a2a-sdk/issues/236#issuecomment-6379597364. Changed: `agent_sdk/routes/mcp.py`, `agent_sdk/common/schema.py`, `agent_sdk/app.py`, `docs/protocols.md`, `docs/deployment.md`. Tests: `tests/test_gh205_mcp_skills.py`, `tests/test_gh206_strict_schema_mode.py`, `tests/test_gh207_mcp_description.py`, `tests/test_rt001_strict_required_nullable_output.py`. Spec-conformance change (MCP 2025-06-18 Utilities, Pagination: invalid cursors are -32602), kept under Changed (GH-221 precedent). **Migration:** send only cursors returned as `nextCursor`; call `load_skill` with only `name`.

## [0.20.1] — 2026-10-24

### Fixed
- GH-233: `acceptance-api.js` (`harness/workflows/` and the template copy) had an apostrophe inside a single-quoted string, so the Workflow runtime could not load it and `/acceptance` stopped before any scenario. The rule text now reads "set the minScore of that transport to 1". Tests: `tests/test_gh233_workflow_scripts_parse.py` (runs `node --check` on every workflow script).
- GH-234: `ChatDriver` AG-UI driver (`agent_sdk/testing/chat.py`) sends `credentials=` and `Accept: text/event-stream` on `/ag-ui/run`; a stream with no `RUN_FINISHED`/`RUN_ERROR` fires the `error` emit `stream closed without a terminal event` and returns `""` (as does a `RUN_ERROR` stream, so no partial reply reaches `messages`); frames after `RUN_ERROR` are ignored; text from different `messageId`s is joined with `\n` and `TEXT_MESSAGE_CHUNK` is handled. Console (`agent_sdk/console/static/chat.js`, `agent_sdk/console/static/a2ui.js`): "Reset session" in `chat.js` calls the new `a2ui.js` export `resetSurfaces()` to clear painted A2UI surfaces, a surface entry in `a2ui.js` no longer keeps a duplicate component list, a failed resume POST in `chat.js` restores the pending interrupt, and `TEXT_MESSAGE_CHUNK`-only messages are folded into history in `chat.js`. Tests: `tests/test_gh234_agui_chat_driver.py`. A `TEXT_MESSAGE_CHUNK` without `messageId` joins the open chunk message (AG-UI sends the id on the first chunk only), in both `agent_sdk/testing/chat.py` and `agent_sdk/console/static/chat.js`; the console folds chunk-only text into history only after `RUN_FINISHED`.

## [0.20.0] — 2026-10-24

### 🔴 Breaking changes
- GH-214: the SDK no longer emits `deleteSurface` for a surface in the artifact or run that created it, and the agent-card A2UI param `deleteSurfaceSemantics` is removed. This is a stable-core wire / Standard Profile change under DESIGN.md §4.0. Ruling: https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762. Emit impact: on A2A each A2UI artifact is `[TextPart, DataPart(open)]` (no close DataPart); on AG-UI each emission is `AGENT_ARTIFACT` then one `A2UI_UPDATE` (no second `A2UI_UPDATE` carrying `deleteSurface`). The open sequence is `createSurface`, `updateComponents`, `updateDataModel`. Parse impact: clients that read `deleteSurfaceSemantics` from the card (`dataEncoding` and the other A2UI params stay), or that waited for a `deleteSurface` message, see neither. Reason: a spec renderer painted each card and then unmounted it. A `translate()` output with no open messages is still rejected. The python helper `split_a2ui_delivery` and `split_a2ui_delivery_validated` are replaced by `validate_a2ui_delivery`. **Migration:** clients manage surface lifetime themselves (keep the card mounted, or unmount it on your own rules); each turn has a fresh `surfaceId`, so cards never collide. The admin console keeps every surface in the transcript. Changed: `agent_sdk/a2ui/translator.py`, `agent_sdk/a2ui/catalog.py`, `agent_sdk/agent/runner.py`, `agent_sdk/routes/ag_ui.py`, DESIGN.md §5.4/§7.1, `docs/protocols.md`. Tests: `tests/test_gh214_no_delete_surface.py`.
- GH-205: a registered tool named `load_skill` now fails boot with `ValueError` whenever `skills_dir` is set, even with `mcp_skills=None` (`agent_sdk/app.py`). Before, such an agent booted and the loop shadowed the tool. Ruling: https://github.com/wailuen/a2a-sdk/issues/205. **Migration:** rename the tool, for example to `<domain>_load_skill`.

### Added
- GH-212: `agent_sdk.safe_id_text` is exported. `ColumnDef` gains `is_id: bool = False`; a `ComparisonTable` column with `is_id=True` renders through `safe_id_text`, other cells as before. `is_id` is omitted from the wire when false. New `agent_sdk.common.redact.safe_joined_id_text` is the old id rendering for ids joined into a row. Docs: `docs/content-types.md` (also GH-207 part 1: custom `ContentModel` authors should include machine ids in `_body_text`). Tests: `tests/test_gh212_id_safe_text.py`.
- GH-230: `agent_sdk.SafeValueError(ValueError)`. Subclass it, set the class attribute `message` to fixed guidance and raise it with no arguments; `safe_validation_message` then shows `type(err).message` (through `safe_line_text`, 256 characters) in MCP `isError` text, A2A/AG-UI tool results and admin try-tool. Text passed at raise time is never shown. A missing, empty or non-string `message`, a plain `ValueError` and an `AssertionError` keep "value failed a validation rule". Documented in `docs/tools.md`. Ruling: https://github.com/wailuen/a2a-sdk/issues/230#issuecomment-6363407316. Changed: `agent_sdk/models/errors.py`, `agent_sdk/__init__.py`, `agent_sdk/agent/loop.py`. Tests: `tests/test_gh230_safe_value_error.py`.
- GH-206: `AGENT_SDK_MCP_SCHEMA_MODE` (`standard` default, `strict`; any other value fails boot). In `strict`, MCP `tools/list` `inputSchema` and `outputSchema` (including the `emits` tuple `anyOf`) are flattened: local `#/$defs` refs are inlined (a recursive model keeps its `$ref` and `$defs`), `anyOf: [X, {"type": "null"}]` at a property becomes `X` (list items and dict values keep `null`), `default: null` is dropped, and a `discriminator.mapping` that would point at removed `$defs` is dropped. In `outputSchema` every nullable field leaves `required` (structuredContent is dumped with `exclude_none`), and a required-nullable field with no default keeps `type: [X, "null"]` so a serializer that re-emits `null` still validates. In `inputSchema` a required-nullable field stays required, because argument validation still demands the key. GH-221 title stripping still runs once. `standard` output is unchanged. The agent loop, agent card and argument validation are unchanged. New `agent_sdk/common/schema.py` (`strip_schema_titles`, moved from the private `_strip_titles` in `routes/mcp.py`; `flatten_schema`). Ruling: https://github.com/wailuen/a2a-sdk/issues/206#issuecomment-6359827730, clarified https://github.com/wailuen/a2a-sdk/issues/206#issuecomment-6377771749. Tests: `tests/test_gh206_strict_schema_mode.py`. Changed: `agent_sdk/config.py`, `agent_sdk/routes/mcp.py`, `docs/protocols.md`, `docs/deployment.md`, `workspace/components/README.md` (C-060 registry row).
- GH-205: `Agent(mcp_skills=None | "tool" | "prompts")` exposes the `skills_dir` catalog to MCP clients (opt-in; `None` leaves `initialize` and `tools/list` byte-identical). `"tool"` lists the read-only `load_skill` tool on `tools/list` and serves it on `tools/call`. `"prompts"` advertises `capabilities.prompts {listChanged: false}` and serves paginated `prompts/list` and `prompts/get` (one user message = skill body; unknown or excluded name is `-32602`); without it `prompts/*` stays `-32601`. Boot rejects any other value, either mode without `skills_dir`, and a registered tool named `load_skill` whenever `skills_dir` is set. `exclude_from_catalog` skills are hidden over MCP. Skill names are never echoed or logged. `McpClient` (alias `McpTestClient`) gains `list_prompts()` and `get_prompt()`. Ruling: https://github.com/wailuen/a2a-sdk/issues/205#issuecomment-6359827386. Changed: `agent_sdk/app.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/agent/skills.py`, `agent_sdk/testing/mcp.py`, DESIGN.md §5.5/§5.6, `docs/protocols.md`, `docs/testing.md`. Tests: `tests/test_gh205_mcp_skills.py`.
- GH-207: `@tool(mcp_description="...")` — optional (default `None`). When set, MCP `tools/list` uses it as the tool `description`; the agent loop and the agent card keep the docstring description. Unset output is byte-identical. Boot rejects an empty or whitespace-only value and one longer than 2048 characters (`ValueError`). The JSON text fallback (part 1) and an MCP-only timeout (part 3) are not implemented. Ruling: https://github.com/wailuen/a2a-sdk/issues/207#issuecomment-6359828022. Changed: `agent_sdk/agent/registry.py`, `agent_sdk/routes/mcp.py`, `docs/tools.md`. Tests: `tests/test_gh207_mcp_description.py`.

### Changed
- GH-212: `safe_id_text` keeps `( )` and single spaces verbatim and collapses a whitespace run to one space (it was `_`); `| < > [ ]` and control characters are neutralised as before and `=` stays byte-exact. `202601026118 (1688214-U)` now reads the same in the text and in `structuredContent`. The two ids joined into a row, `EmailList` `(id: ..., conversation: ...)` and `FundPerformance` `source <pb_id>`, keep the old rendering (`safe_joined_id_text`). Ruling: https://github.com/wailuen/a2a-sdk/issues/212#issuecomment-6359828392; confirmation: https://github.com/wailuen/a2a-sdk/issues/212#issuecomment-6366237627. Changed: `agent_sdk/common/redact.py`, `agent_sdk/models/content_types.py`, `agent_sdk/__init__.py`, DESIGN.md §4.3, `workspace/components/README.md`.
- GH-231: production no longer serves `/openapi.json`, `/docs`, `/redoc` or `/docs/oauth2-redirect` (404). They were public and listed every admin route. They are mounted only when `DEV_MODE=true` (already refused for a non-local `PUBLIC_URL`). No new setting. Changed: `agent_sdk/app.py`, `docs/security.md`. Tests: `tests/test_gh231_api_docs_gated.py`, `tests/test_rt002_placeholder_identity.py` (AC-6 now checks `app.openapi()`).

### Fixed
- GH-230 / LRN-470: a pydantic error `type` code outside the known list (for example `PydanticCustomError(f"leak_{x}", ...)`) was echoed into tool error text, so input could leak. It now shows "input failed validation". The SDK's own `unknown_argument` code and every code already in the list are unchanged.
- GH-229: `acceptance-api.js` (`harness/workflows/` and the template copy) now normalizes `args` like `wave-cycle.js` (GH-131): a JSON-string `args` is parsed, bad JSON gets a named error, and every read goes through `normalizedArgs`. It fails fast when `scenarios` is not an array or `baseUrl`/`keyFile` is missing; errors name only the field and never echo args or values (SI-2). Tests: `tests/test_gh131_acceptance_api_args_normalization.py`.
- MCP `tools/call` `structuredContent` now conforms to the advertised `outputSchema` in both schema modes: a required field whose value is `None` is sent as `null` instead of being dropped by `exclude_none`, and a plain pydantic `emits` model is dumped `by_alias=True` (the text block too) so aliased keys match the schema (`agent_sdk/routes/mcp.py::_restore_required_nulls`). Tests: `tests/test_gh225_multi_type_emits.py::test_required_null_and_alias_conform_to_output_schema`.
- Strict schema mode drops a `discriminator.mapping` whose `#/$defs` targets were inlined. The synthetic `load_skill` tool description caps its skill catalog at 2048 characters. `mcp_description` that is not a string fails registration with `ValueError`. `mcp_skills` is typed `Literal["tool", "prompts"] | None`.
- Console: a `ComparisonTable` `is_id` column renders its value as-is, never locale-formatted (`agent_sdk/console/static/a2ui.js`, GH-212).

## [0.19.0] — 2026-10-23

### Added
- GH-225: `@tool(emits=(A, B))` — a tool that returns different content types (a dispatcher) can declare a tuple. `ToolDecl.emits` keeps the value as given (`X` or the tuple); the new `ToolDecl.emits_types` is always a tuple, empty for no `emits`, `(X,)` for a single type. Boot rejects an empty tuple, duplicate members, an unregistered content type, `MarketBriefing` inside a tuple, a member outside `a2ui_allowed_components`, an annotation that neither is `Any`/absent, nor a common superclass of every member, nor a `Union`/`|` exactly covering the tuple (async-generator yield types follow the same rule), and two members whose `$defs` share a name with different content. The loop sends a card when the result is an instance of any member and labels it with that member's `data_type`; a result matching none gets text only. MCP `outputSchema` for a tuple tool is `{"type": "object", "anyOf": [<member schemas>], "$defs": {<merged>}}` (GH-221 title stripping still applies); `structuredContent` is sent when the result is a member, and raw-dict coercion uses the first member that validates (failure text stays `tool output coercion failed`; only exception type names are logged). The agent card `x-sdk.emits` is a list of `data_type` strings for a tuple tool (a string for a single type, unchanged) and `supportedCatalogIds` covers every member. `@tool(emits=X)` is unchanged byte for byte. `DeferredEvent` gains `emits_types`. `mcp_only` (part b) was rejected by the ruling and is not implemented. Ruling: https://github.com/wailuen/a2a-sdk/issues/225#issuecomment-6359382542. Changed: `agent_sdk/agent/registry.py`, `agent_sdk/app.py`, `agent_sdk/agent/loop.py`, `agent_sdk/agent/runner.py`, `agent_sdk/agent/deferred.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/routes/agent_card.py`, DESIGN.md §4.1/§5.5, `docs/tools.md`, `pyproject.toml` (`jsonschema` dev dependency). Tests: `tests/test_gh225_multi_type_emits.py`.

- GH-228: both wave runners (`harness/workflows/wave-cycle.js`, `.claude/workflows/sdk-wave.js`, plus the `.claude/` and `template/` copies of wave-cycle.js) now treat indented lines directly after a `Creates:`/`Modifies:` line (up to a blank line or the next `- ` field) as part of that line, so a hard-wrapped path list is no longer dropped; `harness/wave_scope.py::extract_wave_scope` and the Parse prompt carry the same rule. `rescanScope` also runs twice with no round to retry, labelled `scan:scope:final-pre-audit` (before Protocol Audit) and `scan:scope:final-pre-archive` (after Codify, before the archive gate); a null, mismatched or unowned result there sets `protocolBlocked` and logs `final scope re-scan returned no trustworthy result — archive BLOCKED`. A new per-todo scan (`TODO_SCOPE_SCAN_PY`, built from `PATH_RULE_PY`) reports `{todoId, path, kind}` rows; `rescanScope` uses it to give a new path to the group whose todo declares it (not the calling loop's group) and to widen `g.creates`/`g.modifies`, `wave.allCreates`/`wave.allModifies`. It fails closed when the per-todo paths differ from the flat scan, or when a new path has no owning todo (`scope re-scan: path <p> has no owning todo — wave BLOCKED`). `SCOPE_SCAN_PY`'s flat output is unchanged for unwrapped waves. Ruling: https://github.com/wailuen/a2a-sdk/issues/228. Tests: `tests/test_wave_scope_extraction.py`, `tests/test_wave_cycle_behaviour.py`, `tests/test_sdk_wave_behaviour.py`.

### Changed
- GH-225: deferred-path artifact gate. A `long_running` tool that declares `emits` and whose resolved value matches none of the declared types now gets a text-only artifact (one `TextPart`, labelled with the tool name, no A2UI card, no `DataPart`). Before, it got an artifact labelled with the first declared type's `data_type` with no type check, which disagreed with the inline path (no card). A matching value is labelled with the matching member's `data_type`; a tool with no `emits` is unchanged. Ruling: https://github.com/wailuen/a2a-sdk/issues/225#issuecomment-6359382542. Changed: `agent_sdk/agent/runner.py` (`build_text_only_artifact`). Tests: `tests/test_gh225_multi_type_emits.py`.

### Fixed
- LRN-469: MCP `tools/call` now returns `isError: true` ("tool output does not match its declared type") when a tool with a declared `emits` (single type or tuple) returns a model of an undeclared type. Before, a tuple tool reported success with no `structuredContent` and a single-type tool sent `structuredContent` that did not match its advertised `outputSchema`, both against MCP 2025-06-18 §Tools structured content. A2A/AG-UI are unchanged (text only, no card).

## [0.18.0] — 2026-10-23

### Changed
- GH-219: the agent card no longer repeats each tool's `outputSchema`. Skills drop `x-sdk.outputSchema` and `x-sdk.outputSchemaWireNote`; `x-sdk.inputSchema`, `tier` and `emits` stay. MCP `tools/list` still carries `outputSchema`. A search of `agent_sdk/` (routes, console JS, testing, a2ui) found no reader of the card field; only the RT-004 tests used it, and they are rewritten. Also: boot logs one warning when `AGENT_DESCRIPTION` is blank (the display-name fallback stays), and `docs/tools.md` examples show `tags=`. Ruling: https://github.com/wailuen/a2a-sdk/issues/219#issuecomment-6345507008. Changed: `agent_sdk/routes/agent_card.py`, `agent_sdk/app.py`, `agent_sdk/agent/registry.py` (`output_schema()` docstring), DESIGN.md, `docs/tools.md`. Tests: `tests/test_gh219_card_remainders.py`, `tests/test_mcp_conformance_w9.py`.
- GH-221: MCP `tools/list` no longer carries pydantic's auto-generated `title` keys in `inputSchema` and `outputSchema` (recursive, including `$defs`, `properties`, `items`, `anyOf`; a property named `title` is kept). This makes the list smaller; the agent loop, agent card and validation are unchanged, and `$defs`/`$ref` are neither added nor removed. `docs/tools.md` gains an "ID A or ID B" section: optional fields, a tool-side check, and a warning against a top-level `anyOf`/`oneOf`/`allOf` (Anthropic models and Claude MCP clients reject it). Part 6 (credential names in `initialize.instructions`) is unchanged, as ruled. Ruling: https://github.com/wailuen/a2a-sdk/issues/221#issuecomment-6345506542. Changed: `agent_sdk/routes/mcp.py`, `docs/tools.md`. Tests: `tests/test_gh221_tools_list_titles.py`.
- GH-221 (moved here from Breaking changes: it is a wire fix toward the published spec, not a break of the stable core): MCP wire changes for spec conformance (MCP 2025-06-18). Authority: (1) Tools, "Error Handling": an unknown tool is a protocol error with code `-32602`. (2) Transports, "Sending Messages to the Server", item 4: a POSTed JSON-RPC response or notification gets `202 Accepted` with no body. (3) Transports, "Session Management": a request with an unknown session id gets `404`. This is a wire fix toward the published spec, shipped in a minor bump; no owner ruling comment exists on issue 221. (1) `tools/call` for an unknown tool or a Tier 2 tool now returns JSON-RPC `-32602` "tool not found" instead of `-32601`. (2) A POSTed JSON-RPC response (not a request) now gets `202` with an empty body. (3) `GET /mcp` now checks `Mcp-Session-Id` when present (no header still returns 200): longer than 64 chars gets 400; unknown, expired or other-owner gets 404. Migration: clients that matched `-32601` to detect a missing tool must match `-32602` (and the "tool not found" message); clients that expected a body on a POSTed response must accept an empty 202; clients that open `GET /mcp` may omit `Mcp-Session-Id` (still 200); the header is checked only when present, so send the one from `initialize` and expect 400 or 404 if it is bad. Changed: `agent_sdk/routes/mcp.py`, DESIGN.md §5.5, `docs/protocols.md`. Tests: `tests/test_gh221_mcp_conformance.py`.

### Added
- GH-218 (docs): `docs/deployment.md` now explains setting uvicorn's `FORWARDED_ALLOW_IPS` to the gateway's address range, using the same values as `AGENT_SDK_TRUSTED_PROXIES`, and warns never to use `*` (clients could spoof their address and bypass the rate-limit trust model). `docs/security.md` links to it. No code change. Tests: `tests/test_changelog_gh143_gh144_wire_changes.py` (`_GRANDFATHERED_ALIASES` ratchet no longer lists `AGENT_SDK_TRUSTED_PROXIES`, now documented here). Ruling: https://github.com/wailuen/a2a-sdk/issues/218#issuecomment-6345507574.
- GH-223: both wave runners (`harness/workflows/wave-cycle.js`, `.claude/workflows/sdk-wave.js`) now re-check every SDK candidate at codify with the existing C-058 stale check (`STALE_CHECK_PY`, same fail-closed rules; no second checker) and write `Status: fixed-in-wave | still-open` per candidate in `workspace/sdk-candidates.md`. A candidate is `fixed-in-wave` only when its quote is gone now and was seen present earlier in the wave; an empty or never-verified quote, a missing path, a grep error or an untrusted result stays `still-open`. `SDK_SCAN_SCHEMA` now requires and carries the finding `id` and `quote` unchanged. In the SDK repo, findings about the wave's own process (CHANGELOG, todo scope, template-mirror hygiene) are excluded by the classifier. New opt-in arg `autoFileSdkIssues` (default `false`, files nothing): when `true`, a script (`FILE_SDK_ISSUES_PY`) files only `still-open` candidates, deduped by `gh issue list -R wailuen/a2a-sdk --search <redacted title>`, created with `gh issue create -R wailuen/a2a-sdk --body-file <tmp> --label auto-filed --label <component>`, at most 10 per run, with the URL written back to the file. Title and body use classified fields only (never `quote`), after credential-pattern redaction (`sk-`, `ak_`, tokens, bearer, long hex/base64); a candidate that still matches a secret pattern is neither searched nor filed. If `gh` is missing or unauthenticated the candidates stay in the file and the wave still finishes. Skills updated: `sdk-issue-scan`, `sdk-issue` (Rules: opt-in exception), `wave` (arg doc), in `harness/`, `.claude/` and the template. Ruling: https://github.com/wailuen/a2a-sdk/issues/223#issuecomment-6355273001. Template commit pushed to wailuen/a2a-agent-template: 0279e59373c1d58d0138760c3d198c54ca90e1cf. Known deferred item (not this change): `template/.claude/skills/wave/SKILL.md` and `.claude/skills/wave/SKILL.md` already drift from `harness/skills/wave/SKILL.md` (severity-floor wording, `agentBudget` doc, Unit/Phase Redteam and Archive bullets); only the GH-223 hunk was added to them. Tests: `tests/test_wave_cycle_behaviour.py`, `tests/test_sdk_wave_behaviour.py`.
- GH-222: confidential DCR. `POST /oauth/register` now honours `token_endpoint_auth_method` in `none` (default, unchanged), `client_secret_post` and `client_secret_basic`; any other value gets 400 `invalid_client_metadata`. A confidential registration returns `client_secret` once, plus `client_secret_expires_at: 0`; only its sha256 is stored (new `client_secret_hash` field, written for confidential clients only; public records keep their exact key set). `/oauth/token` (code and refresh grants) and `/oauth/revoke` without a Bearer read the required method from the stored client record and need the secret through exactly that method (form body, or `Authorization: Basic` with form-urldecoded id and secret); failure is 401 `invalid_client` (`WWW-Authenticate: Basic` for basic clients). A public client that presents a secret is refused. PKCE S256 stays mandatory. Metadata `token_endpoint_auth_methods_supported` is now `["none", "client_secret_post", "client_secret_basic"]`. Open-DCR secrets are a compatibility measure, not a trust boundary. Ruling: https://github.com/wailuen/a2a-sdk/issues/222#issuecomment-6355272603. Changed: `agent_sdk/routes/oauth.py`, `agent_sdk/auth/oauth_tokens.py` (`register_client` gains optional keyword args), `docs/security.md`, DESIGN.md. Tests: `tests/test_gh222_confidential_dcr.py`, `tests/test_gh152_idp_off_regression.py` (authorization-server metadata golden hash re-captured). Release-gate follow-up: an empty `client_secret` (form field or Basic `id:`) counts as not presented, so public clients from generic OAuth libraries still work; a secret presented for an unknown, evicted or malformed client record now fails closed with `invalid_client` (an unknown client with no secret still gets `invalid_grant`, so client existence is not disclosed); `invalid_client` names the Basic scheme whenever the caller used Basic.
- GH-210: `agent_sdk.testing.turns` (PROVISIONAL) adds `run_turn(...)`, `SlotLimiter` and the CLI `python -m agent_sdk.testing.turns --transport a2a|agui --base-url --key-file --run-key [--slots N] [--lock-dir] [--state-dir] [--budget]` (query from `ACC_QUERY`). Both names are exported from `agent_sdk.testing`. It limits concurrent turns across processes with file locks (default 3 slots) and retries HTTP 429, a failed task, an empty reply, and "too many requests" / "rate limit" text found in an error channel only (a failed A2A task message or an AG-UI `RUN_ERROR`, never a completed reply) with back-off inside a 540 s total budget that also bounds the attempt in flight (`reason: "budget-exceeded"`). The key is read from the key file only. A2A ids and the AG-UI message list are saved only after a successful attempt. `acceptance-api.js` (harness and template) calls the helper, tells scenario agents to run it with a Bash timeout of 600000 ms, and has a new failure class `rate-limited`: such results are forced to `passed=false`, reported as "not run", left out of min scores, and never turn into a pass; the acceptance skill documents it. Requires agent-sdk >=0.18.0 in the template. Changed: `agent_sdk/testing/__init__.py` (exports). Tests: `tests/test_gh210_testing_turns.py`.
- GH-204: `MCP_INTERRUPT_SUFFIX` is a new public constant in `agent_sdk.routes.mcp`. When a tool raises `ToolInterrupt` over MCP `tools/call`, the `isError` text is now the sanitized tool message followed by this suffix. The old fixed text is kept only as the fallback when the message is empty. Clients that matched the old fixed string should match the suffix instead. Tests: `tests/test_rt003_rt004_mcp_error_mapping.py`.
- GH-209: `agent_sdk.testing.mcp` (`McpClient`: initialize, paginated `tools/list`, `tools/call`; `run_gate`; CLI `python -m agent_sdk.testing.mcp`) and a new "Phase 1.5 — MCP tools gate" in the acceptance skill (`harness/`, `.claude/`, template). The gate checks `tools/list` (count equals registered tier-1 tools, every input field described, no `$ref`/`$defs`, size budget), then calls each `read_only=True` tier-1 tool once with its `sample=` args. Tools with `sample=None` or without `readOnlyHint` are skipped with a warning unless named by `--opt-in`; a GH-204 interrupt (`isError` text ending in `MCP_INTERRUPT_SUFFIX`) is "needs user input, skipped"; any other `isError` not on `--allow-error` stops acceptance, naming the tool and `sample=` args only. The client reads the key from a key file only. Requires agent-sdk >=0.18.0. Changed: `agent_sdk/testing/__init__.py` (exports). Tests: `tests/test_gh209_testing_mcp.py`.
- GH-220: AG-UI `RUN_ERROR` now carries a `code` field using the `ErrorCategory` vocabulary, and `RUN_FINISHED` now always carries `outcome: {"type": "success"}`. Both changes are additive. New public loop-event fields: `DoneEvent.code` and `ToolResultEvent.code` (`agent_sdk/agent/events.py`, both `str | None = None`, appended after all existing fields so positional construction is unchanged). Changed: `agent_sdk/agent/loop.py` and `agent_sdk/agent/runner.py` (set `code`), `agent_sdk/routes/ag_ui.py` (emits it). Tests: `tests/test_gh220_agui_run_error_code.py`.

### Fixed
- GH-219: the agent card now advertises the SDK's own OAuth authorization server as an `oauth2` security scheme (authorizationCode flow, `oauth2MetadataUrl`, scopes `{}`). `security` is now `[{"bearer": []}, {"oauth2": []}]`, and either one is enough. The URLs come from `resolved_base_url`, never from request headers. There is no `openIdConnect` scheme. The change is additive, so card consumers that compared `securitySchemes` for exact equality must allow the extra key. Changed: `agent_sdk/routes/agent_card.py`. Tests: `tests/test_gh219_agent_card_oauth2.py`, `tests/test_forwarding_integration.py`.
- GH-218: `/mcp/` (trailing slash) is now served by the same handlers as `/mcp` for POST, GET and DELETE, with no 307 redirect. Clients that drop the body or auth header on a redirect now work. Tests: `tests/test_gh218_mcp_trailing_slash.py`.
- GH-217: closing an AG-UI stream before the terminal frame now cancels the run through `cancel_task_record`. Runs parked on an interrupt and A2A `message:stream` are not cancelled. `cancel_task_record` is a new public helper in `agent_sdk/routes/a2a.py`; `agent_sdk/routes/ag_ui.py` calls it. The A2A send and stream self-check probes still cost one model turn each. Tests: `tests/test_gh217_agui_disconnect_cancel.py`.
- GH-208: wave runners no longer treat a returned implementer as a delivered group. After each Implement tier one script (`DELIVERABLE_GATE_PY` in `harness/workflows/wave-cycle.js` and `.claude/workflows/sdk-wave.js`, sharing the `SCOPE_SCAN_PY` path rule) checks every concrete `Creates:` path (file exists; an `acceptance` record needs `Verdict: PASS` and no `[pending`; pattern paths need a match newer than Implement start). A null or malformed result counts every path as missing. Failing groups go to `failedGroups` with a `<wave>-group-<label>-incomplete.md` note; groups depending on them (transitively) are pruned, skipped in unit redteam, and archive is blocked. `wave.groupDeps` is now unioned with deps read from each todo's `Depends:` line. The `Creates:`/`Modifies:` scan re-runs at the top of every unit and phase redteam round (new paths join `group.scope` and `wave.allScope`; a null scan is unknown, not clean). New explicit `HUMAN GATE:` todo marker plus `Release: <GitHub issue URL>` line holds a group; documented in `planner.md` and the todos/wave skills. Free text like `Status: NOT DONE` does not gate. Tests: `tests/test_wave_cycle_behaviour.py`, `tests/test_sdk_wave_behaviour.py`, `tests/test_wave_scope_extraction.py`.
- GH-211: redteam findings now carry a required `line` and `quote` (`RT_SCHEMA` in `harness/workflows/wave-cycle.js`, `.claude/workflows/wave-cycle.js`, `.claude/workflows/sdk-wave.js`, and the template copy). Before each fix round one script runs `grep -F` for every quote; findings whose quote is gone are dropped as stale and do not count as blocking or stop "clean". An empty quote or an untrustworthy check result keeps the finding. `redteam.md` (harness, `.claude/`, template) requires the quote and forbids re-raising a vanished line. Tests: `tests/test_wave_cycle_behaviour.py`, `tests/test_sdk_wave_behaviour.py`. LRN-455.
- GH-213: `A2uiCapabilities.from_metadata()` now accepts upstream A2UI v0.9.1's `{"v0.9": {"supportedCatalogIds": [...]}}` (client_capabilities.json), then a flat root `supportedCatalogIds`, when `catalogs` is absent or not a non-empty list, so clients using that key keep receiving domain surfaces under the GH-180 gate. `catalogs` wins when both are present. The fail-closed `gated()` default is unchanged. Closes w051 RT-008 and RT-011. Changed: `agent_sdk/a2ui/translator.py` (`A2uiCapabilities.from_metadata`), DESIGN.md §5.4, `docs/protocols.md`, `workspace/todos/deferred/w051-group-G1-medium-low.md`. Tests: `tests/test_gh213_supported_catalog_ids.py`.
- GH-216: the admin console AG-UI resume now builds its payload from `interrupt.responseSchema`. One property is coerced to its type (integer, number, boolean, enum); several properties get a small form; no schema stays `{decision: text}`. Bad input shows an error, sends nothing and keeps the interrupt. ActionGate still resumes as `{decision: "approved"}`. New module `agent_sdk/console/static/interrupt.js` exports `buildResumePayload`, `buildPayloadFromValues`, `formFields` and `coerceValue`. Changed: `agent_sdk/console/static/chat.js`, `tests/test_card_console.py` (the resume-payload pin moved from chat.js to interrupt.js). Tests: `tests/test_gh216_console_interrupt_schema.py`.
- GH-215: the admin console (`agent_sdk/console/static/a2ui.js`, `chat.js`) now renders unknown domain components bound to an object as a generic card: title from the component name, key/value rows for scalars, tables for arrays of objects, raw JSON in a collapsible block (no schema endpoint). Each message fold and each surface paint is wrapped in try/catch and pushes a note, so one bad message no longer stops later surfaces; `renderA2uiMessages` is guarded the same way. Relative JSON-Pointer paths are rejected with a note instead of folding to the model root. All list/table renderers share one `MAX_ROWS` cap (100) with an "N more" note. `sendA2a`/`sendAgui` await `loadCatalogIds()` so the first send carries the domain catalog ids. Tests: `tests/test_gh215_console_generic_renderer.py`.

## [0.17.6] — 2026-10-19

### Added
- GH-202: `CredentialStore.list_items(namespace)` (`agent_sdk/credentials/store.py`), a non-abstract method returning `{field: plaintext}` for a namespace. The default is `list_fields` + `get`, so existing subclasses keep working. Stores passed to `ApiKeyStore` must subclass `CredentialStore` (or provide `list_items`), because `list_keys()` and revoke now call it.

### Fixed
- GH-202: API-key store calls no longer block the event loop. With tens of thousands of keys on `AzureTableCredentialStore`, `GET /admin/api/keys` made one synchronous HTTP read per key on the loop and the whole agent (including `/health`) stopped answering for minutes. New non-abstract `CredentialStore.list_items(namespace)` (default: `list_fields` + `get`, so third-party stores are unaffected); Azure Table (`credentials/azure_table.py`) does one partition query and SQLite (`credentials/encrypted_sqlite.py`) one `SELECT`, with no cache use for reserved namespaces. `ApiKeyStore.list_keys()` and revoke's last-admin check make one `list_items` call; `count()` stays one names-only `list_fields` query (no decrypt). The admin list/revoke/overview routes (`routes/admin.py`) and every `api_keys.verify` call (`auth/middleware.py`, `routes/oauth.py`) now run via `asyncio.to_thread`. `verify` writes `last_used` only when it is unset or older than 60 s, so `last_used` is accurate to ~60 s. No pagination; response shape unchanged. The sync `resolve_identity()` keeps its signature (docstring notes it blocks). `auth/api_keys.py` also guards the threaded paths: `last_used` writes and revoke use per-key locks (a revoked key is never re-created by an in-flight `verify`, which re-reads the row before writing), a separate lock serialises the last-admin check, and a `last_used` write that finds its lock busy is skipped, so a slow admin revoke never stalls other keys. Tests: `tests/test_gh202_api_key_store_off_loop.py`, `tests/test_gh202_api_key_races.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/202#issuecomment-6259246006

## [0.17.5] — 2026-10-19

### Changed
- The OAuth sign-in error page and the "Returning to the app" hand-off page now use the same TPC-branded layout as the consent pages (new `render_notice_page` in `agent_sdk/routes/_consent_ui.py`): TPC mark, card, light/dark and phone layout. The hand-off page (used for `_HANDOFF_REDIRECT_ORIGINS`, e.g. Copilot Studio) keeps the identical meta refresh tag and gains a Continue button. Error messages are reworded in plain language (the technical name stays in brackets, e.g. "(unknown client)"). CSP, status codes and redirect behavior are unchanged. Agents get it by upgrading the SDK; no agent change needed. Tests: `tests/test_consent_page_design.py`.

## [0.17.4] — 2026-10-17

### Changed
- OAuth consent pages redesigned. Both the admin-key page (`GET /oauth/authorize`) and the IdP sign-in consent page now share one layout in `agent_sdk/routes/_consent_ui.py`: the TPC mark ("Built by TPC"), the agent's name (`settings.display_name`), a plain headline ("<client> wants to access <agent>"), what the app can do if allowed, the app / return host / resource details, clear primary and secondary buttons, and a short safety note. It follows the system light/dark setting and stacks for phone widths. The page stays self-contained under the unchanged consent CSP: inline style and an inline SVG mark only (`agent_sdk/routes/_tpc_logo.py`), no script, image fetch, font or external stylesheet. Form fields, actions and decision values are unchanged. Agents get it by upgrading the SDK; no agent change needed. Tests: `tests/test_consent_page_design.py`; the IdP-off golden page hash in `tests/test_gh152_idp_off_regression.py` was re-captured (headers, CSP and metadata goldens unchanged).

## [0.17.3] — 2026-10-17

### Fixed
- GH-201: `POST /mcp` sessions no longer evict each other when several clients share one credential. A successful `initialize` used to delete every session owned by the identity key (RTGA-010), and a shared API key or org-wide OAuth client has no user part in that key, so the clients kicked each other out (next call got 404). Now `initialize` evicts only the session it replaces (the presented, caller-owned `Mcp-Session-Id`), and an identity holds at most 200 live sessions by default, set by the new `AGENT_SDK_MAX_MCP_SESSIONS_PER_IDENTITY` (least-recently-used evicted first; other identities are never touched). The default matches the stream cap because an org-wide OAuth client or shared API key puts a whole org on one identity. A non-initialize request with no `Mcp-Session-Id` is now dispatched normally instead of getting 400 "Mcp-Session-Id required". This reverses RTGA-010's evict-all and the session-required 400. 404 for unknown, expired and foreign session ids is unchanged. Changed: `agent_sdk/routes/mcp.py`, `DESIGN.md` §5.5, mcp-advisor and mcp-check checklists. Tests: `tests/test_gh201_mcp_session_sharing.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/201#issuecomment-6234642337 and issuecomment-6235185280

## [0.17.2] — 2026-10-17

### Fixed
- GH-200: `POST /mcp` no longer returns 400 when `MCP-Protocol-Version` is absent on a non-initialize request. This reverses the GH-77 absent-header 400, which the spec does not require (it only requires 400 for an invalid or unsupported value). Microsoft Copilot Studio omits the header on `tools/list` after `initialize`, so it could not load tools. The server now records the negotiated version against the `Mcp-Session-Id` at initialize and uses it for an absent header (else `2025-03-26`). A present but unrecognized value still gets 400, now worded "unsupported MCP-Protocol-Version". Session checks are unchanged. Changed: `agent_sdk/routes/mcp.py`, `DESIGN.md` §5.5. Tests: `tests/test_mcp_gh77_absent_version_header.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/200#issuecomment-6234026443
- GH-200: the legacy `POST /mcp/messages` path now also words a present-but-unrecognized version 400 as "unsupported MCP-Protocol-Version". The mcp-advisor checklist and mcp-check skill no longer require the header on every post-init request.

## [0.17.1] — 2026-10-17

Resolves GH-199: brings the v0.15.3 Copilot Studio fix (7778751) to main, so agents on 0.15.3 can upgrade to 0.17.x without losing Copilot Studio sign-in.

### Fixed
- GH-199 (GH-198 follow-up): Copilot Studio's callback forwards across three origins (`global.consent.azure-apim.net` → `<region>.consent.azure-apim.net` → `copilotstudio.microsoft.com`), so the 0.17.0 `form-action` widening alone still let Chromium block the last hop. For the exact origin `https://global.consent.azure-apim.net`, the post-consent redirect (IdP consent, admin approve, error redirects) is now a 200 hand-off page with a meta refresh (`_HANDOFF_REDIRECT_ORIGINS`, `_client_redirect` in `routes/oauth.py`): a new navigation outside the form-submission chain and so outside `form-action`. Same CSP, `no-store` and `no-referrer` headers. Every other client keeps the 30x. Tests: `tests/test_oauth_flow.py`, `tests/test_gh152_idp_authorize_flow.py`. Decision: https://github.com/wailuen/a2a-sdk/issues/198#issuecomment-6229599836 (updated for the hand-off).

## [0.17.0] — 2026-10-17

Resolves GH-188 to GH-198. Contains one breaking change (GH-196: tools now reject unknown arguments); see Breaking changes for migration steps. GH-198 was also back-ported as 0.15.2.

### 🔴 Breaking changes
- GH-196: tool arguments the input model does not declare are now rejected with `ToolInputValidationError` instead of being silently dropped. This applies to the agent loop, MCP `tools/call`, the admin try-tool route and commitments. The advertised input schema says `additionalProperties: false` by default, and `true` only for a tool that opts in. Migration: add the missing field to the input model, or set `extra="allow"` on the model, or pass `allow_extra_args=True` to `@tools.tool`. Changed: `agent_sdk/agent/registry.py`, `agent_sdk/agent/loop.py` (validation message for unknown arguments), `docs/tools.md`, `harness/skills/add-tool/SKILL.md`. Tests: `tests/test_gh196_reject_unknown_tool_args.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/196#issuecomment-6229360794

### Added
- GH-194: `LoopPolicies.empty_reply_retry` (default `True`).
- GH-196: `@tools.tool(allow_extra_args=...)` parameter to let a tool accept undeclared arguments.
- GH-188: optional `emits` parameter on `supported_catalogs()` and `a2ui_extension()`.

### Changed
- GH-194: new `LoopPolicies.empty_reply_retry` (default `True`). After a tool result, when the model replies with no tool call and only blank text, the loop retries once with tools off and, if the reply is still empty, emits a fixed notice text instead of an empty answer. Changed: `agent_sdk/agent/loop.py`. Tests: `tests/test_gh194_empty_reply_retry.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/194#issuecomment-6229361165
- GH-188: the agent card `supportedCatalogIds` is now built from the catalogs of the registered tools' `emits` types. It may now be `[]`, or omit the Standard Profile when no tool emits its components. `supported_catalogs()` and `a2ui_extension()` take a new optional `emits` parameter. Changed: `agent_sdk/a2ui/catalog.py`, `agent_sdk/routes/agent_card.py`. Tests: `tests/test_gh188_catalogs_from_emits.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/188#issuecomment-6229361485
- GH-195: `ChatDriver.agui_resume` (provisional `agent_sdk.testing` API, additive) resumes an AG-UI interrupt from tests; on AG-UI the `interrupt` emit now receives the AG-UI interrupt dict. Changed: `agent_sdk/testing/chat.py`. Tests: `tests/test_gh195_chatdriver_agui_resume.py`.
- GH-189: `POST /v1/message:send` with `configuration.blocking: true` no longer returns 501 `-32004`. It now waits until the task is terminal or `input-required` and returns 200 with that Task (A2A v0.3.0 §7.1, `MessageSendConfiguration.blocking`). The wait is capped at `min(task deadline, AGENT_SDK_BLOCKING_SEND_MAX)` (new setting `blocking_send_max_seconds`, default 120 s); on the cap it returns the current non-terminal Task and the worker keeps running (poll `tasks/get`). A blocking resume (`taskId`) waits the same way. The wait uses the shared stream admission slots and always releases its subscription, including on client disconnect. `blocking: false` or absent keeps the immediate snapshot. Changed: `agent_sdk/routes/a2a.py`, `agent_sdk/config.py`, `docs/protocols.md`, `DESIGN.md`. Tests: `tests/test_gh189_blocking_send.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/189#issuecomment-6229360257

- GH-193: an A2A resume of an interrupt-state task (`message:send` and `message:stream`) may now carry exactly one `DataPart` whose `data` is an object and no other parts, so a structured answer to a `responseSchema` interrupt reaches `resume_handler` as `{"status": None, "payload": <data>}` (the AG-UI resume shape) inside `ResumeEnvelope`. The GH-159 non-text check still applies to fresh messages (DataPart/FilePart -> `-32005`/415). A text-only resume still delivers a plain `str`. A resume with a FilePart is refused `-32005`; more than one part alongside a DataPart, or more than one DataPart, or non-object `data` is refused `-32602`; errors name the part kind only. The part check runs after the task-state checks, so a DataPart resume on a missing, working or terminal task gets the same error as a text resume. `action_gate` needs no change: `payload.decision` approves, `payload.status` never does. The example `publish_note` handler also reads `payload.status`. Changed: `agent_sdk/routes/a2a.py`, `agent_sdk/example/agent.py`, `docs/protocols.md`. Tests: `tests/test_gh193_data_part_resume.py`, `tests/test_gh185_current_identity.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/193#issuecomment-6229360550

### Fixed
- GH-190: `POST`/`GET /v1/tasks/{id}/pushNotificationConfigs` and `GET`/`DELETE /v1/tasks/{id}/pushNotificationConfigs/{configId}` now return 501 `-32003` PushNotificationNotSupported (A2A v0.3.0 HTTP+JSON push-config methods; card `pushNotifications: false`) instead of 404 `-32601` / 405 `-32004`. Identity and origin guard required; same reply for known, foreign and unknown tasks; body never read. Changed: `agent_sdk/routes/a2a.py`, `docs/protocols.md`. Tests: `tests/test_gh190_push_config_not_supported.py`.
- GH-198: the OAuth consent-page CSP `form-action` now also allows known redirect hops (`_KNOWN_REDIRECT_HOPS`); the Azure APIM global consent host 302s to a regional host (e.g. `asia-001.consent.azure-apim.net`), so `https://*.consent.azure-apim.net` is allowed for that exact origin. Changed: `agent_sdk/routes/oauth.py`. Tests: `tests/test_oauth_flow.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/198#issuecomment-6229360049
- GH-191: the admin console chat no longer retries 4xx responses, honours `Retry-After` for 429/503 (capped at 30 s), and never re-POSTs `/ag-ui/run` after a stream drop (a re-POST would start a second run). New module `agent_sdk/console/static/retry.js`. Changed: `agent_sdk/console/static/chat.js`. Tests: `tests/test_gh191_console_retry_policy.py` (now also syntax-checks every console JS file with node).
- GH-197: `message:stream`, the interrupt-resume stream and `tasks/{id}:subscribe` now send `: ping` SSE comment frames whenever nothing is queued for 15 s, so a long tool no longer leaves the stream silent and short-timeout clients stay connected. The first full-Task frame and the `final: true` ending are unchanged; queued items are never dropped. The interval is the shared `agent_sdk.common.sse.STREAM_HEARTBEAT_SECONDS`, also used by AG-UI. `harness/workflows/acceptance-api.js` now uses a 600 s read timeout on both clients. Changed: `agent_sdk/routes/a2a.py` (`_open_stream`), `agent_sdk/routes/ag_ui.py`, `agent_sdk/common/sse.py`. Tests: `tests/test_gh197_a2a_stream_heartbeat.py`.
- GH-192: `/ag-ui/run` with a body that is not JSON, or is JSON but not an object (array, scalar, `null`), now returns 200 SSE with RUN_STARTED (synthesized ids) then RUN_ERROR `malformed RunAgentInput body`, instead of the misleading "no user message in input". The message is fixed text; the body is never echoed. No 400/422 before the stream (DESIGN.md §5.3 unchanged). Changed: `agent_sdk/routes/ag_ui.py` (`_parse_body` returns `None` on malformed input; the generator checks it first). Tests: `tests/test_gh192_ag_ui_malformed_body.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/192#issuecomment-6229361690

## [0.15.3] — 2026-10-17

Back-port patch on branch `release/0.15.x` (tag `v0.15.3`), not on main. Contains the GH-198 meta-refresh hand-off listed under 0.17.1.

## [0.15.2] — 2026-10-17

Back-port patch on branch `release/0.15.x` (tag `v0.15.2`), not on main. Contains only the GH-198 fix listed under 0.17.0, for agents still on 0.15.x.

## [0.16.0] — 2026-10-17

Resolves GH-185 (new `current_identity()`) and GH-187 (retry after a failed task).

### Added
- GH-185: `agent_sdk.auth.current_identity() -> Identity | None` (new module `agent_sdk/auth/context.py`, exported from `agent_sdk/auth/__init__.py`). A tool or `SourceAdapter` can read who is calling. It is bound at `routes/a2a.py` (`message:send`, `message:stream`, interrupt resume), `routes/ag_ui.py` (`/ag-ui/run`, including resume) and `routes/mcp.py` (`POST /mcp`, `/mcp/messages`). On resume the already-running worker rebinds to the resuming caller (`agent/runner.py`, `run_task_worker.wait_resume`; the identity travels inside the resume future's value as a `ResumeEnvelope`, so concurrent resumers cannot overwrite it), so a tool that runs after a resume sees the resumer, not the original submitter. `tasks/resubscribe` is also bound, per the maintainer ruling. Returns `None` outside a request. Only the `Identity` is held; it is never logged. Tests: `tests/test_gh185_current_identity.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/185#issuecomment-6217407102

### Fixed
- GH-187: a new task in an existing `contextId` is now seeded only from the most recent COMPLETED task (`context_messages()`), and `context_reusable_messages()` only reuses `__resolved__` markers from COMPLETED tasks. FAILED, CANCELED and REJECTED tasks are skipped entirely, including their user message. Before, a task that failed part-way (e.g. a model 429 after a tool round) left tool results in its transcript; the retry inherited them, answered from the stale results, called no tool, and so emitted no data part or A2UI card. Accepted trade-off: a bare "try again" after a failure has no memory of the failed request, so the user must restate it. A context whose only prior tasks failed starts fresh. Changed files: `agent_sdk/tasks/memory.py`, `agent_sdk/tasks/store.py`. New tests: `tests/test_gh187_retry_after_failed_task.py`. Ruling: https://github.com/wailuen/a2a-sdk/issues/187#issuecomment-6217406480

## [0.15.1] — 2026-10-16

Resolves GH-183 and GH-184 (harness skills only; no `agent_sdk` code change).

### Fixed
- GH-183, GH-184: the `/acceptance` and `/agent-verify` service-key mint step is now one command whose response never reaches the transcript. It pipes into a small parser that requires `"service": true` (otherwise revokes any returned key and stops with "this SDK does not support service keys; upgrade to v0.15.0+"), writes the key to a mode-600 file, and prints only `key_id` (`/acceptance` also prints the key file path, which is not secret). `/acceptance` writes into a fresh `mktemp` file, opened with `O_NOFOLLOW` and refused unless it is owned by the caller with mode 600. The `template/` copies are published; the acceptance copy keeps its one allowed difference, a live `scriptPath` of `.claude/workflows/acceptance-api.js`. New tests: `tests/test_gh183_184_service_key_mint_step.py` (including whole-file harness/template parity with that allow-list, and a check that the template copies are committed and pushed).

## [0.15.0] — 2026-10-15

Resolves GH-181 (neutral A2UI prompt wording) and GH-182 (new `service` API key kind).

### Added
- GH-182: `service` API key kind. An admin mints one with `POST /admin/api/keys` (`service: true`, mutually exclusive with `admin`; the bootstrap mint stays admin-only). A service key passes `require_identity` on A2A, AG-UI and MCP even with `AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS=true`, and is refused wherever `require_admin` applies. `GET /admin/api/keys` and the console show the kind; stored records without the field load as normal keys. `/acceptance` and `/agent-verify` mint a service key, use only it for protocol calls, and revoke it at teardown. Ruling: https://github.com/wailuen/a2a-sdk/issues/182#issuecomment-6193941983
- `agent_sdk.auth.Identity.service` (public, trailing field, default `False`).
- New tests: `tests/test_gh182_service_key.py`.

### Changed
- GH-182 (security): `POST /oauth/revoke` — a service key no longer revokes another client's OAuth token; it gets the usual silent HTTP 200 and nothing is revoked (RFC 7009 §2.2). Admin and normal API keys keep today's behaviour. oauth-kind callers still revoke only their own tokens.
- GH-181: the A2UI system-prompt section no longer tells the model to describe tool results "in prose". It now says to summarise tool results for the user in the format the agent's instructions ask for, so persona format rules (e.g. markdown tables) are respected. The safety rules (cards delivered automatically, no component JSON, only values the tools returned) are unchanged, as are the MarketBriefing prose-card notes. No new setting.
- New tests: `tests/test_gh181_prompt_format_neutral.py`.

## [0.14.1] — 2026-10-15

Resolves GH-180 (A2A catalog negotiation). Ruling: https://github.com/wailuen/a2a-sdk/issues/180#issuecomment-6192926900

### Changed
- GH-180 (behaviour change for A2A clients): `A2uiCapabilities.allows()` now returns False for a domain model whose `catalog_id` is not in the client's declared `catalogs`, so the A2A DataPart carries only the text and raw-data fallback for it. A client that opts in without a usable `catalogs` list gets the Standard Profile only, so it no longer receives undeclared domain catalogs. **Migration:** list the domain catalog IDs from the agent card (`supportedCatalogIds`) in `a2uiClientCapabilities.catalogs`. AG-UI CUSTOM emission is unchanged (`for_custom_emit()`). The admin console now declares every catalog ID on the agent card. `A2uiCapabilities` gains an optional `any_catalog` field (default False).
- New tests: `tests/test_gh180_a2a_catalog_negotiation.py`.

## [0.14.0] — 2026-10-15

Resolves GH-174 through GH-177, GH-179 (pre-existing items from the w049 protocol audit) and the code part of GH-178. GH-176, GH-177 and GH-179 (3, 5) are breaking; see Breaking changes.

### 🔴 Breaking changes
- GH-176: `register_content_type` (`agent_sdk/models/content_types.py`) now refuses to boot when a card's `component` equals one of the 18 Basic Catalog primitives (`Text`, `Card`, `Column`, `Row`, `List`, `Tabs`, `Button`, `Image`, `Icon`, `Video`, `AudioPlayer`, `Divider`, `Modal`, `CheckBox`, `TextField`, `DateTimeInput`, `ChoicePicker`, `Slider`) ignoring case (`Card`, `Textfield`, `checkbox` are all refused). The error names the card and the clash. The new `BASIC_CATALOG_COMPONENTS` tuple lists the names. The type and PascalCase check also now runs first, so `component=5` raises the documented `ValueError`. Ruling: https://github.com/wailuen/a2a-sdk/issues/176#issuecomment-6187889280. **Migration:** rename the domain card's `component` to a name that is not a primitive, for example `InfoCard` instead of `Card`.
- GH-177: `DocumentItem.wire()` (`agent_sdk/models/content_types.py`) emits only the Profile v1.1 contract keys (`id, name, type, modified, link, size`) plus the documented SDK extension `modified_by`. `web_url` fills `link` and `last_modified` fills `modified` when the contract key is empty; **wire change (breaking):** the keys `web_url` and `last_modified` are no longer emitted. Both stay readable on the model. The compact schema teaches contract keys only and the console renderer reads `modified`/`link` (see Fixed). When both `modified` and `last_modified` are set and differ, `last_modified` is on no wire key at all: it stays readable on the model (`doc.last_modified`) and in the plain-text fallback, which adds a `    last modified: <value>` line under `    modified: <value>`. Ruling: https://github.com/wailuen/a2a-sdk/issues/177#issuecomment-6187888894. **Migration:** read `link` instead of `web_url` and `modified` instead of `last_modified` on the wire; the model attributes are unchanged. A producer that sets both fields with different meanings (for example `modified` = a period end and `last_modified` = an upload date) must put the date its clients need in `modified`, or the other date is visible only in `content[0].text`.
- GH-179 (3): a non-finite value in `ComparisonTable.rows` or `CategoryValue.metadata` is now rejected with a `ValidationError`, so `wire()` and `to_plain_text()` agree (no `nan`/`inf` in text, no `null` on the wire). Ruling: https://github.com/wailuen/a2a-sdk/issues/179#issuecomment-6187889614. **Migration:** clean or drop `nan`/`inf` values before building these models, or catch the `ValidationError`.
- GH-179 (5): `MarketBriefing.wire()` now returns the `to_markdown()` string (type-ignored override of `dict[str, Any]`). The translator and MCP special cases are unchanged. The AG-UI `AGENT_ARTIFACT` frame is unchanged for this card: `data` stays the field dict, the same as the A2A `DataPart` without A2UI. `_validate_a2ui_wire` (`agent_sdk/agent/runner.py`) now accepts a non-empty `str` from a `MarketBriefing` subclass that has its own `catalog_id`; other domain cards must still return a non-empty dict. Ruling: https://github.com/wailuen/a2a-sdk/issues/179#issuecomment-6187889614. **Migration:** any Python caller of `MarketBriefing.wire()` must expect a `str`, not a dict.

### Added
- GH-179 (9): `agent_sdk.common.json_strict.dumps_strict(obj) -> str` (compact separators, `ensure_ascii=False`, `allow_nan=False`; raises `ValueError` on a non-finite float or on a string that cannot be encoded as UTF-8, such as a lone surrogate, so its output is always safe to `.encode("utf-8")`). The outbound counterpart of `loads_strict`; stable for domain code that writes its own JSON, but not part of the frozen core API.
- GH-174: `agent_sdk.common.redact.safe_label_text(value, *, neutralise, max_len=256)` (`agent_sdk/common/redact.py`). Like `safe_line_text` but keeps ASCII `( ) ,` and swaps only the named separator, line breaks and control characters. Helper used by `agent_sdk/models/content_types.py`; stable for domain cards that render their own label slots, but not part of the frozen core API.
- GH-175: `agent_sdk.common.redact.TITLE_TEXT_MAX_LEN` (1024, cap for title slots) and `LINE_TEXT_CUT_MARKER` (`…`, appended when a standalone slot is cut). Constants read by `safe_line_text`; stable, read-only values.
- GH-176: `agent_sdk.models.content_types.BASIC_CATALOG_COMPONENTS`, the tuple of the 18 Basic Catalog primitive names that `register_content_type` refuses. Stable public constant.
- New tests: `tests/test_gh174_label_ascii.py`, `tests/test_gh175_title_cap_marker.py`, `tests/test_gh176_basic_catalog_names.py`, `tests/test_gh177_document_contract_keys.py`, `tests/test_gh179_conformance_drift.py`.

### Changed
- GH-178 (code part): removed the unused `_Wire._rejects_non_finite` opt-out flag. A downstream subclass that still sets it now has a plain unused attribute (no effect, no error). Float fields are always checked (non-nullable reject, nullable coerce to `None`).
- GH-179 (1): `EntityList.title`/`showing`, event-level `CalendarEvent.is_online`, `ColumnDef.unit`/`highlight` and `ComparisonTable.sort_by`/`sort_order` are documented as SDK extensions in the docstrings and in `docs/content-types.md`. Wire output is unchanged (maintainer ruling: https://github.com/wailuen/a2a-sdk/issues/179#issuecomment-6187889614).
- GH-179 (2): in `agent_sdk/a2ui/catalog.py`, compact schemas now teach KpiCard `change_pct?`, TimeSeriesChart `subtitle?` and `data[].value` as `num|null`.
- GH-179 (6): few-shot examples in `catalog.py` show only the resolved data object (no `component` key); the heading says so.
- GH-179 (7): the fallback field summary shows `Literal` values (`"a|b"`), list element types (`[str]`) and every union arm (`int|str`); the prompt legend explains `|null`.

### Fixed
- GH-175: a cut standalone text slot now ends with a visible `…` that counts within the cap, through `safe_line_text` (and so `safe_label_text`). Card titles and other title slots get a 1024-char cap (`TITLE_TEXT_MAX_LEN`); names and other standalone slots stay at 256 (`LINE_TEXT_MAX_LEN`). A title of 1024 chars or fewer is unchanged. Ruling: https://github.com/wailuen/a2a-sdk/issues/175#issuecomment-6187888514.
- GH-174: `ColumnDef.label` (ComparisonTable header) and `MetricItem.label` (KpiCard rows) keep ASCII `( ) ,` as written, through the new `agent_sdk.common.redact.safe_label_text`. Only `|` (header) or `:` (metric row), line breaks and control characters are neutralised. Ruling: https://github.com/wailuen/a2a-sdk/issues/174#issuecomment-6187888176. **Text-format change**: `IRR (%)` used to render `IRR （%）` and now renders `IRR (%)`. Other author-written labels still render through `safe_cell_text` (via `_sanitize_cell`) and were NOT moved: `WaterfallSegment.label`, the MarketBriefing `KPI {BriefingKpiItem.title}:` line, `MetricItem.unit` (so `USD (m)` still renders `USD （m）`), `BarItem.category`, and the MarketBriefing chart and table titles. They are kept as data-style cells for now because the ruling named only the two label fields; moving them is a follow-up if the maintainer wants it.
- RT-001 (w050): a tool result or response holding a string that cannot be encoded as UTF-8 (a lone surrogate, for example from an upstream API that cut an emoji in half) no longer crashes the writer. Before, the legacy MCP SSE stream died with `UnicodeEncodeError` and the client never got a reply, and MCP Streamable HTTP returned a bare HTTP 500. `dumps_strict` now refuses such a string with a fixed-text `ValueError`, so the existing fallbacks answer: MCP `tools/call` returns an `isError` result (`tool output not serializable`), any other MCP response a -32603 `internal error`, A2A a -32006 `invalid agent response`, and AG-UI a `RUN_ERROR`. The character is never echoed. Test: `tests/test_rt001_lone_surrogate_writers.py`.
- RT-001/RT-002 (w050 rounds 5 and 6): such a string no longer makes a stored task unreadable. Before, the "must encode as UTF-8" rule lived only in the writers, so a value got stored that no later read could write: GET /v1/tasks/{id} and GET /v1/tasks then answered 502 -32006 for that whole identity. The rule now applies at every point that puts text into a task. (1) Ingress: `loads_strict` refuses any decoded key or value that is not UTF-8-encodable (a `"\ud800"` escape, or raw surrogate bytes) with the same fixed-text `json.JSONDecodeError` as other bad JSON. A2A `message:send`/`message:stream` answer 400 -32700 before any task or worker exists; AG-UI answers `RUN_STARTED` then one `RUN_ERROR` (before, a bad `threadId`/`runId` crashed the stream with no terminal frame); MCP answers -32700; OAuth dynamic client registration (`POST /oauth/register`, `agent_sdk/routes/oauth.py`, no code change there) answers 400 `invalid_client_metadata`. (2) `build_artifact`'s pre-commit check now calls `dumps_strict`, so a tool result holding a lone surrogate fails the task (-32006) instead of committing it COMPLETED while the stream sent a FAILED tail. (3) Status commit: `set_task_status` and `_agent_message` (`agent_sdk/agent/runner.py`) replace every surrogate code point in status and history text, message metadata and error text with U+FFFD (new `agent_sdk.common.json_strict.scrub_unencodable`, internal helper). This covers model text (`TextEvent`), `ProgressEvent`, `NoteEvent`, `ToolProgressEvent`, interrupt and failure messages: the task keeps running and the stream carries the replaced text. (4) Reads: `tasks/list` serializes each task on its own, so one record that still cannot be written (stored before this fix, or by a durable store) no longer fails the whole page; unencodable text is replaced with U+FFFD and a record that still cannot be written is left out and logged by id. `tasks/get` and the other non-stream A2A answers apply the same U+FFFD fallback before giving -32006. AG-UI's `RUN_STARTED` write now goes through the guarded frame writer too. A tool result is the one producer that still fails the task rather than being replaced: it is structured data, and silently changing it could change its meaning. Test: `tests/test_rt_w050_lone_surrogate_state.py`.
- GH-179 (8): the class-keyed `functools.cache` memos for float-field plans are weak-keyed, so a dynamically built model subclass can be garbage collected.
- GH-179 (9): in `agent_sdk/routes/a2a.py`, A2A non-stream responses (`message:send`, `tasks/get`, `tasks/list`, `tasks/cancel`) go through one new helper, `_strict_json_response`, built on `dumps_strict`. The A2A, SSE (`sse_data` in `agent_sdk/common/sse.py`) and MCP (`agent_sdk/routes/mcp.py`) writers now share this one serializer. SSE frames and MCP Streamable HTTP bodies are byte-for-byte unchanged. **Wire change:** the legacy MCP HTTP+SSE transport (`/mcp/messages` replies on `/mcp/sse`) used `json.dumps` with default separators and `ensure_ascii=True`; it now writes compact JSON (`,`/`:` with no spaces) with non-ASCII characters as raw UTF-8 instead of `\uXXXX` escapes. Both are valid JSON and parse to the same value. A non-finite value that bypassed validation returns a fixed -32006 `invalid agent response` (HTTP 502) instead of HTTP 500, except on `tasks/list`, which leaves that one task out of the page (logged by task id) so the other tasks stay readable (w050 RT-001 round 6).
- GH-177 (console): `agent_sdk/console/static/a2ui.js` `renderDocumentList` now reads `modified` first and falls back to `last_modified`, and renders the document name as a link from `link` (falling back to `web_url`). Only an absolute `http:` or `https:` URL becomes an `href` (new `safeHttpUrl`); `javascript:`, `data:`, relative and unparsable values render the name as plain text. The anchor is built through `el()` with text nodes only and opens with `rel="noopener noreferrer"`. Tests in `tests/test_gh177_document_contract_keys.py` run the real renderer under node.
- GH-177 (transcript): the model's own copy of a tool result (`agent/loop.py::fold_result_content`) still carries `web_url` and `last_modified`; only client-facing output uses the contract keys. It passes the new serialization context key `agent_sdk.models.content_types.TRANSCRIPT_DUMP_CONTEXT` (internal) to `model_dump` (w050 RT-001 round 8).
- GH-177 (text): `DocumentList.to_plain_text()` keeps `    modified: <modified or last_modified>` and adds `    last modified: <last_modified>` when both are set and differ, so the `last_modified` value the wire no longer carries still shows somewhere (w050 RT-002). It also adds `    modified by: <modified_by>` when set.
- GH-179 (5, AG-UI): `agent_sdk/routes/ag_ui.py` has a new `MarketBriefing` branch in the artifact mapper; the `AGENT_ARTIFACT` frame `data` stays the field dict (`model_dump`), since `wire()` is now a string.
- GH-179 (4): verified only; done in GH-176.
- GH-178: `docs/content-types.md` ("Non-finite numbers (GH-173)") said `BriefingKpiItem` rejects non-finite values in both cases. The code, and the 0.13.0 entry, are right: `BriefingKpiItem.value` rejects a non-finite value, and `delta`, like every nullable float, becomes `None`. Docs only; no code change.

## [0.13.0] — 2026-10-15

Resolves GH-171 (fallback schema `?` marks), GH-172 (component names must be unique PascalCase) and GH-173 (non-finite numbers). GH-172 and GH-173 are breaking; see Breaking changes.

### 🔴 Breaking changes
- GH-173: non-nullable `float` fields on built-in AND domain `ContentModel`/`_Wire` subclasses now reject non-finite values (`nan`, `inf`, `-inf`) with a `ValidationError` that names the field and never echoes the value (`BarItem.value`, `WaterfallSegment.value`/`cumulative`, `CategoryValue.value`, numeric `MetricItem.value`, and any domain card's `float` field). A tool that returned such a value used to produce invalid JSON (`NaN`); it now fails its output. Nullable fields (`float | None`, `int | None`) coerce non-finite to `None` instead, including `BriefingKpiItem.delta`, which used to reject (GH-95). `_Wire` models now hide the input value in validation errors, and the GH-95 `ValueError` text is now `non-finite float not allowed` (SI-2). Authority: maintainer ruling https://github.com/wailuen/a2a-sdk/issues/173#issuecomment-6182565586. **Migration:** make the field `float | None` to get coercion to `null`, or clean non-finite numbers before building the model.
- GH-172: `register_content_type` now refuses to boot when a component name does not match `^[A-Z][A-Za-z0-9]*$`, or equals a reserved or already-registered component name ignoring case. Before, `KPICard` registered next to the frozen `KpiCard`, `tradeactivity` next to the reserved `TradeActivity`, and snake_case names like `my_card` registered; A case-sensitive client silently drops the case variant. Authority: maintainer ruling https://github.com/wailuen/a2a-sdk/issues/172#issuecomment-6182565843. The `ValueError` names the offending component and, for a clash, the existing name. Re-registering the same class stays a no-op. **Migration:** rename the card to a unique PascalCase component name.

### Added
- GH-173: `agent_sdk.common.json_strict.loads_strict(raw)` (new module `agent_sdk/common/json_strict.py`). It works like `json.loads` but raises `json.JSONDecodeError` for anything that would decode to a non-finite float: the bare literals `NaN`, `Infinity` and `-Infinity`, and number literals that overflow a double, such as `1e999` or `-1e400` (plain `json.loads` turns these into `inf`). An integer literal longer than Python's digit limit raises the same error instead of a bare `ValueError`. The message is fixed and never echoes the token (SI-2). Every protocol ingress uses it (see Fixed). Internal helper: not part of the stable public API.

### Fixed
- GH-173: non-finite floats no longer reach the wire as invalid JSON (`NaN`). Built-in models coerce or reject at validation (see Breaking). The artifact check in `build_artifact` (`agent_sdk/agent/runner.py`) and `sse_data` (`agent_sdk/common/sse.py`) now use `allow_nan=False`, so on A2A and AG-UI a value that bypasses validation (assigned after construction, `model_construct()`, or a plain `float('nan')` returned by a tool) fails the task with -32006 instead of streaming `NaN`. MCP has no task: there, a `tools/call` whose output cannot be written as strict JSON returns an `isError: true` result with the fixed text `tool output not serializable` (MCP §5.5), on both `POST /mcp` and the legacy `/mcp/messages` path. Any other MCP response that cannot be written becomes a fixed -32603 `internal error` for the same id. Before, `POST /mcp` answered with a bare HTTP 500 and `/mcp/messages` never sent a reply. New `tests/test_gh173_mcp_non_finite_output.py`. Request bodies containing the bare literals `NaN`, `Infinity` or `-Infinity` (not JSON per RFC 8259), or a number that overflows to infinity such as `1e999`, are now rejected at every protocol ingress through one shared parser, `agent_sdk/common/json_strict.loads_strict`: A2A `/v1/message:send` and `/v1/message:stream` (`agent_sdk/routes/a2a.py`) return a -32700 parse error, MCP `POST /mcp` and `/mcp/messages` (`agent_sdk/routes/mcp.py`) return a JSON-RPC -32700 parse error, `/oauth/register` (`agent_sdk/routes/oauth.py`) returns `invalid_client_metadata`, and AG-UI (`agent_sdk/routes/ag_ui.py`) treats the body as invalid. Before, the A2A stream accepted `{"metadata":{"x":NaN}}` and then died mid-body with no `final:true` frame. As a second guard, the A2A stream generator (`_open_stream` in `agent_sdk/routes/a2a.py`) now closes with one `final:true` `failed` status-update (-32006, fixed text) if any frame still cannot be serialized. The AG-UI run generator (`agent_sdk/routes/ag_ui.py`) gets the same guard: every frame, including the `STATE_SNAPSHOT` that echoes the client's `state`, is written through one encoder that, on a frame it cannot serialize, closes the run with exactly one `RUN_ERROR` (fixed text) — also when the bad frame was the `RUN_FINISHED` itself. New `tests/test_gh173_non_finite_values.py`; three old "accepts non-finite" tests in `tests/test_content_types.py` were inverted.
- GH-171: the fallback field summary taught to the model for a registered content type (one with no hand-written compact schema) no longer marks a required-but-nullable field optional. `?` now comes only from `FieldInfo.is_required()`, so `a: str | None` with no default reads `a: str|null` and `b: str | None = None` reads `b?: str|null`. The summary also no longer cuts at 247 characters: over 250 characters it drops whole optional fields from the end, never a required field, and appends `...` when anything was dropped. Built-in `_COMPACT_SCHEMAS` are unchanged. Change is in `agent_sdk/a2ui/catalog.py` (`_field_summary`). New `tests/test_gh171_fallback_schema_required.py`, which also checks the `get_system_prompt_section()` output.

## [0.12.1] — 2026-10-14

Resolves GH-170 (A2UI `CalendarEvent.location` always carries `display_name` and `is_online`). No breaking change.

### Fixed
- GH-170: `EventLocation.display_name` now defaults to `""` and `is_online` to `False` (were `None`), so `CalendarEvents` wire output always carries both keys that Standard Profile v1.1 requires on `CalendarEvent.location`. Before, `EventLocation(join_url="u")` emitted only `{"join_url": "u"}` and failed the Profile's required-key check. Per the maintainer ruling (https://github.com/wailuen/a2a-sdk/issues/170#issuecomment-6143894937) the fields are not made required: input that omits them stays valid, and `EventLocation()` still validates. Additive, not breaking: the wire gains two keys and removes none, and an explicit `None` for `display_name` or `is_online` is treated as the default (`""` / `False`) so callers that pass upstream nulls keep validating. The compact schema taught to the model now reads `location?:{display_name:str,is_online:bool,join_url?:str}`. Plain text is unchanged (no ` @ ` for an empty `display_name`, no `[online]` for `is_online=False`). New `tests/test_gh170_profile_required_keys.py` compares the required keys in every Standard Profile compact schema (nested objects included) with the Profile field contracts and with what `wire()` emits for a minimal instance. It found no other mismatched card type, so `CalendarEvents` is the only type changed.

## [0.12.0] — 2026-10-13

Resolves GH-160 to GH-169. GH-161 is breaking: every `oidc` sign-in now needs a role, a group or the explicit opt-out. Known pre-existing protocol issue filed for a follow-up: GH-170.

### Added
- GH-163: an operator can now cut off one signed-in person. `OAuthTokenStore.list_identities()` returns one summary per user (user, client ids, family count, earliest created, latest expiry; no token values or hashes) and `revoke_user(user)` revokes all of that user's refresh families, drops their access tokens in this process and returns the family count. It also burns that user's unredeemed auth codes, and the admin route drops their pending IdP consent tickets, so a sign-in already in flight cannot mint a new family after the revoke. New admin-only routes `GET /admin/api/oauth/identities` and `DELETE /admin/api/oauth/identities/{user}` (URL-encode the `tid:oid`; idempotent, `{"user", "revoked"}`); the revocation is logged with the sanitized user id and the family count, never token material. The console API Keys tab has a "Signed-in users" panel with a Revoke button. Caveat (GH-162): access tokens are kept in memory per process, so with several workers a revoked user's access token still works on the other workers until it expires (at most 1 hour); refresh fails everywhere at once.
### Changed
- `uv.lock` resynced to the current package version (0.8.0 to 0.11.0) with a `tzdata` refresh. No dependency change. Declared in todo w047 (GH-168 file list).
- GH-167: standalone slots of `to_plain_text()` keep ASCII, per the maintainer ruling (https://github.com/wailuen/a2a-sdk/issues/167#issuecomment-6137225466). New `agent_sdk.common.redact.safe_line_text(value, *, max_len=256)` collapses line breaks and control characters, strips surrounding whitespace and caps length, but does not swap `( ) [ ] < > = , : |` for look-alikes. Every title, name, summary and as-of header that sits alone now uses it: `TimeSeriesChart`, `BarChart`, `EntityList`, `WaterfallChart`, `MultiCategoryChart` titles; `KpiCard` and `ComparisonTable` titles (full ASCII, so `Q3: Revenue` stays as written; their rows are now indented so a column-0 title cannot imitate one); `EntityList` item names (256-char cap) and summaries (no cap); `UserList`, `UserProfile` (and manager), `DocumentList` names and `CalendarEvents` subjects; `MarketBriefing` title and as-of. So `Toshiba (Tokyo)` and `Smith, John` render unchanged. Values joined with other text (table cells, `label: value` details, `k=v`, dates, `EmailList` rows and previews) still use `safe_cell_text`, whose behavior is unchanged. **Text-format change** (readers that parsed the old one-line shapes must read the new lines): `EntityList` item `  - Name` then `    id: <id>` (was `  - Name (id)`); `UserList` user `  - Name` / `    email: <email>` / `    title: <job title>` (if set) / `    id: <id>` (was `  Name <email> (id: <id>) — title`); `UserProfile` `Name` / `  email: <email>` / `  id: <id>` and `  manager: Name` / `    email:` / `    id:` (was `Name <email> (id: <id>)`); `DocumentList` `  - Name` / `    type:` / `    modified:` (if set) / `    id: <id>` (was `  Name (type)  date (id: <id>)`); `CalendarEvents` `  - Subject` / `    start – end @ place [online]` / `    id: <id>` (was `  start – end: Subject @ place (id: <id>)`); `MarketBriefing` header `Title` then `as of: <as_of>` (was `Title (as_of)`; this is also the `to_markdown()` wire value); `KpiCard` metric rows `  label: value [unit]` with `    trend: ...` under them (was `label: value` / `  trend: ...`); `ComparisonTable` header, rule and data rows each indented two spaces (were at column 0). `EmailList` rows are unchanged.

### 🔴 Breaking changes
- GH-161: `AGENT_SDK_OAUTH_IDP=oidc` now needs `AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE`, `AGENT_SDK_OAUTH_IDP_REQUIRED_GROUP` or `AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS=true` for every issuer, Entra GUID issuers included. Before, a GUID-pinned Entra issuer booted with no check and admitted every member and guest of the tenant unless "Assignment required" was on, which the SDK cannot see. The message names settings only. The personal-account tenant GUID is still refused. ADR a003 D14 supersedes the D13 Entra exemption. **Migration:** set a role or group (and assign users in Entra), or set the opt-out `AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS=true` (logs one boot WARNING).

### Security
- GH-160: `BaseAgentSettings` now sets `hide_input_in_errors=True`. Settings validation errors (e.g. missing `PUBLIC_URL` in production) no longer include the raw settings dict as `input_value=`, which could leak `MASTER_KEY` or other secrets into logs. Subclasses that override `model_config` still inherit it.
- GH-166: the `uvicorn.access` log no longer records the query string of any `/oauth/` request. With `response_mode=query` the IdP callback URL carries `code` and `state`, and uvicorn logged them in full. `build_app()` installs a logging filter (idempotent, always on) that cuts the query from `/oauth/` paths; other paths keep theirs. Only uvicorn's own access log is covered. Reverse proxy and ingress logs are not; strip them there or run uvicorn with `--no-access-log`. Resolves w042 phase deferred RT-027.
- RT-001 (w047): the `/mcp` JSON-RPC dispatch catch-all no longer uses `logger.exception`. It logs the exception class and `file:line` frames only, so a rendering error that carries a rejected tool-output value (pydantic `input_value=`) cannot reach the log.

### Fixed
- GH-164: wave Parse no longer trusts the AI parse alone for `allScope`. `wave-cycle.js` and `sdk-wave.js` also run a deterministic regex scan of every `Creates:`/`Modifies:` line (skipping `[~]` todos), union it with the AI result, abort with `scope-scan-mismatch` if the AI missed a scanned path, and log the final `allScope`. `harness/wave_scope.py::_looks_like_path` now accepts `.lock` files and known dotfiles (`uv.lock`, `.env.example`, `.gitignore`, ...) while still rejecting directories, globs and bare extensions. The scan and the AI parse read bare paths as well as backticked ones (the planner agent writes `Creates: src/a.py, tests/test_a.py` and bare `(modifies a, b)` clauses; a backtick-only scan printed `[]` for those waves, so the guard never fired), and accept a bold `**Creates:**`/`**Modifies:**` header line. `tests/test_wave_scope_extraction.py` runs the scan extracted from every workflow copy on planner-format, bare, backticked and `[~]` fixtures.
- GH-168: AG-UI history no longer cuts every replayed message to its first 4000 characters with no sign, which lost ids at the end so the model invented them. The limit is now `AGENT_SDK_AGUI_MAX_MESSAGE_CHARS` (default 32000, minimum 1000; a lower value fails boot). A longer message keeps its start and end with `[... N chars omitted ...]` in the middle (marker counted within the limit). Control characters are still stripped first and the warning is still logged.
- GH-162: docs no longer recommend `minReplicas: 2` when OAuth/IdP sign-in is on. IdP flows, consent tickets, auth codes, access tokens and MCP sessions are per-process, so sign-in needs exactly one replica; `docs/deployment.md` and DESIGN.md §2 now say so and list cross-replica revoke lag. A corrected `config.py` comment replaces the multi-replica claim. Boot logs one WARNING whenever a shared (Azure Table) store is configured, because the OAuth server and MCP sessions are always per-process; nothing is logged on the local SQLite store (maintainer ruling: https://github.com/wailuen/a2a-sdk/issues/162#issuecomment-6142451447). Shared sign-in storage is recorded as deferred work.
- GH-165: wave Archive step 3 now also fills `Test: [pending]` in PRD FR entries (written by `/analyze`) with `tests/<file>.py::<test_name>`, but only for a test that exists and passed in the wave: the file must be a `tests/` path in the wave scope and the test name must be cited in the wave file (read at its `completed/` path, after the move in step 1). Otherwise it stays `[pending]`. Same change in `wave-cycle.js` (harness, runtime and template copies) and `sdk-wave.js`; Archive phase detail updated.
- GH-169: the A2UI system-prompt section (`get_system_prompt_section`) no longer tells the model to "wrap" data as a component. It now says tools deliver cards automatically, the model must not write component JSON, and results are described in prose using only values tools returned. The examples are labelled as reference shapes of tool output. `allowed_components` filtering and compact schemas are unchanged.

## [0.11.0] — 2026-10-13

Resolves GH-156 (ids in text fallbacks), GH-157 (agent MCP instructions), GH-158 (AG-UI omits null `parentMessageId`) and GH-159 (non-text input rejected). GH-158 and GH-159 change wire behavior; see Breaking changes.

### Added
- GH-157: agent rules can now reach MCP client models. New `Agent(mcp_instructions=...)` (for `persona=` agents) or an optional `artifacts/mcp_instructions.md` artifact (for `artifacts_dir=` agents) is rendered once at build with the same variables as `system`, stripped, capped at 4000 characters, and sent in `initialize.instructions` after the credential note (blank line between). Setting both, going over the cap, or using an undefined template variable fails the build. The text is shown to every MCP client model: put no secrets in it. No env setting.

### 🔴 Breaking changes
- GH-159: A2A and AG-UI no longer silently drop non-text input. A2A `message/send`, `message/stream` and the interrupted-task resume reject any message containing a `FilePart` or `DataPart` (even mixed with text) with `-32005` ContentTypeNotSupported (HTTP 415) before any task is created; the error names the part kind only. A message with no text is rejected with `-32602`; the `" "` fallback is removed. AG-UI user messages with non-text content parts (in the current turn, i.e. the user messages after the last assistant message) now end in `RUN_ERROR` naming the part type, before a task is created; user `content` that is neither a string nor a list of parts (e.g. a bare part object) is also rejected with `RUN_ERROR` instead of being stringified into model input, and non-string, non-list assistant `content` folds to empty rather than being stringified; earlier history is not re-checked, so a rejected message a client keeps in its history does not lock the thread (its non-text parts are left out of the model input). Text-only input is unchanged; the card still advertises `text/plain` input only. **Migration:** send only `TextPart`s (A2A) or text content (AG-UI); clients that sent `FilePart`/`DataPart` now get 415. Spec: A2A v0.3.0 `defaultInputModes` and `ContentTypeNotSupportedError` (-32005).
- GH-158: AG-UI `TOOL_CALL_START` (normal and resume-synthetic) now omits `parentMessageId` when there is no parent message id, instead of sending `null` (tool-first turns, resume runs). A text-then-tool turn still carries the string id. **Migration:** treat `parentMessageId` as optional; do not read the key unconditionally. Spec: matches the AG-UI reference encoder (`exclude_none`).

### Fixed
- GH-156: the text fallback (`to_plain_text()`: MCP `tools/call` text, A2A `TextPart`, admin try-tool) of `EntityList`, `EmailList`, `CalendarEvents`, `UserList`, `UserProfile` and `DocumentList` now includes the ids follow-up tools need (e.g. `- Databricks (59199-40)`; `(id: ...)` elsewhere; email `conversation` id; manager id). Ids are sanitized and capped at 256 chars. Adds the shared helper `safe_id_text` (C-007, `agent_sdk/common/redact.py`); `FundPerformance.pb_id` now renders through it instead of `_sanitize_cell`, so `=`, `:`, `,` and `@` pass through verbatim instead of becoming fullwidth characters. Text-parsing callers of these cards will see the extra `(id: ...)` suffix; the MCP text block is still `to_plain_text()`, not JSON.

## [0.10.0] — 2026-10-12

Resolves GH-154 (per-task current date) and GH-155 (summary before a cap failure). Both new behaviors are on by default. Known pre-existing protocol issues filed for a follow-up: GH-158, GH-159.

### Added
- GH-155: final summary before a cap failure. When a run hits `max_turns` or the token budget, the SDK now makes one tools-disabled model call so the user gets an answer from what was gathered (text streams, then the run still ends failed with the same error; A2A `status.message` carries the summary plus the error). If that call fails or returns nothing, a fixed notice is sent instead. `ModelClient.converse` gains optional `tool_choice: "auto" | "none"`; `LoopPolicies.final_summary` (env `AGENT_SDK_FINAL_SUMMARY`, default `true`) and `final_summary_max_tokens` (default 1024) control it. Set `AGENT_SDK_FINAL_SUMMARY=false` for the old behavior. Deadline and sealed exits are unchanged. Per the GH-155 maintainer ruling, `final_summary_max_tokens` caps only the summary's output (also bounded by `max_output_tokens`); the call is always made at a cap exit (including the token-budget exit, however far the last turn overshot), and the fixed notice is sent only when the call fails or returns no usable text. A cap exit therefore costs exactly one extra call: its input is the re-sent transcript (the size the next turn would have sent) and its output is at most `final_summary_max_tokens`, so total spend can end above `token_budget` by that one call. Set `final_summary_max_tokens` to 0 for notice-only. Env `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS` sets `final_summary_max_tokens`. The OpenAI client adds no `reasoning_effort` on summary calls beyond what the operator configured. The OpenAI summary call sends `max_completion_tokens = min(final_summary_max_tokens, operator max_completion_tokens)`, which fits non-reasoning deployments (gpt-4o allows at most 16,384). Because that limit also counts hidden reasoning on gpt-5/o-series models, an empty summary with `finish_reason="length"` logs a fixed warning; raise `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS` or lower the reasoning effort. The max-turns exit checks the deadline first (no call) and uses the same output cap. **Custom `ModelClient` implementations must accept `tool_choice: Literal['auto','none'] = 'auto'`**, or summaries silently fall back to the notice (a warning naming the exception type is logged).
- GH-155: new settings `AGENT_SDK_OPENAI_REASONING_EFFORT` and `AGENT_SDK_OPENAI_MAX_COMPLETION_TOKENS` pass the existing `OpenAIModelClient` `reasoning_effort` / `max_completion_tokens` options through from the environment (previously reachable only by constructing the client in code).
- GH-155: new `DoneEvent.summary: str | None` field — the summary or fixed notice text of a cap-exit failure (also streamed as a `TextEvent`); custom route translators may read it. `None` on every other exit.
- GH-155 (testing, provisional): `FakeModelClient.converse` accepts `tool_choice`, and each `FakeModelClient.calls` entry gains a `"tool_choice"` key.
- GH-154: new `TaskRecord.date_line: str | None` field (runtime-set on a task's first turn; durable `TaskStore` subclasses should persist it, see DESIGN.md §5).
- GH-154: new dependency `tzdata` so `AGENT_SDK_TIMEZONE` and per-request zones load on hosts without system zone data (Windows, Alpine, distroless). The default zone `UTC` needs no zone data at all, and `AGENT_SDK_TIMEZONE` is not validated when `AGENT_SDK_INJECT_CURRENT_DATE=false`.
- GH-154: per-task current date. The worker appends `Today is YYYY-MM-DD (<tz>).` as the last system-prompt segment (`app.state.system_prompt` is never mutated). New settings `AGENT_SDK_INJECT_CURRENT_DATE` (default `true`) and `AGENT_SDK_TIMEZONE` (default `UTC`, validated at boot). Optional per-request zone: AG-UI `forwardedProps.timezone`, A2A `message.metadata.timezone` (invalid values fall back silently). Set `AGENT_SDK_INJECT_CURRENT_DATE=false` for the previous byte-identical prompt.

## [0.9.0] — 2026-10-10

Rolls up everything since `v0.7.0`, including the `[0.8.0]` work below, which was drafted in
September but never tagged. Closes GH-145, GH-147, GH-148, GH-149, GH-150, GH-151, GH-152, GH-153.

### 🟠 Security

- **Per-source sign-in flow quota (w043):** the in-progress IdP sign-in table is now limited per
  source address (IPv6 grouped by /64), so one source can no longer evict other users' sign-ins; a
  new source finding the table full gets a generic `temporarily_unavailable` instead of evicting anyone.
- **`client_ip()` no longer trusts the caller's own `X-Forwarded-For` hop (w043):** it walks the
  header from the right past configured trusted proxies, so a spoofed leftmost value is billed to the
  real peer. This affects every per-IP limit, including `unauth_rate_limit`.
- **Two sign-ins in one browser (w043):** each federated flow gets its own browser binding cookie, so
  a second authorize no longer breaks the first.
- **Microsoft personal-account tenant refused (w044):** the tenant GUID
  `9188040d-6c67-4c5b-b112-36a304b66dad` is rejected like the `consumers` alias, so a "pinned"
  Entra issuer can't admit every personal Microsoft account.

### — Harness

- Per-agent `effort:` for the Claude 5.5 models: `high` for redteam, debug, planner, sdk-advisor
  and the four protocol advisors; `medium` for analyst, codify and python-implementer. `debug.md`
  now says it runs at round 4+.
- Wave runners (`sdk-wave.js`, both `wave-cycle.js`): restored origin's GH-129..139 work that merge
  `0dc0517` dropped; a group's budget overrun now stops the wave, and a crashed group loop blocks archive.

### ✅ Features, fixes and docs (from the waves)

- **GH-152 fail-closed IdP gate:** with `AGENT_SDK_OAUTH_IDP=oidc` and a non-Entra issuer, boot now fails unless `AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE` or `_REQUIRED_GROUP` is set, or the new opt-out `AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS=true` (setting `oauth_idp_allow_all_issuer_users`, default false) is set. The opt-out logs one boot WARNING and is refused without `oidc`. Entra GUID issuers and role/group setups are unchanged.

- **GH-152-B/C — opt-in OIDC/Entra sign-in at `/oauth/authorize` (off unless `AGENT_SDK_OAUTH_IDP=oidc`):** `GET /oauth/authorize` now redirects the browser to the identity provider. Two new routes, `/oauth/idp/callback` and `/oauth/idp/consent`, finish the sign-in and show the consent page. Under `oidc`, `POST /oauth/authorize` is disabled.
- **`Identity.user` and `Identity.principal_key` (GH-152-C):** public stable-core fields, added as trailing fields so existing callers keep working.
- **`OAuthTokenStore` kwargs:** `session_ttl_seconds` and `require_user` on the store, and `user=` on `mint_code` and `mint_token_pair`.
- **Session cap and legacy-family refusal:** refresh families now have an absolute lifetime cap (`oauth_idp_session_hours`). Under `oidc`, refresh families that carry no user are refused.
- **API-key switch (GH-152-D):** `AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS` turns off non-admin API keys. Admin keys keep working.
- With `AGENT_SDK_OAUTH_IDP=none`, nothing changes. Approving a client at the IdP consent page records `user_consented_at` on the client, never the admin-only `consented` flag, so a later switch to `AGENT_SDK_OAUTH_IDP=none` with `AGENT_SDK_OAUTH_ONE_TIME_CONSENT=true` cannot auto-approve clients a directory user once allowed. New `OAuthTokenStore.mark_user_consented()`. Client eviction, in every mode: admin-approved (`consented`) clients are never evicted — this includes org clients approved before the upgrade; user-consented clients are protected only while they hold a live refresh family; all others are evictable oldest-first.

**GH-152-E — docs and wave-runner surface for IdP sign-in (docs, skills and tests):** DESIGN.md §5.5 gains an IdP sign-in addendum; §6 documents `Identity.user`, the `__oauth_idp__` namespace, the session cap with its removal-lag statement, and the API-key switch route table. `docs/security.md` gets the IdP section and the surface table now lists the callback/consent routes; the stale "A2A, AG-UI | API key" row now reads "API key or OAuth token". The `/setup` skill gains Entra app-registration steps. `agent_sdk/auth/oidc` (C-014) joins `AUTH_SURFACE` in `sdk-wave.js` and `src/auth/oidc` in the three `wave-cycle.js` mirrors; `tests/test_workflows.py` pins both. Follow-ups listed in ADR-003: OBO from the user token, Entra re-check at refresh, Graph group-overage fallback, extra-host allowlist, remembered consent.

**GH-152-A — IdP sign-in settings and boot validation (off by default, additive):** new `BaseAgentSettings` fields `oauth_idp` (`AGENT_SDK_OAUTH_IDP`, `none`|`oidc`, default `none`), `oauth_idp_issuer` (`AGENT_SDK_OAUTH_IDP_ISSUER`), `oauth_idp_client_id` (`AGENT_SDK_OAUTH_IDP_CLIENT_ID`), `oauth_idp_required_role` (`AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE`), `oauth_idp_required_group` (`AGENT_SDK_OAUTH_IDP_REQUIRED_GROUP`), `oauth_idp_session_hours` (`AGENT_SDK_OAUTH_IDP_SESSION_HOURS`, default 720, bounds 1-2160) and `oauth_idp_disable_api_keys` (`AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS`, default false). `build_app()` refuses a missing issuer or client id, a multi-tenant or v1 Entra issuer, a missing `agent-sdk[oidc]` extra, `AGENT_SDK_OAUTH_ONE_TIME_CONSENT=true` with `oidc`, and the disable-API-keys switch without `oidc`. The client secret lives in the reserved `__oauth_idp__` credential namespace (admin Credentials card, set/unset only). New optional extra `oidc = ["PyJWT[crypto]>=2.8"]`. With `oauth_idp=none` nothing changes.

**GH-151 — template A2UI/A2A advisor and check-skill mirrors re-synced (docs/tests only, no runtime change):** `template/.claude/agents/a2ui-advisor.md`, `template/.claude/skills/a2ui-check/SKILL.md`, `template/.claude/agents/a2a-advisor.md` and `template/.claude/skills/a2a-check/SKILL.md` are now byte-identical to their `harness/` mirrors, so `/a2ui-check` run from a seeded agent repo no longer flags the SDK's own `data.messages` DataPart (advertised via `dataEncoding`) as a protocol error. `tests/test_rt002_a2ui_wire_shape_mirror_parity.py` now reads the template copies off disk (strict xfail when `template/` is absent) and the "#151 — do not fold it in" carve-out is removed. Template edits must be committed in the template's own repo.

**Profile v1.1 `metadata` amendment — ratified and applied:** the maintainer signed off REVIEWS.md Round 11 on 2026-10-09 (recorded in https://github.com/wailuen/a2a-sdk/issues/153). The typed `TimeSeriesChart.metadata` row is removed from all three a2ui-advisor copies; `metadata` is a cross-cutting free-form field on every FROZEN type, and receivers MUST accept it. Docs now say Standard Profile v1.1. The catalog URN `urn:a2ui-profile:standard:v1` and `CATALOG_ID` are unchanged. The parity tests enforce the state via the REVIEWS.md-derived `ROUND_8_METADATA_ROW_REMOVAL_RATIFIED` flag (now True); no separate release gate. No runtime change.

**Reconciliation note (w042):** this repo's local `main` had diverged from `origin/main` at
`v0.5.44` — origin went on to tag `v0.6.0` and `v0.7.0` (the admission-cap and terminal-resume
error-code work recorded further below) independently of the `v0.8.0` work in this file's next
section, drafted on the local branch over the same period. The merge that reconciled the two
histories landed both lineages' code, but the `v0.6.0`/`v0.7.0` CHANGELOG sections themselves
were only added back here afterward — see the `[0.7.0]` and `[0.6.0]` sections below, positioned
in their real chronological place (before `[0.5.44]`'s successors, after `[0.8.0]` which
supersedes them). The GH-152 IdP sign-in work listed above is the only work sitting ahead of `[0.8.0]`.

## [0.8.0] — 2026-09-02 (never tagged; shipped in v0.9.0)

**RT-002 (redteam, high, versioning discipline): this release was drafted under a same-minor
patch bump (`0.5.45`) even though two of the entries below are VOLUNTARY breaking changes to the
stable core — the `metadata` base-class hoist and the `to_plain_text()`/`_body_text()` split are
internal SDK redesigns, not required by any external protocol spec (A2A/AG-UI/A2UI/MCP). DESIGN.md
§4.0's wire-shape conformance exemption only covers a break "driven by external protocol
conformance (not a voluntary redesign)" and states plainly that "a voluntary breaking change to the
stable core — not required by spec conformance — still requires a major bump; this exemption cannot
be cited for those." The `FundPerformance.fund_name` removal below is exemption-eligible on its own
(it brings the wire shape into conformance with the frozen A2UI Standard Profile v1 contract), but it
ships in the same release as the two voluntary breaks, and a release's version number covers the
whole release, not per-entry — so the release as a whole requires this project's major-bump
convention (bumping the middle digit pre-1.0, per precedent elsewhere in this file, e.g. the 0.6.0
alternative discussed under 0.5.44 below). Retitled from `[0.5.45]` to `[0.8.0]` for that reason.
**Numbering note:** `0.6.0` and `0.7.0` were found already tagged in this repository's git history
(pushed to `origin`, on a branch that diverged from local `main` right after `v0.5.44` — `main` here
has never merged that lineage) — see the `w041` git-divergence finding surfaced alongside this fix.
Reusing either number for this unrelated content would collide with real, differently-scoped
releases, so this entry uses the next unused number, `0.8.0`, instead. The branch divergence itself
is NOT resolved by this entry and needs separate, deliberate reconciliation before any tag is cut.

### 🔴 Breaking changes
- **`FundPerformance.fund_name` (wire alias `fundName`) removed** (`agent_sdk/models/content_types.py`) —
  GH-149. `fund_name` was never part of the frozen A2UI Standard Profile v1 `FundPerformance`
  contract (`.claude/agents/a2ui-advisor.md` / `harness/agents/a2ui-advisor.md`, 19-field table under
  `urn:a2ui-profile:standard:v1`): it shared that catalog id with every other frozen type despite not
  being one of its contracted fields, and the SDK has no gating/versioned-extension mechanism to mark
  a field as an intentional per-agent addition to a frozen profile type. Removed rather than
  retroactively frozen into the profile. `FundPerformance.to_plain_text()` no longer leads with the
  fund name; the remaining bits (every other field the type declares — see RT-002 below) still
  produce a non-empty summary on their own. The LLM-facing example payload and compact wire schema
  (`agent_sdk/a2ui/catalog.py`, `_FEW_SHOT_EXAMPLES["FundPerformance"]` / `_COMPACT_SCHEMAS["FundPerformance"]`)
  no longer mention `fundName`. **Migration:** any agent emitting `fundName` on `FundPerformance`
  must drop it — the field is no longer declared on the model, so a `fundName` key in constructor
  input is now silently ignored (pydantic's default `extra="ignore"`) rather than populating a field,
  and it will never appear in `wire()` output going forward. **Fund identity has no dedicated
  replacement field on `FundPerformance` — do not add one back.** An agent that needs to say *which*
  fund a card describes must carry that identity through one of: (1) surrounding assistant text
  (e.g. "Here's Fund III's performance:" ahead of the card), (2) the SDK-wide `metadata` envelope
  every `ContentModel` inherits (e.g. `metadata={"fund": "Fund III"}`, distinct from the frozen
  per-type fields — see the `metadata` docstring at the top of `content_types.py`), or (3) a
  domain-specific card type registered under its own `catalog_id` via `register_content_type` (see
  "Domain extension" in that same docstring) when fund identity belongs on the card itself. Absent
  one of these, sibling `FundPerformance` cards in one response are indistinguishable: the console
  card title is the fixed string `"Fund performance"` (`console/static/a2ui.js::renderFundPerformance`),
  `get_system_prompt_section` (`agent_sdk/a2ui/catalog.py`) instructs the model to emit `pbId` only
  when a tool result supplied one and never invent one, and `to_plain_text()` on a card without
  `pbId` emits only metric bits with no identifying prefix. A multi-fund comparison response is
  expected to use one of the three replacements above per card; N identically-titled cards with no
  text-fallback way to tell them apart is a bug in the calling agent, not intended SDK behavior.
- **`metadata: dict[str, Any] | None = None` moved onto `ContentModel` itself** (RT-003, RT-006
  follow-up; `agent_sdk/models/content_types.py`) — previously redeclared on each of the 14
  `ContentModel` subclasses, now declared once on the base class and inherited by every subclass,
  including every third-party domain card type registered via `register_content_type`. This is a
  public-surface change, not a no-op refactor, with three observable effects. (1) **Every external
  `ContentModel` subclass silently gains a `metadata` field it never declared** — widening what that
  type accepts on construction and emits in `wire()`, whether or not the owning agent wants a
  `metadata` key on that card. (2) **`wire()` key order changed for all 14 profile types** — pydantic
  orders base-class fields ahead of subclass fields in `model_fields`, so e.g.
  `list(FundPerformance.model_fields)[:4]` is now `['metadata', 'pb_id', 'as_of_date', 'irr']` where
  `metadata` previously sorted with the type's own fields; a consumer relying on wire key order (a
  strict JSON diff, a positional parser) sees a different shape. (3) **An external subclass that
  already assigns a plain, unannotated class attribute named `metadata`** now fails at
  class-definition time (`PydanticUserError`: "Field 'metadata' defined on a base class was
  overridden by a non-annotated attribute") — the same "adding to a public ABC breaks external
  subclasses" class of break as `workspace/learning/LRN-113-public-abc-new-abstractmethod.md`. A
  `@property` or plain method named `metadata` does NOT raise at class-definition time — pydantic
  silently accepts the descriptor/function object itself as the field's new default, so an instance
  that doesn't pass `metadata=` explicitly gets that raw `property`/`function` object back from
  `.metadata` instead of `None`, and the break instead surfaces later, on the first `wire()` call
  (`PydanticSerializationError: Unable to serialize unknown type: <class 'property'>`). **Migration:**
  search third-party `ContentModel` subclasses for any `metadata` attribute — field, property, or
  method — before upgrading; rename it if found. No action is needed for a subclass that neither
  defines its own `metadata` nor depends on `wire()` key order.
  `agent_sdk/a2ui/catalog.py`'s `_field_summary` now skips `metadata` explicitly so it doesn't precede
  a type's real required fields in the LLM-facing compact-schema line for a registered type with no
  `_COMPACT_SCHEMAS` entry. `agent_sdk/models/content_types.py`'s module docstring records the move as
  intentional and SDK-wide. **RT-004 (REVIEWS.md Round 10) correction:** this entry originally also
  claimed all three a2ui-advisor copies (`.claude/agents/a2ui-advisor.md`, `harness/agents/a2ui-advisor.md`,
  `template/.claude/agents/a2ui-advisor.md`) were edited in this same release to drop `TimeSeriesChart`'s
  frozen per-type `metadata` row in favor of a cross-cutting note — that edit was a wave self-authorizing
  a change to a frozen A2UI Standard Profile v1 field contract (DESIGN.md stable core) to match its own
  code, mirroring GH-149's opposite-direction resolution with no comparable sign-off, and REVIEWS.md
  Round 8 recorded it as PROPOSED, never SIGNED OFF. It has been **reverted**: the frozen row is back in
  all three copies pending a maintainer's explicit Profile v1.1 ratification (tracked in
  `workspace/sdk-candidates.md`). The base-class `metadata` field itself, and everything else in this
  bullet, is unaffected. `tests/test_rt002_a2ui_wire_shape_mirror_parity.py` and
  `tests/test_round8_metadata_ratification_gate.py` now fail the suite if any copy drops the row again
  while unratified, rather than only warning on a revert. (`agent_sdk/models/content_types.py`,
  `agent_sdk/a2ui/catalog.py`, `.claude/agents/a2ui-advisor.md`, `harness/agents/a2ui-advisor.md`,
  `template/.claude/agents/a2ui-advisor.md`)
- **`to_plain_text()` now appends a trailing `\nkey=value` metadata suffix for every `ContentModel`**
  (RT-A06, direct follow-up to the `metadata` base-class move above; `agent_sdk/models/content_types.py`)
  — before this release no type emitted `metadata` into its text fallback at all; the shared
  `_metadata_suffix()` helper now has exactly ONE call site, inside the concrete base-class
  `ContentModel.to_plain_text()` (`self._body_text() + self._metadata_suffix()`), which every one of
  the 14 profile types and every domain card inherits. It is never called per subclass — see the
  next bullet for why that mechanism, not a 14-site edit, is the fix. This changes
  wire-visible output on two surfaces the bullet above does not cover: the A2A dual-part `TextPart`
  built in `agent_sdk/agent/runner.py`'s `build_artifact` (`TextPart(text=payload.to_plain_text())`)
  and the MCP `tools/call` text block in `agent_sdk/routes/mcp.py`'s `_tool_text` (line 363). An
  operator diffing either text fallback before/after this release will see an unexplained
  `\nkey=value` tail on any card constructed with `metadata=...`. Each rendered key and value is now
  routed through `agent_sdk.common.redact.sanitize_text` (C-007's control-char-strip + length-cap
  helper, SI-2 — see the C-007 entry below; this release also deletes `agent/loop.py`'s former
  private copy, `_sanitize_model_name`, now that every caller has moved onto the shared helper)
  before reaching the wire,
  and the assembled suffix as a whole is capped at 4096 chars — `metadata` is a caller-/tool-supplied
  `dict[str, Any]` and was previously interpolated into the suffix with no sanitization and no bound.
  (`agent_sdk/models/content_types.py`, `agent_sdk/common/redact.py`)
- **`ContentModel` subclasses now implement `_body_text()`, not `to_plain_text()`** (RT-003;
  `agent_sdk/models/content_types.py`) — `to_plain_text()` is now CONCRETE on the base class, defined
  as `self._body_text() + self._metadata_suffix()`, and `_body_text()` is the abstract hook. As the
  bullet above states, before this release **no card — built-in or domain — emitted `metadata` into
  its text fallback at all**; the previous bullet's single base-class `_metadata_suffix()` call ships
  in this same release, not restoring a prior convention. None of the 14 built-ins declares
  `to_plain_text()` any more — each now declares `_body_text()` instead. Adding the suffix call by
  hand, one per subclass, would invite the failure this bullet exists to close off: a
  card — built-in, and especially a future domain card registered via `register_content_type`, which
  this module never controls — forgets the call, and its `wire()` carries the GH-63 disclosure
  annotation while its `to_plain_text()` silently drops it, for exactly the no-A2UI-capability clients
  (A2A `TextPart`, MCP `tools/call` text) the annotation exists for. A field declared once on a base
  class cannot have a rendering obligation discharged per subclass, so the base class
  now renders it once for every subclass that will ever exist. **Migration: none required** for a
  domain card that does not already declare a method or attribute named `_body_text` — see the
  RT-005 correction below for the one shape that does need migration. An
  existing domain card that overrides `to_plain_text()` keeps working and additionally gains the
  suffix — `ContentModel.__init_subclass__` adopts the override as that class's `_body_text()` and
  rebinds `to_plain_text()` to the base implementation (the original stays reachable as
  `cls._body_text`). New code should implement `_body_text()` directly.
  **RT-003 (round 2, redteam, high) — corrected here:** an earlier draft of this migration note
  claimed "no code can exist against the previous API" that calls `super().to_plain_text()` from a
  `_body_text()`/`to_plain_text()` override, since that call "resolved to the abstract `...` stub and
  returned `None`." That is true only for a class subclassing `ContentModel` DIRECTLY. It is false —
  and was a live `RecursionError`, reproduced in CI — for the equally legal, more common pattern of a
  card subclassing a CONCRETE built-in (e.g. `class MyKpi(KpiCard)`) and extending its rendering via
  `super().to_plain_text()`: the rebound `to_plain_text()` calls `self._body_text()`, which dispatches
  on `type(self)` and lands right back on the same adopted override, unboundedly. Fixed structurally,
  not just documented around: `ContentModel.to_plain_text()` now detects it is being re-entered from
  inside an adopted override executing for the same instance and resolves the call to the next
  ancestor's `_body_text()` directly (`_ADOPTED_OVERRIDE_STACK` / `_NEXT_BODY_TEXT`,
  `agent_sdk/models/content_types.py`), without a second metadata-suffix append — only the outermost
  call adds one. **Migration: still none required** — both `super()._body_text()` (new code) and
  `super().to_plain_text()` (adopted legacy code, any ancestor) now resolve correctly; prefer
  `super()._body_text()` in new code only because it skips one indirection, not because the other form
  is unsafe. Covered by `tests/test_rt003_super_to_plain_text_no_recursion.py`.
  **RT-005 (redteam, high) — the "Migration: none required" claim above is false for one pre-existing
  shape:** a domain card written before this split could legally declare a PRIVATE helper method named
  `_body_text()` alongside its `to_plain_text()` override — `_body_text` had no reserved meaning in the
  SDK until this release. `ContentModel.__init_subclass__` only adopts the legacy `to_plain_text()`
  override when the subclass has not also declared its own `_body_text` in its own `__dict__`; a class
  declaring both now raises `TypeError` at class-DEFINITION time (import time), not at render time,
  because silently skipping adoption would leave the stale `to_plain_text()` override in place,
  shadowing the concrete base method and dropping the `metadata` suffix — the exact drift this whole
  mechanism exists to make impossible. **Migration required for this one shape only:** grep third-party
  `ContentModel` subclasses for `_body_text` — any subclass defining both `_body_text` (in any sense,
  including a private helper unrelated to text rendering) and `to_plain_text` will fail to import.
  Rename the pre-existing `_body_text` member (e.g. to `_render_body`) and move the body of
  `to_plain_text()` into a new `_body_text()` override; the error message raised at class-definition
  time repeats this exact guidance. A subclass declaring only one of the two names is unaffected —
  this migration step applies solely to the both-declared collision. Covered by
  `tests/test_rt005_both_body_text_and_to_plain_text_declared.py`.
  (`agent_sdk/models/content_types.py`, `docs/content-types.md`)
- **`ContentModel.metadata` now rejects non-finite floats at construction** (RT-006;
  `agent_sdk/models/content_types.py`) — a `field_validator` routes it through the existing
  `_assert_finite`, matching `ChartSection.data` / `TableSection.data` / `BriefingKpiItem.value`.
  `metadata` is the only free-form `dict[str, Any]` present on every card and the only one reaching
  BOTH halves of a dual-part artifact: `KpiCard(..., metadata={"x": float("inf")})` previously
  constructed fine, then emitted `{"metadata": {"x": null}}` from `wire()` (pydantic's
  `ser_json_inf_nan` null default) while `to_plain_text()` rendered `x=inf` — the A2UI `DataPart` and
  the mandatory `TextPart` disagreeing about the same value, which is precisely the split GH-95's
  guard exists to prevent. **Migration:** a caller passing `inf`/`-inf`/`nan` anywhere inside
  `metadata` (nested dicts and lists included) now gets a `ValidationError` at construction instead
  of a silently reshaped wire value; pass `None` or a string sentinel instead. Fields outside GH-95's
  scope (`MetricItem.value`, `BarItem.value`, `WaterfallSegment.value`, `ComparisonTable.rows`,
  `FundPerformance`'s numerics) still accept non-finite floats, unchanged.
  (`agent_sdk/models/content_types.py`)

### 🟡 Protocol surface changes
- RT-B-004: `ToolEntry.input_schema(include_reuse_hint=True)` (`agent_sdk/agent/registry.py:550-612`,
  loop-only — see that method's RT-005 docstring paragraph for why every other tool-schema-advertising
  surface must keep the hint off) now widens a `ReuseKind` field whose advertised type excludes
  strings — `Annotated[int, ReuseKind("entity_id")]` otherwise renders as plain `{"type": "integer"}` —
  to `{"anyOf": [<original constraints>, {"type": "string", "pattern": "^\$"}]}`
  (`_widen_for_reuse_token`, `agent_sdk/agent/registry.py:212-231`) so the `$ref:<kind>`/`$raw:<value>`
  reuse token, itself a string sentinel, is actually representable in the schema a schema-enforcing
  model provider (Bedrock Converse and similar) constrains tool arguments to — without it the GH-148
  reuse mechanism was silently unreachable on every non-string `ReuseKind` field on such a provider,
  even though `reuse_fields_for_model` accepted the annotation without complaint. The same widening
  applies to a string-typed field whose own schema narrows its value space via `pattern`/`const`/
  `format`/`minLength`/`maxLength` (a regex-validated or UUID-formatted id), and resolves a `$ref`
  (against the schema's own `$defs`) or `allOf` composition first so an `Enum`-typed `ReuseKind` field
  is widened too, not silently skipped (`_schema_permits_string`,
  `agent_sdk/agent/registry.py:133-209`). A plain, unconstrained string-typed field is untouched — the
  token is already representable and the emitted schema is byte-identical to before. Only the
  `include_reuse_hint=True` rendering changes; the tool's own `input_model` validation, and every
  agent-card/MCP schema advertisement (which never sets that flag), are unaffected. Covered by
  `tests/test_rt_b004_reuse_kind_nonstring_scalar_schema.py`,
  `tests/test_rt004_string_value_constraint_widening.py` and
  `tests/test_rt006_reuse_kind_enum_schema_widening.py`. (`agent_sdk/agent/registry.py`)
- RT-B-203: `GET /v1/tasks` (`tasks_list`) and `GET /v1/tasks/{id}` (`tasks_get`) no longer echo
  `X-A2A-Extensions` unconditionally off the request's own header (`agent_sdk/routes/a2a.py`).
  `X-A2A-Extensions` means an extension was ACTIVATED for this response (§5.1) — a conformant
  consumer is expected to parse a response for A2UI `DataPart`s only when the header comes back
  activated (the project's own a2a-advisor D7.11 guidance). Both routes run no extension logic at
  all (no `_capabilities()` call, nothing forwarded), so echoing unconditionally meant a client
  that opted into `A2UI_EXTENSION_URI` on a `tasks/get` against a task that was NOT created with
  A2UI active got the header back anyway, alongside a Task with no A2UI parts — a false activation
  signal on the wire, not just a misleading code comment. `tasks_get`/`tasks_list` now echo
  `A2UI_EXTENSION_URI` (`_echo_a2ui_if_present`) only when a Task actually being returned carries a
  part whose `metadata.mimeType` is `application/a2ui+json`; the credential-forwarding extension
  URI is never echoed on either route at all — nothing is forwarded on a read. The four mutating
  routes (`message:send`, `message:stream`, `tasks/cancel`, `tasks/resubscribe`) are unchanged —
  each can genuinely activate both extensions on its own request. Covered by
  `tests/test_rtb203_a2ui_echo_activation_only.py`. (`agent_sdk/routes/a2a.py`)

### ✅ Features
- GH-148 (LRN-355 re-test): new `Reusable`/`ReuseKind` mechanism (`agent_sdk/agent/reuse.py`) gives
  a tool-resolved value a cross-turn reference the model can cite instead of retyping it from memory.
  Before this fix `run_loop`'s only cross-turn memory was replaying the full `messages` transcript
  verbatim — the task-local result cache only dedupes byte-identical repeat calls WITHIN one task —
  so nothing stopped the model from retyping a value it resolved in an earlier turn, and live testing
  (8 fresh runs) found it substitutes a different-but-real, WRONG entity id in 7/8 runs: a silent
  data-correctness failure with no validation-layer signal, since the substituted value is itself a
  real, valid id. A tool now marks a return value reusable via `Reusable(value=result,
  kind="entity_id", label="PT IMC Pelita Logistik")`; `agent/loop.py` unwraps it before the model sees
  the result (the model receives `.value`, exactly like a plain return) and folds a `__resolved__`
  marker (`kind`/`label`/`value`) into that tool call's existing result block in `messages` — no new
  store, no new `TaskRecord` field, no expiry rule; the mechanism rides `messages`, but carrying a
  marker across a request boundary depends on the transport's fold (RT-001, see below).
  A downstream tool opts an input field into the contract via `Annotated[<type>,
  ReuseKind("entity_id")]` on its Pydantic `input_model` (detected once at `@tools.tool` decoration
  time by scanning `input_model.model_fields[<field>].metadata` for a `ReuseKind` instance
  (`agent_sdk/agent/reuse.py`, `reuse_fields_for_model`), stored on `ToolDecl.reuse_fields`); at
  the start of every `run_loop` call the loop rebuilds a "resolved this conversation" index by
  scanning `messages`, then before invoking such a tool: a
  literal `$ref:<kind>` or `$ref:<kind>:<label>` token (the label disambiguates multiple resolutions
  of the same kind) is substituted with the matching resolved value and the substitution is recorded
  as an auditable `AuditEvent` — never a `NoteEvent` (RT-009: that channel is folded into user-facing
  agent chat text by both transports, and this is internal plumbing that must never reach it) — and
  the event itself carries only the schema-declared field name and kind, never the resolved value or
  label (SI-2); a raw value that does NOT match any resolution of a kind that HAS at least one is
  rejected with a generic, SI-2-safe tool error (`ToolEntry.invoke`/`invoke_gen` signatures are
  unchanged — this is the exact GH-148 failure mode, now caught instead of silently executed) naming
  only the schema-declared field and kind, never the mismatched raw value or any resolved value's
  content verbatim; a raw value is passed through unchanged when no resolution of that kind exists
  yet, or it already matches. A tool that returns a plain value and an `input_model` with no
  `ReuseKind`-annotated fields is unaffected — byte-identical behavior to before this feature existed.
  Additive, non-breaking.
  **RT-008 (two escape hatches, same release) — corrected by RT-002 in this same release:** the
  mismatch rejection above has no path for a genuinely new, legitimate raw value, which without one
  leaves the model stuck retrying a resolver tool it has no reason to call until the turn budget runs
  out. `ReuseKind("entity_id", allow_raw_override=True)` is an OPERATOR opt-in, per field, defaulting
  to `False` (`ReuseKind.allow_raw_override`, `agent_sdk/agent/reuse.py:171`) — it is not a
  caller-discoverable escape hatch. Only when an operator has set it `True` on a field does the
  per-call literal token `$raw:<value>` on that field pass `<value>` through as-is for that one call,
  bypassing the match check entirely, itself recorded as a substitution
  (`AuditEvent(code="reuse_raw_override", ...)`, `ReuseSubstitution.via_raw_override=True`) so the
  bypass is auditable, not silent. RT-002 found that naming `$raw:` in the mismatch rejection error —
  as an earlier draft of this feature did, to let the model "recover in-turn" — handed the exact
  adversary this mechanism exists to stop (a model that just supplied a wrong raw value) a documented
  bypass, so by design the rejection text never mentions the token, on any field, opted in or not
  (`tests/test_gh148_reuse_kind_substitution.py::test_mismatch_error_does_not_name_the_raw_override_escape_hatch`).
  **RT-005:** a field left at the default (`allow_raw_override=False`, i.e. most fields) rejects a
  `$raw:`-prefixed string outright, unconditionally (`agent_sdk/agent/reuse.py`'s
  `resolve_reuse_fields`, the `is_raw_override_token and not raw_override_allowed` branch) — the token
  is never treated as an ordinary candidate raw value there, so it never falls through to the
  mismatch check and never reaches the tool body, regardless of whether any resolution of that kind
  exists yet
  (`tests/test_gh148_reuse_kind_substitution.py::test_raw_override_token_rejected_on_field_without_opt_in`,
  `tests/test_rt005_loop_raw_token_no_opt_in_parity.py`). Set
  `allow_raw_override=True` only on a field whose operator has deliberately accepted that trade-off;
  until then, `$raw:` grants the model nothing. Separately, `ReuseKind("entity_id", strict=False)` turns off the mismatch
  rejection for that field for every call, not just one: `$ref` still resolves normally, but a raw
  value is never checked against prior resolutions. Trade-off: `strict=False` restores full liveness
  (nothing the model or user supplies directly is ever blocked) at the cost of exactly the
  silent-wrong-substitution risk GH-148 exists to catch — pick it only for a field where an operator
  has judged that risk acceptable for that tool. `allow_raw_override=True` is the narrower opt-in
  (per call, always audited, and never advertised to the model) and is the default escape hatch to
  reach for; reserve `strict=False` for fields where even the per-call prompt is worse than the risk.
  **Note for `TaskStore` subclassers:** across an A2A `contextId` continuation (a new task started on
  a context that already has a terminal prior task), the resolved-value index this mechanism scans is
  rebuilt from whatever `messages` the new task starts with — for that transport, the sole carrier of
  the prior task's `__resolved__` markers into the new task is `TaskStore.context_messages()`. Its
  base-class implementation (`agent_sdk/tasks/store.py`, non-abstract) returns `[]`; an
  external durable `TaskStore` that does not override it will not error or warn — it silently starts
  every continued task with an empty index, so the mismatch check silently stops applying for every
  reference resolved in a prior turn of that context: a raw value simply passes through unvalidated,
  while an explicit `$ref:<kind>` token still fails loudly with an error, not closed, since the empty
  index has no entry for it to resolve against. A single task with no continuation involved is
  unaffected, since `run_loop` reads and writes the same in-memory `messages` list throughout.
  **RT-001 correction: cross-turn carriage is A2A-only, not both-transport as first described above.**
  A2A qualifies because `TaskStore.context_messages()` returns the prior task's Converse-format
  `messages` verbatim (server-persisted, never round-tripped through the client) — a marker folded in
  turn N survives into turn N+1's fresh `run_loop` call. AG-UI does not: `routes/ag_ui.py::_fold_history`
  collapses every resent message, including a prior toolResult block, down to a single `{"text": ...}`
  entry built only from `type == "text"` parts, and every `POST /ag-ui/run` creates a brand-new
  `TaskRecord` with no `context_messages` equivalent — so the resolved-value index is always empty at
  the start of a fresh AG-UI run, and `$ref:<kind>` substitution across two separate AG-UI runs is a
  silent no-op (a raw value is simply passed through, since the index looks empty rather than
  mismatched). The mechanism still works WITHIN a single AG-UI run — `resolved_index` is grown in place
  across the multiple model turns `run_loop` drives for one request — it just does not survive to the
  next request. If AG-UI carriage is ever added (e.g. persisting the index server-side per `threadId`,
  or round-tripping markers through `state`/`forwardedProps`), note that AG-UI's transcript is
  client-resent and therefore caller-controllable: the resolved index must not be described as a
  data-integrity control on that transport the way the A2A rejection path is. Covered by
  `tests/test_gh148_reuse_kind_substitution.py`'s AG-UI-shaped regression tests.
  **RT-A-004 correction: AG-UI carriage landed this same release — the "if ever added" note above is
  now stale.** The gap was operator-invisible (no log, no CHANGELOG caveat until this correction) and
  the mismatch check itself simply never fired across an AG-UI thread, silently reopening exactly the
  wrong-but-real-id failure GH-148 exists to catch, on the one transport the issue's own repro
  methodology was modeled on. Fixed by reusing the SAME `TaskStore.context_messages(context_id)` A2A
  already relies on — `thread_id` and `context_id` are the same value for an AG-UI task
  (`routes/ag_ui.py`'s `new_task(thread_id)`) — but routed differently: `run_loop` gained a new
  keyword-only `extra_resolved_messages` parameter (`agent_sdk/agent/loop.py`), scanned to seed the
  resolved-value index ONLY, never appended to `messages` and never shown to the model. `routes/a2a.py`
  still extends `record.messages` with `context_messages()` directly (unchanged — the model there is
  meant to see the prior turn's history verbatim); `routes/ag_ui.py`'s non-resume run branch instead
  calls `context_messages(thread_id, identity)` and passes it through `run_task_worker` (which gained
  the same new parameter, forwarded to `run_loop`) as `extra_resolved_messages` — so AG-UI's smaller,
  text-only model-visible transcript is unchanged, only the reuse mechanism's internal index gains
  cross-run memory. A resume run (continuing the SAME `TaskRecord`) is unaffected — its `messages`
  already carries everything relevant from within that run. Covered by
  `tests/test_gh148_reuse_kind_substitution.py::test_route_level_ref_substitution_survives_ag_ui_thread_continuation`,
  which drives two real `POST /ag-ui/run` requests on the same `threadId` through the live ASGI app —
  mirroring `test_route_level_ref_substitution_survives_a2a_context_continuation`'s existing A2A
  coverage. Non-breaking: `extra_resolved_messages` defaults to `None` on both new parameters, so
  every existing `run_loop`/`run_task_worker` caller is unaffected. (`agent_sdk/agent/loop.py`,
  `agent_sdk/agent/runner.py`, `agent_sdk/routes/ag_ui.py`, `agent_sdk/agent/reuse.py`)
  **RT-001/RT-009 correction: the RT-A-004 fix above survived exactly ONE run hop, not a
  conversation, and could leak across identities.** `routes/ag_ui.py` seeded `resolved_index` from
  `TaskStore.context_messages(thread_id, identity)` — the SINGLE most recent terminal task's
  `messages` only. An AG-UI `TaskRecord.messages` never inherits a prior run's `messages` the way
  A2A's does (it stays scoped to that run's own folded text), so a `__resolved__` marker folded
  while completing run N was visible only while run N remained the newest terminal task in the
  thread. One intervening, unrelated run N+1 — which completes with no marker of its own — became
  the new "most recent terminal task", and run N+2's seed went silently empty: `$ref:<kind>` stopped
  resolving, and a WRONG raw id was silently executed instead of rejected — reopening the exact
  wrong-but-real-id substitution GH-148 exists to catch, on the one transport its own repro
  methodology was modeled on. Separately, `InMemoryTaskStore.context_messages()` short-circuits its
  per-identity filter for admin api_key identities (operator task inspection); reusing it for the
  reuse-index seed meant an admin AG-UI caller who supplied ANOTHER identity's `threadId` inherited
  that identity's resolved values through a side channel that produces no frame and no user-visible
  history. Fixed by a new store method, `TaskStore.context_reusable_messages(context_id, identity)`
  (`agent_sdk/tasks/store.py`, default no-op `[]`; implemented on `InMemoryTaskStore`,
  `agent_sdk/tasks/memory.py`) that scans EVERY terminal task in the context, oldest first, and
  never honours the admin cross-identity override — `routes/ag_ui.py`'s non-resume run branch now
  calls it instead of `context_messages()`. `context_messages()` itself and A2A's use of it are
  unchanged. Covered by
  `tests/test_gh148_reuse_kind_substitution.py::test_route_level_ag_ui_ref_substitution_survives_intervening_unrelated_run`
  (three real `POST /ag-ui/run` requests on one `threadId` with an intervening unrelated run) and
  `::test_route_level_ag_ui_admin_key_cannot_seed_resolved_index_from_other_identity_thread`, plus
  store-level unit coverage in `tests/test_context_reusable_messages.py`. (`agent_sdk/tasks/store.py`,
  `agent_sdk/tasks/memory.py`, `agent_sdk/routes/ag_ui.py`, `agent_sdk/agent/reuse.py`,
  `agent_sdk/agent/loop.py`)
  **RT-A-006: the mismatch check compared a raw value against the UNION of every resolution of a
  kind, regardless of label — so it only ever caught a value that was never resolved at all.**
  Verified: with `entity_id: [("Acme Corp", "ENT_1"), ("Beta Ltd", "ENT_2")]` on record, supplying
  `"ENT_2"` where Acme was meant passed silently — `"ENT_2"` really was resolved, just under the
  wrong label, and the check had no way to tell which resolution the call actually meant. Fixed:
  `resolve_reuse_fields` (`agent_sdk/agent/reuse.py`) now rejects a raw value outright, ambiguity-
  worded, whenever MORE than one resolution of the kind is on record — before checking whether the
  raw value happens to match one of them — sending the model to `$ref:<kind>:<label>` (or a
  re-resolve) instead of guessing. A single resolution of a kind is unambiguous and raw-value
  matching against it is unchanged. Covered by
  `tests/test_rt_a006_reuse_label_confusion.py`.
  (`agent_sdk/agent/reuse.py`, `agent_sdk/agent/loop.py`, `agent_sdk/agent/registry.py`)

### 🔧 Fixes
- RT-001: `agent_sdk/a2ui/catalog.py`'s `_field_summary` no longer reads
  `vars(cls).get("__annotations__", {})` to decide whether a card declared a field itself. That is a
  CPython implementation detail, not a portable check: under PEP 649 (Python 3.14+) a class body's
  annotations compile to a lazy `__annotate__` and `__annotations__` is absent from the class
  `__dict__` until something forces it, but only for classes in a module WITHOUT
  `from __future__ import annotations` (which still stores strings eagerly). The RT-008 "a domain card
  that redeclares `metadata` keeps it in its LLM teaching string" carve-out was therefore inert on
  3.14 — the check answered False for every field — while working on 3.12/3.13, silently dropping the
  field across the declared `requires-python = ">=3.12"` range. The three regression tests that were
  meant to lock it (`tests/test_a2ui_wire.py`) could not catch it: that module declares the future
  import at line 9, so its card classes took the eager-string path and passed against broken code.
  Replaced with `_own_annotation_names()`, which uses `inspect.get_annotations` (non-inheriting and
  PEP-649-aware), requesting `annotationlib.Format.FORWARDREF` on 3.14+ so an unresolvable forward
  reference in a domain card's annotation yields a placeholder instead of raising. New coverage pins
  the cards in `tests/_rt001_no_future_annotations_cards.py`, a helper module that deliberately omits
  the future import, plus a guard asserting the raw read cannot return
  (`tests/test_rt001_field_summary_pep649_portable.py`). (`agent_sdk/a2ui/catalog.py`)
- RT-003: a domain `ContentModel` subclass's `metadata` now reaches `to_plain_text()`. See the
  `_body_text()` entry under Breaking changes above for the mechanism and migration (none required).
  (`agent_sdk/models/content_types.py`)
- RT-004: the admin console now renders the SDK-wide `metadata` envelope for every component type
  (`agent_sdk/console/static/a2ui.js`, `console.css`). `metadata` is declared on `ContentModel`
  itself, so no per-component renderer owned it — and none of the 14 read it, leaving the console
  (the surface `/acceptance --ux` drives) blind to the whole GH-63 envelope. That made the GH-149
  migration path unrenderable on the only renderer the SDK ships: with `fundName` removed and the
  card title fixed to the string "Fund performance", the migration callout in this release names
  `metadata={"fund": "Fund III"}` as a supported way to carry fund identity, yet an agent following
  it saw N identically-titled cards with nothing to tell them apart. A new `appendMetadataFootnote()`
  is applied once at `paintSurface`'s single dispatch point rather than inside `card()` (which
  receives only title/subtitle/children, never the data), so all 14 renderers and every future domain
  card are covered — mirroring `ContentModel.to_plain_text()` appending `_metadata_suffix()` once on
  the base class. Values land as text nodes (the file's untrusted-output invariant), object values are
  JSON-stringified rather than `[object Object]`, and a non-object binding — `MarketBriefing`'s prose
  exception — renders no footnote instead of throwing out of the renderer. Covered by
  `tests/test_rt004_console_renders_metadata_envelope.py`, which runs the real shipped function under
  node. (`agent_sdk/console/static/a2ui.js`, `agent_sdk/console/static/console.css`)
- RT-005: `BedrockModelClient.converse()`'s botocore version-floor escape hatch now actually reaches
  the operator, and only fires for that one condition (`agent_sdk/agent/bedrock.py`). The RT-A05
  `except RuntimeError: raise` delivered neither: (1) the escaping exception is not an `AgentError`,
  so `run_loop` (which catches only `AgentError`) does not handle it and it lands in
  `run_task_worker`'s generic handler, which logs `type(exc).__name__` with no message and no
  `exc_info` and maps the wire response to the fixed literal "internal error" — the
  "upgrade boto3>=1.39" instruction reached neither the log nor the wire, and the only observable
  change from the original fix was 502 UPSTREAM becoming 500 internal error; (2) the catch was
  unconditional, so any other `RuntimeError` from boto3 or the bounded executor (e.g.
  `ThreadPoolExecutor`'s "cannot schedule new futures after shutdown" after `shutdown()`) also escaped
  as a non-`AgentError` and bypassed `run_loop`'s `AgentError` → `DoneEvent` path.
  `require_bearer_auth_botocore()` now raises a dedicated `BedrockBearerAuthUnsupported` (a
  `RuntimeError` subclass, so `app.py`'s Layer-2 startup probe is unaffected); `converse()` catches
  that class only, logs the instruction at `ERROR` (the string is SDK-authored, so SI-2 holds), then
  re-raises. `tests/test_rta05_bedrock_bearer_runtime_error_unmasked.py` now asserts the text reaches
  an operator log and that an unrelated `RuntimeError` still maps to `AgentError(UPSTREAM)`.
  (`agent_sdk/agent/bedrock.py`)
- RT-002: deleted `agent_sdk/agent/loop.py`'s byte-identical private copy of component C-007 —
  `_CONTROL_CHAR_MAP` and `_sanitize_model_name` duplicated `agent_sdk/common/redact.py`'s
  `_CONTROL_CHAR_MAP` and `sanitize_text(s, max_len=64)` character-for-character, comment block
  included, while `content_types.py` already imported the shared helper. Both model-supplied-name call
  sites now call `sanitize_text` (its default cap is 64, matching the deleted copy), so the two cannot
  drift on the control-char set (C0 + DEL + C1 — a narrower `range(0x20)` copy would defeat the SI-2
  guard) or on the length cap. `workspace/components/README.md`'s C-007 row moved from `planned` to
  `present` and its body now lists the landed call sites; it previously still read "the pattern is
  currently inline at loop.py" and "the existing `redact.py` only masks secret-named keys/bearer
  values, not control chars" — both false once the helper landed, and exactly the stale description
  that invites a third divergent copy. `tests/test_rt002_c007_sanitize_text_single_definition.py`
  asserts the control-char map is defined in one file only. (`agent_sdk/agent/loop.py`)
- GH-147: `run_loop`'s no-tool-call completion branch (`agent_sdk/agent/loop.py`) now folds the
  assistant's final plain-text turn into `messages` before returning. Previously the fold block
  that appends `{"role": "assistant", "content": [...]}` only ran on the tool-call path — the
  no-tool-call branch returned first — so a completed task's `record.messages` never contained
  the model's own final reply (it only ever reached the wire via `status.message`). A2A `contextId`
  continuation (`context_messages()` replay in `agent_sdk/routes/a2a.py`) therefore never showed the
  model what it said on the prior turn. Same root cause produced a second defect: a tool-using
  task's stored transcript always ended on the `user` toolResult message, and continuation appended
  another `user` message — two consecutive same-role entries, malformed for Converse-shaped
  backends (Bedrock). When every text segment is empty/whitespace there is nothing to fold, so
  `run_loop` instead calls `bridge_trailing_user` (`agent_sdk/agent/loop.py`), which appends a fixed,
  SDK-authored synthetic assistant turn (`"(no response)"`, never derived from model or tool output —
  SI-2) so `messages` still never ends on `user`. AG-UI is unaffected — it folds the client-resent
  transcript and never calls `context_messages()`.
  **Note for `TaskStore` subclassers:** this changes the persisted shape of `record.messages` — a
  completed no-tool-call task now carries a trailing assistant message it did not carry before.
  `bridge_trailing_user` is not limited to that one branch: `run_loop` calls it on every exit that
  can land with `messages` still ending on a `user` turn — deadline exceeded (`loop.py:430`), token
  budget exceeded (`loop.py:434`), an upstream `AgentError` from `model.converse` (`loop.py:448`),
  and max-turns exceeded (`loop.py:817`), in addition to the empty-text no-tool-call branch
  (`loop.py:476`) — so the fixed `"(no response)"` synthetic assistant turn can land in persisted
  `record.messages` on any of these five FAILED/max-turns exits too, not only on a completed
  no-tool-call task. Any external durable `TaskStore` implementation that reads or replays
  `messages` directly should account for the new entry on all five paths. Landed first in w039
  group:A — GH-150 below was developed and tested against this already-updated fold logic. Covered by
  `tests/test_gh147_assistant_turn_fold.py`. (`agent_sdk/agent/loop.py`)
- GH-145: `BedrockModelClient._boto_client()`'s bearer-token branch (`agent_sdk/agent/bedrock.py`)
  now pins `config=botocore.client.Config(signature_version="bearer")` on the boto3 client instead
  of relying on botocore's own signer selection. botocore's choose-signer handler chain
  (`_set_auth_scheme_preference_signer` / `_should_prefer_bearer_auth`) decides bearer-vs-sigv4 by
  reading the REAL process `os.environ` for `AWS_BEARER_TOKEN_BEDROCK` directly — it never
  consults the isolated `token_provider` component this client registers on its own botocore
  session. Since the bearer token is deliberately never written to the real env (SI-6), that check
  always saw no token, silently fell back to sigv4, and sigv4 then failed with
  `NoCredentialsError` because no real IAM credentials exist in a bearer-only deployment. This was
  not a macOS-vs-Linux botocore difference — macOS only appeared to work when
  `AWS_BEARER_TOKEN_BEDROCK` happened to be ambiently present in that machine's real env (itself a
  quiet SI-6 leak); Linux correctly has no such var and failed honestly. SI-6 isolation is
  unchanged: the fix pins a client config value and does not write the token to `os.environ` or
  argv. Covered by `tests/test_bedrock_credential_store.py` (asserts
  `meta.config.signature_version == "bearer"`, and that resolution still succeeds with
  `AWS_BEARER_TOKEN_BEDROCK` absent from the real env). (`agent_sdk/agent/bedrock.py`)
- RT-006: `BedrockModelClient.converse`'s catch-all (`agent_sdk/agent/bedrock.py`) had started
  interpolating `type(exc).__name__` into `AgentError.message` as part of the GH-145 diagnosis work
  above — but that message is not operator-only: `run_loop` turns it into `DoneEvent(ok=False,
  error=...)`, which `runner.py` echoes verbatim to the untrusted A2A caller as both the wire
  `WireError` and the user-facing `Message`. A client could therefore learn the upstream provider is
  Bedrock and its exact auth/quota failure mode (`NoCredentialsError` / `UnauthorizedException` /
  `ThrottlingException`) from a failed run. No GH-145 AC asked for a wire-message change. The class
  name now goes to `logger.warning` before the raise instead; the wire message is back to the fixed,
  generic `"model invocation failed"`, matching `OpenAIModelClient`'s existing behavior
  (`agent_sdk/agent/openai_client.py`). SI-2 unchanged: only the class name is ever logged, never
  `str(exc)`. Covered by `tests/test_rtb002_bedrock_error_class_enrichment.py`.
  (`agent_sdk/agent/bedrock.py`)
- GH-150: `tasks_cancel` (`agent_sdk/routes/a2a.py`) now repairs a cancellation-induced dangling
  `toolUse` block. `run_loop` folds a turn's assistant `toolUse` message into `record.messages`
  before running that turn's per-tool-call loop, and only appends the matching `toolResult`
  message once every tool call in the turn finishes (`agent_sdk/agent/loop.py`) — `run_loop` is
  called with `messages=record.messages` by reference, and `run_task_worker`'s `CancelledError`
  handler deliberately re-raises without repairing `messages` ("the canceller owns cleanup"). A
  task cancelled while a tool call was still in flight — blocked inside the tool's own execution,
  or parked in `input-required`/`auth-required` awaiting an interrupt's resume — therefore left
  `record.messages` ending on the assistant `toolUse` message with no matching `toolResult`.
  `context_messages()` (§3 contextId continuation) then replayed that broken transcript verbatim
  on the next turn, which Converse-API-shaped backends (Bedrock) reject outright. Before
  committing the `CANCELED` transition, `tasks_cancel` now detects an unresolved `toolUse` tail
  (the last message is `assistant` with one or more `toolUse` blocks) and appends a synthetic
  `{"role": "user", "content": [{"toolResult": {..., "status": "error"}}]}` message — one error
  `toolResult` per dangling `toolUseId` — immediately after the `toolUse` message, restoring the
  alternating assistant/user Converse shape the SDK relies on; the repair's success/failure outcome
  is then threaded into `set_task_status`, which gates the durable `CANCELED` `persist_status`
  flush on that transcript repair (and its own `persist_messages` flush) having actually landed —
  fail-closed, so a client is never told a task is durably `CANCELED` while a store might still
  hold the unrepaired, replay-breaking transcript. SI-2: the synthetic `toolResult`
  text (`_CANCELLED_TOOL_RESULT_TEXT`) is a single fixed SDK-authored string; it never
  interpolates the tool name, arguments, or an upstream exception. Landed against GH-147's
  already-updated assistant-turn-fold logic in `agent_sdk/agent/loop.py` (w039 group:B, after
  group:A). Covered by `tests/test_gh150_cancel_dangling_tooluse.py` — cancellation mid-tool-call
  via a blocking tool, cancellation while parked awaiting an interrupt resume, and a `contextId`
  continuation replay after cancellation, all asserting no `toolUse` block anywhere in
  `record.messages` (or the replayed prior-turn history) ever lacks an immediately-following
  matching `toolResult`. (`agent_sdk/routes/a2a.py`)
  **Note for `TaskStore` subclassers (RT-005):** `tasks_cancel` (and `agent_sdk/agent/runner.py`'s
  deferred background awaiter and terminal exception handlers, which call the same
  `repair_dangling_tool_use` helper) mutate `record.messages`/`record.pending_tool_results` directly
  on the `TaskRecord` object `TaskStore.get()` returned — there is no separate write call.
  `InMemoryTaskStore` needs nothing further, since its `get()` hands back the live record by
  reference: the in-place mutation IS the write. A durable `TaskStore` (the external
  `AzureTableTaskStore` shape this ABC exists for) whose `get()` deserializes a FRESH copy from
  storage on every call will silently drop every such repair unless it overrides the new
  `TaskStore.persist_messages(record)` hook (`agent_sdk/tasks/store.py`, non-abstract, default
  no-op — mirrors the `interrupt_ttl_remaining` precedent from 0.5.40) to flush `record.messages`
  back to the backing store keyed by `record.task.id`. **`record.pending_tool_results` is NOT part
  of this flush** — despite also being mutated in place by the same repair, it is runtime-only turn
  state (never serialized, per its own field comment on `TaskRecord`, `agent_sdk/tasks/store.py`)
  exactly like `worker`/`resume_future`; a subclass whose own resume path needs to reconstruct
  mid-turn sibling-tool-call results has to track that field itself. `repair_dangling_tool_use` now
  takes an optional `store=` keyword and calls this
  hook once, unconditionally, after its own repair/bridge — every one of its five call sites
  (`routes/a2a.py`'s `tasks_cancel`, and `runner.py`'s deferred-success path, deferred-failure
  `_fail`, and both `run_task_worker` terminal exception handlers) now passes its own `store`.
  Covered by `tests/test_rt005_gh150_taskstore_persist_messages_hook.py`, including a
  copy-on-`get()` fake store proving a repair is silently lost without the override and survives
  with it.
  **RT-B-003 follow-up: overriding `persist_messages` alone is NOT sufficient.** `tasks_cancel`
  also mutates `record.task.status` directly on the same `TaskRecord` object, right before it
  calls `repair_dangling_tool_use(store=store)` — and until now there was no matching write hook
  for that field. A durable `TaskStore` that overrode only `persist_messages` never learned the
  task went `CANCELED`: `context_messages()` filters continuation candidates on
  `r.task.status.state in TERMINAL_STATES`, so the repaired transcript `persist_messages` just
  flushed was never read back — a cancelled task was never a `contextId` continuation candidate at
  all. `TaskStore.persist_status(record)` (`agent_sdk/tasks/store.py`, non-abstract, default
  no-op, same precedent) closes this; `tasks_cancel` now calls it right after the `CANCELED`
  assignment. **A durable subclasser must override both `persist_messages` AND `persist_status` —
  either alone still loses data.** Covered by
  `tests/test_rtb003_taskstore_persist_status_hook.py`, including the same
  gap-without-override/survives-with-override pairing, asserted via `context_messages()` staying
  empty vs. non-empty.
  **RT-B-008: `TaskStore.persist_status` gained ten more call sites, not documented above.**
  `tasks_cancel` was, until now, `persist_status`'s ONLY caller in the SDK — the note above
  describes exactly that one call site. `agent_sdk/agent/runner.py`'s `_set_status` is now the
  single choke point for every in-place `record.task.status` mutation the worker makes (WORKING,
  COMPLETED, FAILED, AUTH_REQUIRED, INPUT_REQUIRED, across both `run_task_worker` and
  `_run_deferred_background`) and flushes `persist_status` after each one when given its own
  `store=` — including every streamed `TextEvent`/`ProgressEvent`/`NoteEvent`/`ToolProgressEvent`
  chunk's WORKING transition, not only the terminal one. `TaskStore.persist_status`'s own
  docstring (`agent_sdk/tasks/store.py`) previously described only the single `tasks_cancel` call
  site and has been updated to state the real call pattern. **This is a contract change for
  external subclassers, not merely an internal refactor:** a durable override sized against "one
  write per task, at cancel" now receives one write per status transition — including several per
  streamed chat turn. A subclasser that wants a write only on the terminal transition must filter
  on `record.task.status.state` itself; the hook does not do that filtering. No behavior change in
  this release (the per-transition call pattern was already shipping, covered by
  `tests/test_rtb008_set_status_persist_status_choke_point.py`) — this entry closes the
  documentation gap RT-B-003 (redteam) found between that shipped behavior and both this
  CHANGELOG and the ABC docstring.
  **RT-B-001 (round 2): the "override both hooks" guarantee above was not actually true.**
  `TaskStore.persist_messages` had exactly ONE call site in the whole SDK —
  `repair_dangling_tool_use` — which never runs on a normal completion (there is no dangling
  `toolUse` tail to repair). RT-B-008's `persist_status`-on-every-transition fix therefore let a
  durable store observe a task going COMPLETED/FAILED on the dominant, non-cancelled happy path
  without `persist_messages` ever having been called for it — so a subclasser who faithfully
  overrode both hooks, exactly as instructed above, still got a durable record that was terminal
  over an empty or stale transcript, and `context_messages()`'s `TERMINAL_STATES` filter would
  select and replay it on the next `contextId` continuation. `set_task_status`
  (`agent_sdk/agent/runner.py`) now also flushes `TaskStore.persist_messages(record)` itself on
  every `TERMINAL_STATES` transition, BEFORE `persist_status` — mirroring `tasks_cancel`'s own
  RT-B-007 fail-closed ordering: `persist_status` runs only once the messages flush has actually
  succeeded, so a failure leaves the durable record correctly non-terminal rather than terminal
  over a transcript that never arrived. RT-B-104: the same pair of flushes, under the same
  ordering, now also fires on an `INTERRUPT_STATES` transition (`AUTH_REQUIRED`/`INPUT_REQUIRED`)
  — status alone is not a coherent record of an interrupted task without its matching
  `record.messages` transcript alongside it, so a durable store needs both to have anything to
  resume from restart. (`record.pending_tool_results` is explicitly NOT covered by this flush —
  see the `persist_messages` docstring correction above; it stays runtime-only, exactly like
  `worker`/`resume_future`, on both the terminal and interrupt paths.) **The "override both hooks"
  guarantee is now actually satisfied**: a
  durable subclasser overriding both `persist_messages` and `persist_status` gets a correct
  transcript-then-status flush on every terminal and interrupt transition, cancelled or not,
  repaired or not — `persist_messages` is no longer reachable only through the cancel/repair
  path. Covered by `tests/test_rtb001_terminal_persist_messages_flush.py`, including a
  copy-on-`get()` durable double proving `context_messages()` returns the real transcript (not
  `[]`) after a normal, non-cancelled completion, and an ASGI-level end-to-end reproduction of the
  original finding.
  **Redteam follow-up (RT-004): `TaskStore.context_messages()`'s admin cross-identity override,
  framed as "operator task inspection," was materially wider exposure than that framing suggested
  — and a prior pass had ratified it as intended SDK policy without ever putting the decision to
  the user.** `routes/a2a.py`'s `_create_task_record` calls this method on every fresh
  `message/send`/`:stream` (no `taskId`) and folds the result straight into the new task's
  `record.messages`, which is then sent to the model — this is `contextId` continuation, the same
  path a same-identity caller uses to keep talking in their own thread, not a side, read-only
  inspection view. An admin `api_key` identity had no separate inspection-only entry point into
  this data: submitting a fresh `message/send` against ANOTHER identity's `contextId` (there is no
  ownership check on a bare `contextId`, only on an existing `taskId` — DESIGN.md §5.1) inherited
  that identity's transcript straight into the admin's own new task and, from there, the upstream
  model's context — a data-exposure policy decision no wave's own redteam pass may self-ratify.
  **The bypass is removed, not documented further:** `context_messages()` is now identity-scoped
  exactly like `context_reusable_messages()` already was (no admin exception, RT-004) — a
  cross-identity `contextId` now simply starts a fresh continuation with no inherited history,
  admin or not. Genuine operator inspection of another identity's task remains available, safely,
  as a read that never seeds a new task's model context: `GET /v1/tasks/{id}` (unaffected). The
  now-dead `agent.reuse.strip_resolved_markers` mitigation (added when the bypass was only
  partially closed) is deleted along with it. Covered end-to-end by
  `tests/test_admin_continuation_scoped_to_own_identity.py`, which drives two real
  `POST /v1/message:send` requests on the same `contextId` (a non-admin identity, then the default
  admin identity with no `taskId`) through the live ASGI app and asserts the admin's continuation
  turn never receives the other identity's prior text. (`agent_sdk/tasks/store.py`,
  `agent_sdk/tasks/memory.py`, `agent_sdk/agent/reuse.py`, `DESIGN.md`)
- **RT-B-003: corrects the "no behavior change" claim in the RT-B-008 entry above — there now is
  one.** `set_task_status` (`agent_sdk/agent/runner.py`) flushed `TaskStore.persist_status` on
  every in-place status mutation, including the repeated `WORKING` transition applied once per
  streamed `TextEvent`/`ProgressEvent`/`NoteEvent`/`ToolProgressEvent` chunk — a durable write per
  chunk of agent text, on a plain synchronous hook a durable subclass's own network call can block
  the event loop from inside. `set_task_status` now flushes this hook by default only for
  `TERMINAL_STATES` and `INTERRUPT_STATES` — the transitions durability actually depends on — never
  for `WORKING`. A subclass that still wants the old every-transition granularity (e.g. to drive a
  live status dashboard) opts back in with the new `TaskStore.persist_every_status = True` class
  attribute (`agent_sdk/tasks/store.py`); `persist_status`'s own docstring has been rewritten to
  describe this exact call pattern and the opt-in, replacing the single-caller ("`tasks_cancel`
  only") description it carried before RT-B-008. Covered by
  `tests/test_rtb008_set_status_persist_status_choke_point.py` (now asserting the gated pattern)
  and `tests/test_rtb007_persist_status_ordered_after_repair.py`. (`agent_sdk/agent/runner.py`,
  `agent_sdk/tasks/store.py`)
- **RT-B-002: `repair_dangling_tool_use`'s RT-005 `persist_messages` flush was unguarded at 3 of
  its 5 call sites.** `tasks_cancel` (`routes/a2a.py`) already wrapped its call in try/except; the
  other three — `_run_deferred_background`'s `_fail` closure, and `run_task_worker`'s `except
  AgentError`/`except Exception` terminal handlers, all in `agent_sdk/agent/runner.py` — called the
  raw helper directly, all three sitting BEFORE the try/finally that guarantees the terminal FAILED
  transition, the terminal publish, and `close_streams`. A durable store whose `persist_messages`
  override raised on its own write failure escaped each of these three sites — out of a
  fire-and-forget `asyncio.Task` for `_fail`, straight out of `run_task_worker` for the other two —
  leaving the task stuck WORKING (or, for the deferred path, un-terminated) with its streams never
  sentinel-closed, until the TTL sweep. New `repair_dangling_tool_use_safe` (`agent_sdk/agent/runner.py`)
  is the one guarded entry point every out-of-loop caller now uses instead of hand-rolling its own
  try/except around the raw helper (the exact drift that left `tasks_cancel`'s copy diverging from
  the other four): it degrades a `persist_messages` failure to a logged `error_type`-only
  `logger.error` (SI-2) and returns `False`, never propagating the raise. Covered by
  `tests/test_rtb002_runner_repair_failure_still_terminates.py` (all three sites) and
  `tests/test_rtb002_cancel_repair_failure_still_publishes_final.py` (the pre-existing
  `tasks_cancel` site, migrated onto the same wrapper). (`agent_sdk/agent/runner.py`)
- RT-B-007 / RT-B-008: two hardening fixes inside `repair_dangling_tool_use` itself
  (`agent_sdk/agent/runner.py`), independent of any `TaskStore`. **RT-B-007:** every synthetic
  `toolResult` block built for a turn with several dangling `toolUseId`s embedded the SAME
  `content` list object by reference — the caller's own `default_content`, or a shared
  pending/override entry — across every one of them, and that object was still reachable by the
  caller; a later mutation of it (by the caller, or by a store's serializer) silently rewrote every
  one of those transcript entries at once. Each block now embeds `list(content)`, a copy, so the
  transcript owns its own list regardless of which source (default/pending/override) supplied it.
  **RT-B-008:** the tail-message read (`messages[-1].get("role")`) had no `isinstance(messages[-1],
  dict)` guard, unlike the `pending_tool_results` loop just above it (which already checks each
  block) — a non-dict tail entry (a durable store deserialising loosely, or a future caller
  appending something other than a plain dict) raised `AttributeError`, which — per RT-B-002 above
  — escaped every one of this helper's callers before that fix landed. The tail read, and the
  `toolUse` block iteration over its content, both now guard with `isinstance(block, dict)`; a
  non-dict tail is treated as "nothing to repair" rather than crashing. Covered by
  `tests/test_rtb007_rtb008_repair_dangling_tool_use_hardening.py`. (`agent_sdk/agent/runner.py`)
- RT-007: `reuse_fields_for_model` (`agent_sdk/agent/reuse.py`) now raises `TypeError` at
  `@tools.tool` registration time for either shape `ReuseKind` cannot actually support, instead of
  shipping a silent no-op or a permanently-failing tool. `ReuseKind` only works on a top-level
  scalar field: (1) a container field (`Annotated[list[str], ReuseKind("entity_id")]`) — the
  substitution/validation contract in `resolve_reuse_fields` matches a raw argument against a
  resolved value with a single equality check, so a *correct* list argument (e.g. `["ENT_1"]` when
  `ENT_1` IS the resolved id) was permanently rejected as a mismatch, with no way to ever satisfy
  the check; (2) `ReuseKind` on a field of a nested model — `reuse_fields_for_model` and the loop
  only ever look at `input_model`'s own top-level fields, so the annotation was silently inert and
  any `$ref:` token there reached the tool verbatim with no substitution and no validation. Both are
  now detected at decoration time (checked recursively through Optional/list/tuple/set/dict, so a
  nested model buried inside a container field is caught too) and documented as unsupported on
  `ReuseKind`'s own docstring. Covered by `tests/test_rt007_reuse_kind_scalar_only.py`.
  (`agent_sdk/agent/reuse.py`)
- RT-002: `ToolEntry.invoke_any()` (`agent_sdk/agent/registry.py`) now unwraps a `Reusable`-returning
  tool's result to `.value`, mirroring `agent/loop.py`'s own unwrap (`loop.py:756-772`) instead of
  returning the raw `Reusable` dataclass verbatim to every OTHER dispatch surface. `invoke_any()` is
  the shared helper behind three callers with no `messages` transcript of their own — MCP
  `tools/call` (`routes/mcp.py`), the admin try-tool endpoint (`routes/admin.py`), and the
  commitments executor (`contrib/commitments/executor.py`) — so a Tier-1 tool returning `Reusable`
  broke identically on the first two: MCP folded the wrapper's dataclass repr
  (`"Reusable(value='ENT_5831', kind='entity_id', label='...')"`) onto the wire for a tool with no
  `emits`, and raised the SC-C1 coercion's `ValidationError` ("tool output coercion failed") for a
  tool that DOES declare `emits` (coercing the raw wrapper, not `.value`, against the declared
  model) — the identical call succeeding over A2A/AG-UI, a §5.6 surface-parity violation. The admin
  try-tool endpoint leaked the wrapper's raw fields (`{"value": ..., "kind": ..., "label": ...}`)
  through `_safe_result` instead of the tool's actual result shape. The unwrap runs AFTER any
  `DeferredResult` chain is resolved, since a deferred handle may itself resolve to a `Reusable`.
  **By design, not fixed here:** the `ReuseKind` `$ref:<kind>` substitution/validation gate
  (`resolve_reuse_fields`) stays conversation-scoped — it only runs on `agent/loop.py`'s direct
  `invoke`/`invoke_gen` path, which is the sole caller with a `messages` transcript to scan for prior
  `__resolved__` markers and fold an `AuditEvent` audit into. A `Reusable`-returning tool invoked via
  MCP, the admin console, or a commitment never grows the resolved index and never accepts a
  `$ref:<kind>` token on that same call — those three surfaces do not participate in the GH-148
  cross-turn mechanism at all, only in not leaking its wrapper type (see RT-A-009 below for what
  "never accepts" means in practice on those three surfaces). Covered by
  `tests/test_rt002_invoke_any_reusable_unwrap.py`. (`agent_sdk/agent/registry.py`)
- RT-A-009: closes a gap the RT-002 entry above left open — "never accepts a `$ref:<kind>` token"
  shipped as silent PASSTHROUGH, not rejection. `ToolEntry.invoke_any()` handed a `$ref:<kind>` or
  `$raw:<value>` token on a `ReuseKind` field straight to the tool body as an ordinary string
  (validated and executed like any other value), instead of erroring, on all three transcript-free
  surfaces — MCP `tools/call`, the admin try-tool endpoint, the commitments executor. A tool would
  then look up an entity literally named `"$ref:entity_id"` and return a wrong-but-successful result;
  an MCP client (or any caller of these surfaces) that read the token syntax off this very CHANGELOG
  entry or the loop-side `input_schema(include_reuse_hint=True)` description had no way to know it
  would silently misfire rather than error. `invoke_any()` now rejects any `decl.reuse_fields`
  argument starting with `REF_PREFIX` (`$ref:`) or `RAW_PREFIX` (`$raw:`) — regardless of the field's
  own `strict`/`allow_raw_override` flags, which only govern the loop.py path and have no meaning
  here — via a generic `AgentError(ErrorCategory.VALIDATION, ...)` that every caller already maps to
  its existing failure shape (`isError: true` for MCP, `ok: false` for admin, `mark_failed` for the
  commitments executor). Covered by `tests/test_rt_a009_invoke_any_reuse_token_rejection.py`
  (registry-level + a real `CommitmentExecutor` end-to-end) and
  `tests/test_gh148_reuse_kind_substitution.py`'s renamed
  `test_mcp_tools_call_ref_token_rejected_no_conversation_transcript` /
  `test_mcp_tools_call_raw_override_token_rejected_no_conversation_transcript` (MCP end-to-end).
  (`agent_sdk/agent/registry.py`)
- RT-004: `agent_sdk.agent.loop._fold_result_content` is renamed to the public `fold_result_content` —
  `agent_sdk/agent/runner.py`'s deferred (GH-87) background awaiter now imports and calls it directly
  so a deferred tool's terminal `toolResult` message folds through the exact same content-shaping
  rule as every synchronous tool call, instead of duplicating that logic. No behavior change for
  existing callers. (`agent_sdk/agent/loop.py`, `agent_sdk/agent/runner.py`)
- RT-A-008: a `ReuseKind` field left at every default (`strict=True`, `allow_raw_override=False`) had
  no in-band recovery path for a genuinely new, legitimate raw value once any resolution of its kind
  existed — the mismatch rejection is deliberately silent about the `$raw:` override token (RT-002),
  and that token is off by default anyway, so the model could only keep calling the resolver tool
  until `max_turns` was exhausted: a correctness gate with no documented recovery path traded a
  correctness bug for a liveness bug. `resolve_reuse_fields` (`agent_sdk/agent/reuse.py`) gained an
  optional `reject_counts` parameter — a caller-owned `(tool_name, field_name) -> consecutive
  rejection count` map as shipped in this entry (**RT-C-001 below narrows the key** to
  `(tool_name, field_name, repr(raw value))` — see that entry for why the field-only key is unsafe;
  every description below of what increments/resets the count refers to the narrowed key), mutated in
  place — and `agent/loop.py` now threads one through, scoped to a
  single `run_loop` call (`reuse_reject_counts`, initialized alongside `resolved_index`). Once a field
  has been rejected `MAX_CONSECUTIVE_REUSE_REJECTIONS` (2) times in a row for the mismatch reason, the
  next call passes the raw value through unchanged instead of rejecting again, recorded as a
  `ReuseSubstitution(via_forced_passthrough=True)` and surfaced as a distinct, auditable
  `AuditEvent(code="reuse_forced_passthrough")` (and a `logger.warning`, not the `logger.info` the
  `$ref`/`$raw:` substitution paths use, since this is an automatic liveness fallback, not an
  operator-authorized bypass) — never silence. The count resets whenever that same field resolves via
  `$ref`, a `$raw:` override, or a raw value that actually matches: the budget guards a stuck retry
  loop on the SAME wrong value, not a running total across the whole conversation. This is
  unconditional — it applies regardless of `strict`/`allow_raw_override`, since it exists precisely
  for the field that opted into neither. As shipped in this entry the bound covers the raw-value-mismatch
  rejection only — the raw-value-**ambiguity** rejection (RT-A-006 above: a bare raw value submitted
  while more than one resolution of the kind is on record) is exempt too, via its own early `return`
  ahead of the counter, and therefore rejects forever with no liveness fallback even though it has no
  more of an in-band recovery move than the mismatch case does. **RT-B-002 below closes that gap**,
  folding the ambiguity rejection into the same bound. Neither shape ever counted, nor counts now, a
  `$ref`-token rejection — malformed `$ref`, wrong-kind `$ref`, unresolved `$ref`, a `$ref` that
  resolves to more than one value, or a label matching nothing — since the model already has a real
  in-band recovery move for any of those: fix the `$ref` token itself.
  `reject_counts` defaults to `None` (every caller predating RT-A-008, and every direct unit
  test of `resolve_reuse_fields`) and preserves the original reject-forever behavior byte-for-byte.
  Covered by `tests/test_rt_a008_reuse_bounded_recovery.py` — the `resolve_reuse_fields(reject_counts=
  ...)` contract directly (recovery after the bound, per-`(tool, field)` scoping, reset-on-success,
  the unchanged rejection text up to the bound) and an end-to-end `run_loop` repro of the exact stuck
  shape RT-A-008 describes. (`agent_sdk/agent/reuse.py`, `agent_sdk/agent/loop.py`)
- RT-C-001: the RT-A-008 bounded-recovery budget above is scoped to the exact `(tool_name, field_name,
  repr(raw value))` triple, not merely `(tool_name, field_name)` — keying on the field alone let a
  sequence of three *different* hallucinated raw values exhaust one shared budget, forcing the third
  through unvalidated and reopening the exact GH-148 failure mode this mechanism exists to catch. Only
  a genuinely stuck retry of the identical value now earns the passthrough. `resolve_reuse_fields`
  gained `max_consecutive_rejections` (the threshold `reject_counts` is checked against), which
  `agent/loop.py` threads through from the new `LoopPolicies.reuse_forced_passthrough_limit`.
  (`agent_sdk/agent/reuse.py`, `agent_sdk/agent/loop.py`)
- RT-B-002: the RT-A-008 bound above shipped counting only the plain mismatch rejection reason —
  the RT-A-006 raw-value ambiguity rejection (more than one resolution of the kind on record) was
  decided and returned early, ahead of the `reject_counts` check, so it never incremented or consulted
  the counter and rejected forever regardless of `reject_counts`/`max_consecutive_rejections`, even
  though it has no more of an in-band recovery move for a genuinely new value than the mismatch case
  does (the `$ref:<kind>:<label>` disambiguation it points to is itself rejected by RT-A-007 for a
  label not already on record) — the RT-A-008 liveness fallback silently didn't cover the shape most
  conversations that resolve two entities of one kind actually hit. `resolve_reuse_fields`
  (`agent_sdk/agent/reuse.py`'s `resolve_reuse_fields`, the `elif resolved_for_kind and (strict_fields
  ...)` branch) now decides the rejection reason (mismatch vs. ambiguity) into
  one `reject_reason` local first, then runs both through the SAME `reject_counts` boundary — a `$ref`-
  token rejection (malformed, wrong-kind, unresolved, multi-match, label-matches-nothing) is unchanged
  and still never counted, since the model already has a real in-band recovery move there (fix the
  `$ref` token itself). Covered by `tests/test_rt_b002_reuse_bounded_recovery_ambiguity.py`
  (`test_ambiguity_rejection_is_bounded_like_the_mismatch_rejection`,
  `test_ambiguity_and_mismatch_share_one_consecutive_budget`,
  `test_ref_token_rejections_are_not_counted`). (`agent_sdk/agent/reuse.py`)
- RT-020: `resolve_reuse_fields`'s raw-value match check used exact type identity
  (`_raw_matches_resolved`), so a value pydantic would coerce and accept as identical to an
  already-resolved one — e.g. the string `"5831"` on an `int`-typed field already resolved to `5831` —
  was rejected here, before the tool was ever reached, purely because the model's raw JSON argument
  and the resolved value differ in Python type. New `ToolDecl.reuse_field_types`
  (`agent_sdk/agent/registry.py:372-378`, built by `reuse_field_types_for_model` in
  `agent_sdk/agent/reuse.py`) maps each `ReuseKind` field to its declared, Optional-stripped
  scalar type; `resolve_reuse_fields` (new `field_types` parameter) runs a raw value through
  `_coerce_raw_for_match` — the same coercion `input_model.model_validate` would apply — before the
  match check, so `"5831"` now matches a resolved `5831`. Coercion never crosses the `bool`/`int`
  boundary in either direction (`bool` is an `int` subclass; a bare `TypeAdapter` would silently turn
  `True` into `1` or `1` into `True`, undoing the RT-014 type-boundary guard `_raw_matches_resolved`
  enforces), and only affects the comparison — `effective_arguments` still carries the raw, uncoerced
  value, so the tool's own `model_validate` performs the real coercion, unchanged. A field absent from
  `field_types`, or `field_types` itself `None` (every caller predating RT-020), falls back to the
  original exact-type-identity check byte-for-byte. Covered by `tests/test_rt020_reuse_type_coercion.py`.
  (`agent_sdk/agent/reuse.py`, `agent_sdk/agent/registry.py`)
- RT-002: `LoopPolicies.reuse_forced_passthrough_limit` now **defaults to `0`** (reject-forever),
  down from `MAX_CONSECUTIVE_REUSE_REJECTIONS` (2). The RT-A-008/RT-C-001 entries above shipped this
  policy defaulting to the module's ceiling constant, which meant the GH-148 gate failed OPEN by
  default: the third consecutive identical wrong raw value was executed unvalidated with no operator
  opt-in. A correctness gate must never default to fail-open — an operator who wants the liveness
  fallback now opts IN by setting a positive `reuse_forced_passthrough_limit`, the same opt-in shape
  `ReuseKind`'s own `strict`/`allow_raw_override` flags already use. DESIGN.md §8.1 and `docs/tools.md`
  now document this as a third escape hatch (the two `ReuseKind` field-level flags being the first two)
  with its default stated explicitly — DESIGN.md previously said only "two escape hatches, both
  operator opt-ins", with no mention of this policy at all. (`agent_sdk/agent/loop.py`, `DESIGN.md`,
  `docs/tools.md`)
- RT-001: every `ReuseKind` map (`reuse_fields`/`reuse_strict`/`reuse_raw_override`/`reuse_field_types`
  on `ToolDecl`, built by `agent_sdk/agent/reuse.py`'s `reuse_*_for_model` functions) is now ALSO keyed
  by the field's bare python attribute name — alongside its wire alias, never instead of it — on a
  model whose config declares `populate_by_name=True`/`validate_by_name=True` (new
  `_accepts_field_name_alias` helper; a bare `alias_generator` with neither flag set does NOT trigger
  this — verified live that pydantic still rejects the field name there). Such a model accepts a tool
  call keyed by EITHER name — contrary to `_wire_field_name`'s previous docstring claim that
  `model_validate` "rejects the plain field name outright, even with `populate_by_name=True`" (verified
  false). Keying the reuse maps on the alias alone therefore let a call keyed by the python field name
  skip the entire GH-148 substitution/validation gate on such a model — both the `$ref:`/`$raw:`
  resolution in `agent/loop.py` and the `invoke_any` RT-A-009 rejection in `agent/registry.py` — while
  `model_validate` accepted it without complaint: the exact silent wrong-but-successful substitution
  GH-148 exists to close, on precisely the field shape (an aliased, camelCase-friendly model with
  `populate_by_name=True`) most likely to use `ReuseKind`. A model that has not opted in — every
  pre-RT-001 `ReuseKind` model — is unaffected: its maps stay keyed by the alias alone, byte-for-byte
  as before. (`agent_sdk/agent/reuse.py`)
- RT-007: the resolved-value index's de-duplication (`agent_sdk/agent/reuse.py`'s `scan_resolved` and
  `agent_sdk/agent/loop.py`'s marker-append) now keys on `(label, type(value).__name__, repr(value))`
  via the new `_index_entry_key` helper, not plain `(label, value)` tuple equality. Python's tuple `==`
  conflates `1`/`True`/`1.0` across a type boundary, so a `Reusable(value=1, ...)` and a later
  `Reusable(value=True, ...)` of the same kind and label collapsed into one index entry — after which
  `_raw_matches_resolved` (which deliberately enforces type identity at MATCH time to stop exactly
  that conflation) could only ever compare against whichever one was indexed first. Mirrors
  `resolve_reuse_fields`'s own `repr`-based `reject_counts` keying. (`agent_sdk/agent/reuse.py`,
  `agent_sdk/agent/loop.py`)
- RT-006: `ToolEntry.input_schema`'s reuse-hint widening (`agent_sdk/agent/registry.py`'s
  `_schema_permits_string`) now resolves a `$ref` (against the schema's own `$defs`) and an `allOf`
  composition before deciding whether a `ReuseKind` field's advertised schema already permits the
  `$ref:<kind>`/`$raw:<value>` string sentinel, and treats any schema carrying an `enum` key — resolved
  or inline — as excluding it, even when every member is itself a string. Previously an unresolved
  `$ref`/`allOf` was assumed to permit a string unconditionally, so an `Enum`-typed `ReuseKind` field
  (accepted by `reuse_fields_for_model` — it is neither a container nor a `BaseModel`) advertised only
  its enum members with no widened string branch: a schema-enforcing provider could never emit the
  `$ref:<kind>` token, and the mechanism silently no-opped on that field — precisely the failure mode
  this widening exists to prevent, just narrowed from "any non-`str`/`int`/`float`/`bool` scalar" down
  to "closed". (`agent_sdk/agent/registry.py`)
- RT-D-001: `resolve_reuse_fields`'s two rejections that recommend `$ref:<kind>:<label>` as the recovery
  move — the multi-match `$ref:<kind>` rejection and the raw-value ambiguity rejection (RT-A-006) —
  now name the kind's own on-record LABELS directly in the rejection text (new `_known_labels_hint`
  helper, `agent_sdk/agent/reuse.py`). Live testing against a real AG-UI thread (3 real
  `POST /ag-ui/run` calls on one `threadId`) found the recovery move those rejections recommend was
  UNREACHABLE there: once two resolutions of a kind existed, both the CORRECT raw value and the bare
  `$ref:<kind>` token were rejected, and the only recovery, `$ref:<kind>:<label>`, needed a label that
  `routes/ag_ui.py::_fold_history` strips from every model-visible transcript (module docstring,
  RT-A-004/RT-001 above) — with `LoopPolicies.reuse_forced_passthrough_limit` defaulting to `0`
  (RT-002 above), this was reject-forever, taking the tool offline for the steady state of any
  multi-entity AG-UI thread (the resolved-index dedup means `InMemoryTaskStore.MAX_REUSABLE_TASKS=50`
  is easily reached by ordinary use). Only the on-record LABELS are now surfaced — tool-author-supplied
  display names, never a resolved VALUE and never the caller's own (possibly wrong) supplied label, so
  SI-2 is unaffected; RT-A-007's own label-mismatch rejection (a label WAS supplied and matched
  nothing) is unchanged. The fix needs no transport-specific plumbing: the rejection text is the tool
  result for THIS call, delivered back to the model on every transport regardless of what a later
  request replays. Covered by a new route-level regression,
  `tests/test_gh148_reuse_kind_substitution.py::test_route_level_ag_ui_ambiguity_rejection_names_a_usable_label_across_runs`
  (two entities resolved on separate `POST /ag-ui/run` calls, a third run's correct raw id rejected
  with a usable label, the follow-up `$ref:entity_id:<label>` call succeeding within that same run) —
  the two-resolution shape only had A2A-shaped (one shared `messages` list) coverage before. Updated
  `tests/test_rt_a006_reuse_label_confusion.py` and
  `tests/test_rt_b002_reuse_bounded_recovery_ambiguity.py`'s exact-rejection-text assertions to match.
  (`agent_sdk/agent/reuse.py`)
- RT-004 (GH-149 follow-up): `FundPerformance.to_plain_text()` (`agent_sdk/models/content_types.py`)
  now includes `pb_id` (as a provenance suffix, mirroring the admin console card's subtitle in
  `a2ui.js`) plus `net_irr`/`gross_irr`/`rvpi`/`quartile` when set. GH-149 moved `pbId` into the
  console card's subtitle but left the mandatory text fallback — sent to every client without A2UI
  capability (DESIGN.md §5.1/§5.4 dual-part `TextPart`) — unaware of it and (at the time) of four
  other wire fields: a `FundPerformance(pbId=..., netIrr=..., grossIrr=..., rvpi=..., quartile=...)`
  card with none of the original irr/tvpi/dpi/moic fields set rendered the literal string
  `"fund performance (no data)"` to those clients even though `wire()` carried real data. RT-004 did
  not reach every wire field, though — six more (`calledDownPct`, `dryPowder`, `dryPowderPct`,
  `distributed`, `remainingValue`, `distributedPlusRemaining`) plus `asOfQuarter`/`asOfYear` were
  still silently dropped by the text fallback; see RT-002 below for the fix that closes the rest of
  the gap. (`agent_sdk/models/content_types.py`)
- RT-002: `FundPerformance.to_plain_text()` (`agent_sdk/models/content_types.py`) now also includes
  `dry_powder`, `dry_powder_pct`, `distributed`, `remaining_value`, `distributed_plus_remaining`,
  `called_down_pct`, `as_of_quarter` and `as_of_year` when set — the six most recently added wire
  fields (four of which the A2UI console card already renders in `a2ui.js::renderFundPerformance`)
  plus the two as-of-period fields were reaching `wire()` and the console card but silently vanishing
  from the mandatory text fallback sent to clients without A2UI capability. A card carrying only
  `calledDownPct`/`dryPowder`/`distributed`/`remainingValue` — a fully populated real-world payload —
  previously rendered the literal string `"fund performance (no data)"` to those clients.
  (`agent_sdk/models/content_types.py`, `tests/test_content_types.py`)
- RT-B-202: `_create_task_record` (`agent_sdk/routes/a2a.py`) no longer calls `bridge_trailing_user`
  directly to re-assert the never-ends-on-`user` invariant on the transcript
  `TaskStore.context_messages()` returns. LRN-144's Check pins that bridge to exactly one call
  site — inside `agent/runner.py::repair_dangling_tool_use` — and an unamended second direct call
  site silently converts that Check into a permanently-failing audit. The re-assertion now routes
  through a new, narrowly-scoped `bridge_context_messages` helper (`agent_sdk/agent/loop.py`): it
  copies the store-supplied `Sequence[dict]` into a fresh list, bridges that copy, and returns it —
  `routes/a2a.py` imports and calls only this wrapper, so `grep -n "bridge_trailing_user"
  agent_sdk/routes/a2a.py` is back to zero matches. LRN-144 updated in the same change to describe
  both call sites explicitly (out-of-loop repair writers vs. this read-side consumption helper) and
  to fix a stale `_repair_dangling_tool_use_safe` reference (the landed symbol has always been the
  public `repair_dangling_tool_use_safe`). (`agent_sdk/agent/loop.py`, `agent_sdk/routes/a2a.py`,
  `workspace/learning/LRN-144-transcript-bridge-must-cover-out-of-loop-writers.md`)
- RT-B-204: `tasks_cancel` (`agent_sdk/routes/a2a.py`) now publishes its terminal `StreamItem` with
  `event=DoneEvent(ok=False, error="task canceled")` instead of `event=None`. A `StreamItem`'s
  `frame` serves A2A SSE consumers; its `event` serves AG-UI's `_RunMapper` (`routes/ag_ui.py`),
  which maps only `.event` — `_RunMapper.map(None)` returns `[]`. Every other terminal publisher in
  the SDK (`run_task_worker`'s terminal handlers, `_run_deferred_background._fail`) already attaches
  a `DoneEvent`; `tasks_cancel` was rewritten in a recent wave and carried `event=None` forward
  unexamined. Before this fix, an AG-UI subscriber streaming a task cancelled through the A2A route
  broke out of its frame loop with `terminal_sent` still `False` and fell through to the generic
  `RUN_ERROR: "stream ended unexpectedly"` — a misleading error for a deliberate, successful
  cancellation — while the A2A SSE consumer of the same task correctly saw `final:true`; the two
  transports disagreed about what happened. Covered by a new end-to-end regression that starts a run
  on `/ag-ui/run`, cancels the underlying task via `POST /v1/tasks/{id}:cancel` while the run is
  still WORKING, and asserts the AG-UI stream's terminal frame is `RUN_ERROR` with message
  `"task canceled"`, not `"stream ended unexpectedly"`:
  `tests/test_rtb204_agui_cancel_terminal_event.py`. (`agent_sdk/routes/a2a.py`)
- RT-002 (redteam, high): `InMemoryTaskStore.context_messages()` (`agent_sdk/tasks/memory.py`)
  no longer silently disables A2A `contextId` continuation for a thread whose most recent task
  produced more than `MAX_CONTEXT_MESSAGES` (default 50) messages with no genuine turn boundary in
  the trailing cap-sized window. A single task that never finishes folds `2 * max_turns + 2`
  messages (a `toolUse`/`toolResult` pair per turn, plus the seed and the final
  `bridge_trailing_user` close), with its ONLY plain user-authored turn boundary at the seed
  message — so once `AGENT_SDK_MAX_TURNS` (default 20) rises past roughly 24, that per-task
  message count exceeds the default cap and `_turn_boundary_slice` found no boundary in the
  trailing window at all, returning `[]`: not a truncation, a total silent loss of every prior
  message, with no log line and no fallback. Numerically confirmed: `max_turns=24` carries all 50
  messages (fits under the cap); `max_turns=25` and above carried zero. `_turn_boundary_slice` now
  widens its search backward past the cap for the nearest earlier turn boundary when the trailing
  window has none, logging a `WARNING` (`agent_sdk.tasks.memory`) each time it does — this cannot
  reopen the unbounded cross-task growth `MAX_CONTEXT_MESSAGES` itself guards against (RT-007,
  0.5.x), since a single task's own message list is already finite, bounded by that task's
  `max_turns`. Still returns `[]`, now also logged, on the residual case where no turn boundary
  exists anywhere in the transcript. Documented the `MAX_CONTEXT_MESSAGES`/`max_turns` coupling in
  DESIGN.md §5.2 and docs/deployment.md — previously undocumented outside the module's own
  docstrings. New regression coverage at `max_turns=25` (and a `max_turns=24` control, confirming
  no fallback/warning fires under the cap): `tests/test_rt002_context_messages_max_turns_cliff.py`.
  (`agent_sdk/tasks/memory.py`, `agent_sdk/tasks/store.py`, `DESIGN.md`, `docs/deployment.md`)

## [0.7.0] — 2026-08-19

### 🔴 Breaking changes
- GH-144: `POST /v1/message:stream`'s `taskId` branch
  (`agent_sdk/routes/a2a.py::message_stream`) now returns 501 `-32004`
  (`UnsupportedOperation`) for a present-but-**terminal** task, instead of
  404 `-32001` (`TaskNotFound`) — matching `/v1/message:send`'s existing
  `_resume_or_error` behavior for the identical terminal-state condition
  (A2A-F1). Both codes already existed, unchanged, in
  `agent_sdk/models/errors.py` before this change; only the routing
  decision in `a2a.py` — which of the two pre-existing codes to return for
  this specific condition — changed.
  **RT-002 correction:** an earlier revision of this entry claimed the
  change satisfied both conditions of DESIGN.md §4.0's wire-shape
  conformance exemption and could therefore ship without a major bump. That
  claim does not survive verification: (a) *location* — the exemption is
  scoped to "a breaking change to a stable-core wire shape in `models/`",
  but `agent_sdk/models/errors.py` is untouched by this diff; only
  `agent_sdk/routes/a2a.py`'s code selection changed. (b) *spec-driven* —
  A2A v0.3.0's code→method table (`harness/reference/a2a-protocol-0_3_0.md`)
  maps neither `-32001` nor `-32004` to `message/send`/`message/stream`,
  and the spec's terminal-re-message rule requires only that the server
  "MUST return an error" — a requirement either code already satisfied.
  This repo's own Round 10 conformance audit (`REVIEWS.md`, finding "A2A
  (D2 Transports & Methods)") classifies the pre-fix split as "an internal
  cross-method inconsistency, not a hard-MUST breach (both codes are valid
  A2A error codes)." The exemption **does not apply** here. This is
  therefore a voluntary stable-core break — not one required by spec
  conformance — and per DESIGN.md:141 ("A voluntary breaking change to the
  stable core ... still requires a major bump; this exemption cannot be
  cited for those") it must ship under a major-equivalent version bump
  (`0.7.0`, per this repo's `0.MAJOR.MINOR` pre-1.0 convention — see
  `0.5.44` → `0.6.0` for GH-134/GH-135's genuine major bump), never under
  the `v0.6.1` patch this wave otherwise targets. The dedicated heading and
  Migration callout below are kept regardless — the change remains
  wire-visible and breaking with or without the exemption.
  - **Emit:** `message/stream` with `taskId` pointing at a task whose
    `status.state` is terminal (`completed`/`failed`/`canceled`) now
    responds `HTTP 501` `{"error": {"code": -32004, "message": "task is in
    a terminal state and cannot accept new messages"}}` — was `HTTP 404`
    `{"error": {"code": -32001, "message": "task not found"}}`. A
    genuinely unknown/foreign `taskId` is unaffected and still returns
    `HTTP 404` `-32001` (identity-scoped lookup; existence is never leaked
    per DESIGN.md:266).
  - **Parse:** this SDK is an A2A server only and never parses its own
    `message/stream` error responses, so there is no in-repo parse path
    affected. The impact lands entirely on external A2A clients — see
    Migration.
  - **Migration:** any A2A client that branches on `-32001`/404 to detect
    "task cannot be resumed" for `message/stream` must also handle
    `-32004`/501 for the terminal-task case (matching the handling such a
    client should already have for `message/send`, which has returned
    `-32004`/501 for this condition since `_resume_or_error` was
    introduced — only `message/stream` was inconsistent). Concretely: this
    same change required updating `harness/skills/acceptance/SKILL.md`
    (turn-continuation guidance) and rewriting `workspace/learning/LRN-103`
    in this repo's own harness/docs, which is the giveaway that the break
    is real and downstream-visible, not merely internal. `docs/protocols.md`
    and `DESIGN.md`'s `-32004` error-table row are updated to match.
  (`agent_sdk/routes/a2a.py`, `agent_sdk/tasks/store.py`,
  `agent_sdk/tasks/memory.py`, `docs/protocols.md`, `DESIGN.md`,
  `harness/skills/acceptance/SKILL.md`,
  `workspace/learning/LRN-103-a2a-multiturn-contextid-continuation.md`,
  `tests/test_gh144_terminal_resume_error_docs.py`,
  `tests/test_w017_gh51_multiturn.py`)

### 🟠 Security
- GH-143 (+ RT-001 redteam follow-up): `GET /mcp` (Streamable HTTP heartbeat
  stream) and `GET /mcp/sse` (legacy SSE) are now admitted against ONE
  shared, reject-based concurrency cap — global (`_MAX_GET_STREAMS = 500`)
  checked first, then per-identity (`_MAX_GET_STREAMS_PER_IDENTITY`, raised to
  `200` and made operator-overridable before release — see the RT-001 round 2
  entry below; it was `8` when this entry was first written) —
  enforced BEFORE the indefinite `StreamingResponse` is created on either
  route, and returning `429` (`Retry-After: 5`) once at capacity. Both
  routes hold an authenticated, indefinitely-held `text/event-stream` open
  on the same single-process connection pool (the server is
  single-process/single-worker by design), so capping only one was
  bypassable by calling the other. `GET /mcp/sse`'s prior admission control
  — a dedicated `_MAX_SSE_SESSIONS` evict-oldest loop — is retired: it only
  dropped the session-routing bookkeeping entry, never the live
  heartbeat/poll loop (the generator kept running, untracked, until the
  client itself disconnected), and it evicted regardless of owner, so one
  caller could make another tenant's still-open session unroutable
  (`POST /mcp/messages` → 404 "session not found" for the evicted tenant,
  while that tenant's connection stayed open). Both routes now release
  their slot on disconnect via a two-layer mechanism (a generator `finally`
  plus a `StreamingResponse` `BackgroundTask`) and a liveness-based prune
  keyed on the owning ASGI task's `.done()` state — never wall-clock TTL,
  which would risk reclaiming a still-open stream under load. (`agent_sdk/routes/mcp.py`,
  `agent_sdk/tasks/store.py`, `agent_sdk/tasks/memory.py`,
  `tests/test_gh143_mcp_get_stream_cap.py`, `tests/test_rt001_mcp_sse_stream_cap.py`,
  `tests/test_mcp_security_rt001_005.py`)
- RT-001/RT-002/RT-003 (round 4 fresh-lens, redteam follow-up on GH-143):
  the A2A admission cap ran in the wrong PLACE on `POST
  /v1/message:stream`'s dominant no-`taskId` path, and one SSE surface had
  no cap at all.
  - **Admission now precedes every durable state mutation.** `_open_stream`
    conflated the admission *decision* with the subscription *registration*
    into one call needing a `TaskRecord`; on the no-`taskId` path no record
    exists until `_create_task_record()` has already run
    `task_store.create()`, so the load-shed check ran AFTER a durable write
    to the LRU-bounded task store. Every 429-rejected request still
    inserted an orphan `TaskRecord` (no worker, permanently `submitted`),
    and `create()` → `_evict_over_capacity()` evicts oldest-first while
    `evict()` cancels the evicted record's worker and `sub.close()`s its
    subscribers — so shedding load severed **another tenant's** in-flight
    SSE stream with no `final: true` frame, exactly the harm this wave's
    reject-never-evict rule exists to prevent. Admission is now a separate
    `_admit(request, identity, task_id)` that takes no record, mutates
    nothing durable, and **claims** its slot in the same synchronous step as
    the checks (so a caller may create state afterwards without risking a
    second rejection). A shed `message:stream` is now a pure no-op.
  - **`POST /ag-ui/run` is now admission-capped** against the same shared
    budget as the A2A streams (wire-visible: it can now return `429` +
    `Retry-After: 5` with the bare `{"detail": ...}` shape that surface's
    other transport-level rejections already use, always *before*
    `RUN_STARTED`, so it is never a `RUN_ERROR` frame). It was the third
    authenticated, indefinitely-held `text/event-stream` on the same
    single-process connection pool — sharing the task store, worker pool and
    token budget — and had no cap, leaving the DoS GH-143 set out to close
    fully reachable by calling it instead. A source-level completeness gate
    now fails if any route returning `media_type="text/event-stream"` lacks
    an admission check.
  - **The 429 is now recorded on every spec surface** (DESIGN.md §5.5 and
    §6 — rate limiting is now documented as *three* layers, not two — plus
    `docs/protocols.md`'s A2A error table and MCP section, and both route
    module docstrings), including an explicit citation of the two-outcome
    `GET /mcp` rule (`text/event-stream` or 405) the 429 departs from and
    the Claude.ai *"Couldn't connect"* operational consequence recorded in
    `harness/reference/mcp-claude-platforms.md`.
  (`agent_sdk/routes/a2a.py`, `agent_sdk/routes/ag_ui.py`,
  `agent_sdk/routes/mcp.py`, `DESIGN.md`, `docs/protocols.md`,
  `tests/test_rt001_admission_before_mutation.py`)
- RT-001 (round 4, redteam follow-up on GH-143/GH-144): the same
  release-on-disconnect leak GH-143 closed on `GET /mcp`/`GET /mcp/sse` also
  applied to the A2A streaming surface — `POST /v1/message:stream`'s `taskId`
  resume branch and `POST /v1/tasks/{id}:subscribe` both subscribe to the
  task store EAGERLY, before their `StreamingResponse` exists, and relied
  solely on the SSE generator's `finally` to unsubscribe. A request task
  hard-cancelled at Starlette's `send(http.response.start)` checkpoint — the
  same unwind GH-143 identified — never reaches that `finally` and skipped
  the response's `BackgroundTask` too, leaking a `Subscription` onto
  `TaskRecord.subscriptions`, an unbounded list `store.publish` walks for
  every frame. Both routes now register `BackgroundTask(abort)` (`abort`
  calls `store.unsubscribe`) in addition to the generator's `finally`, and
  `InMemoryTaskStore.subscribe` reclaims any orphan whose owning ASGI task
  has finished before registering a new one, keyed on that task's `.done()`
  state — never wall-clock TTL, so a still-open stream is never reclaimed.
  New public **`Subscription.owner_task`** (`agent_sdk/tasks/store.py`) — the
  owning `asyncio.Task`, captured at `subscribe()` time, `None` when
  `subscribe()` ran outside a task — and new public **`TaskStore.reap_dead_subscriptions(record)`**,
  a concrete method on the `TaskStore` base class every `subscribe()`
  implementation must call (stated on the now-documented abstract
  `subscribe` contract) so a third-party `TaskStore` subclass gets the same
  reclaim behavior without re-deriving it. Also fixes a related
  thread-safety bug in both `release()` (`mcp.py`) and `abort()` (`a2a.py`):
  as plain `def` closures, Starlette's `BackgroundTask` dispatched them via
  `run_in_threadpool` (an AnyIO worker thread) while the event loop
  concurrently iterated the same containers (`_prune_get_streams`,
  `InMemoryTaskStore.publish`) — able to raise `RuntimeError: ... mutated
  during iteration` or silently skip a live SSE subscriber. Both are now
  `async def`, so Starlette awaits them in-loop instead; every caller
  (`message_stream`'s early-return path included) now `await`s them.
  (`agent_sdk/routes/a2a.py`, `agent_sdk/routes/mcp.py`,
  `agent_sdk/tasks/store.py`, `agent_sdk/tasks/memory.py`,
  `tests/test_rt001_stream_slot_release_on_hard_cancel.py`,
  `tests/test_rt001_release_runs_on_loop_thread.py`,
  `tests/test_rt003_task_store_reap_conformance.py`)
- RT-001 (round 2, redteam follow-up on GH-143): the per-identity `GET /mcp`
  cap this same wave introduced was keyed on `_identity_key()`
  (`f"{identity.kind}:{identity.subject}"`), but `Identity.subject` is an
  OAuth client_id (`auth/oauth_tokens.py`) or API-key id (`auth/api_keys.py`)
  — never an end user. Under this SDK's own documented org-wide OAuth client
  mode (`python -m agent_sdk provision-org-oauth-client`, `config.py`) or a
  shared API key, every caller in an organization collapses onto ONE
  identity key, so the old hardcoded `_MAX_GET_STREAMS_PER_IDENTITY = 8`
  capped an entire org — not one caller — at 8 concurrent MCP connectors;
  the 9th connector got 429 regardless of org size, with no override
  available. Default raised to `200`, and a new setting
  **`AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY`**
  (`settings.max_mcp_streams_per_identity`, `config.py`) lets an operator
  raise it further for a larger org — resolved via new
  `routes/mcp.py::_max_streams_per_identity()`, which also clamps any
  override to never exceed the process-wide `_MAX_GET_STREAMS` budget.
  (`agent_sdk/routes/mcp.py`, `agent_sdk/config.py`,
  `tests/test_rt001_mcp_org_wide_identity_cap.py`)
- RT-002 (redteam follow-up on GH-143): GH-143's admission cap covered
  `GET /mcp`/`GET /mcp/sse` only — `POST /v1/message:stream`'s `taskId`
  resume branch and `POST /v1/tasks/{id}:subscribe` remained authenticated,
  indefinitely-held `text/event-stream` responses on the SAME single-process
  connection pool with no concurrency accounting at all, so the DoS GH-143
  set out to close stayed reachable through the other transport. Worse,
  `tasks_resubscribe` could be invoked unboundedly against ONE task, each
  call appending a `Subscription` onto `record.subscriptions` — the exact
  "unbounded list `store.publish` walks for every frame" harm `_open_stream`'s
  own docstring already named. Both routes now admit through
  `routes/a2a.py::_admit()`
  against a new shared budget (`routes/a2a.py::_a2a_streams()`, mirroring
  `routes/mcp.py::_get_streams()`) in **three** layers, in this order:
  global (`_MAX_A2A_STREAMS = 500`, bounds total process load), then
  per-identity (`_MAX_A2A_STREAMS_PER_IDENTITY = 200`, overridable via the new
  **`AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY`** setting — see ✅ Features below
  — the layer that stops one authenticated tenant consuming the whole budget
  and locking every other tenant out), then a cap on concurrent subscribers to
  the SAME task (`_MAX_A2A_STREAMS_PER_TASK = 16`, which bounds the
  `record.subscriptions` growth `store.publish` walks per frame) wherever the
  request names an existing task. All three are enforced BEFORE
  `store.subscribe()`/the `StreamingResponse` is created — and, per the round-4
  entry above, before any durable state mutation on the request path —
  rejecting with `HTTPException(429,
  Retry-After: 5)` (never evicting, for the identical reason GH-143's `mcp.py`
  comment gives) which the existing `/v1/*` A2A error envelope
  (`app.py::_a2a_auth_envelope`) translates into the spec error shape. Also
  adds `429 -> -32000` to that envelope's status→code map (previously
  unmapped 429s, including the pre-existing identity rate limiter's, fell
  through to the misleading `-32603` Internal-error default).
  **RT-001 correction (round 7):** an earlier revision of this entry described
  only the global and per-task layers, omitting the per-identity one that
  DESIGN.md §5.5 and `docs/protocols.md` both document as the cross-tenant
  fairness layer. That omission mattered doubly: the per-task cap is vacuous on
  `message:stream`'s dominant no-`taskId` path (a fresh uuid per call always
  counts 0), so an entry naming only those two described a budget with no
  cross-tenant dimension at all on the SDK's busiest streaming route.
  (`agent_sdk/routes/a2a.py`, `agent_sdk/app.py`, `agent_sdk/config.py`,
  `agent_sdk/common/admission.py`, `DESIGN.md`, `docs/protocols.md`,
  `workspace/components/README.md`,
  `tests/test_rt002_a2a_stream_admission_cap.py`)

### ⚠️ Behavior changes
- RT-001 (round 5, fresh-lens redteam follow-up on GH-143/GH-144):
  `InMemoryTaskStore._evict_over_capacity()` (`agent_sdk/tasks/memory.py`) no
  longer evicts a task record that has live subscribers, even when the store
  is over `capacity`. Previously, LRU overflow eviction could pick ANY
  oldest record regardless of whether it had an open SSE stream — `evict()`
  cancels the worker and sentinel-closes every subscriber's queue, which
  `routes/a2a.py`'s `gen()` reads as an unannounced stop, never emitting a
  `final: true` `TaskStatusUpdateEvent`. Because eviction is driven by total
  store occupancy, the identity whose `create()` call overflowed the store
  was almost never the owner of the record that got evicted — any
  authenticated identity calling `POST /v1/message:send` (which has no
  admission cap) could silently sever another tenant's in-flight
  `message:stream`/`tasks:subscribe` connection. `publish()` now also
  refreshes the record's LRU position on every emitted frame (delegating to
  `touch()`), not just on create/get — previously a record streaming frames
  for an hour still sat at the LRU end and was the first eviction candidate.
  A dead (owner-task-finished) subscription is reaped before the live-check
  runs, so a leaked subscription can never pin a record forever.
  **RT-001 round 6 (pre-release `/sdk-test` Leg 3, ag-ui-advisor):** the round
  5 guard only covered the capacity-overflow eviction path. `get()`'s
  TTL/interrupt-deadline expiry check, and the periodic background
  `sweep()`, both called `evict()` unconditionally on the same expired
  record with no live-subscriber guard at all — and `get()`'s path is
  reachable from `find_interrupt()` (AG-UI's `_resume_target_task_id`
  resume lookup), so a resume attempt for one interrupt could walk every
  record and silently evict an unrelated, still-live-streamed task that
  simply hadn't been touched in `task_ttl`/`interrupt_ttl`. Both `get()` and
  `sweep()` now apply the identical reap-then-skip-if-still-subscribed guard
  `_evict_over_capacity` already had.
  - **Migration:** total occupancy in `InMemoryTaskStore` can now boundedly
    exceed `capacity` while records have live subscribers — bounded by the
    same route-layer admission caps (`_MAX_A2A_STREAMS`, `_MAX_GET_STREAMS`)
    that already limit concurrent streams, not unbounded. No action needed
    for typical deployments; a custom `TaskStore` subclass or a
    capacity-planning script that assumed strict `capacity`/TTL enforcement
    should account for this bounded overrun.
  (`agent_sdk/tasks/memory.py`, `DESIGN.md` §5.2,
  `tests/test_rt001_r6_expiry_never_severs_live_streams.py`)

### ✅ Features

RT-001 (round 7): the three stable-core additions below shipped in the
🟠 Security work above with no entry of their own. DESIGN.md §4.0 puts
`BaseAgentSettings` in the stable core under strict SemVer, so a new settable
field is a public-API addition that must be recorded as one — documenting the
behaviour in DESIGN.md does not discharge the SemVer accounting.
`tests/test_changelog_gh143_gh144_wire_changes.py` now fails if any
non-grandfathered `AGENT_SDK_*` alias in `agent_sdk/config.py` is absent from
this file.

- New setting **`AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY`**
  (`settings.max_a2a_streams_per_identity`, `agent_sdk/config.py`) — the
  operator override for the per-identity layer of the A2A/AG-UI stream
  admission budget (`POST /v1/message:stream`, `POST /v1/tasks/{id}:subscribe`,
  `POST /ag-ui/run`). Default `None` selects the SDK default
  `routes/a2a.py::_MAX_A2A_STREAMS_PER_IDENTITY = 200`; any override is clamped
  to the process-wide `_MAX_A2A_STREAMS = 500`, since a per-identity cap above
  the global budget is meaningless and would only mask misconfiguration.
  Validated `ge=1` at settings construction: `0` is the natural operator
  reading of "unlimited", but every call site guards with `count >= limit`, so
  a `0` would deny every stream for every identity silently — "unlimited" is
  expressed by leaving the variable unset. Sized in the low hundreds, and
  overridable at all, for the same documented reason as its MCP twin
  `AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY`: `Identity.subject` is a client_id
  or API-key id — a *registration*, never an end user — so org-wide OAuth
  client provisioning or a shared API key collapses an entire org onto one
  identity key. (`agent_sdk/config.py`, `agent_sdk/routes/a2a.py`,
  `tests/test_rt002_a2a_stream_admission_cap.py`)
- New module **`agent_sdk/common/admission.py`** (component **C-024**,
  `workspace/components/README.md`) — the single implementation of the stream
  admission bookkeeping every indefinitely-held `text/event-stream` route in
  this SDK shares: `StreamSlot`, `SlotTable`, `identity_key`, `slot_table`,
  `prune_finished`, `count_for_owner`, `count_for_task`,
  `resolve_per_identity_limit`. It replaces a byte-identical second copy that
  had been implemented once per transport in the same wave and had already
  drifted (different record arities) — which is how the next fix lands in one
  transport and not the other. The two *budgets* remain deliberately separate
  tables (`app.state.mcp_get_streams` vs `app.state.a2a_streams`): merging them
  would be a behaviour change, not a deduplication.
  (`agent_sdk/common/admission.py`, `agent_sdk/routes/a2a.py`,
  `agent_sdk/routes/mcp.py`, `agent_sdk/routes/ag_ui.py`,
  `workspace/components/README.md`)
- New public **`TaskStore.new_subscription(record, maxsize)`**
  (`agent_sdk/tasks/store.py`) — a concrete method on the `TaskStore` base
  class that performs the whole `subscribe()` body (reap dead subscriptions →
  construct → stamp `Subscription.owner_task` → append), so every
  implementation delegates to it rather than reproducing it. RT-002 (round 7):
  the earlier `reap_dead_subscriptions` hoist stated only the *consume* half of
  that contract. `reap_dead_subscriptions` keeps every `owner_task is None`
  entry by design and `Subscription.__init__` defaults it to `None`, so a
  third-party `TaskStore` (`Agent(task_store=...)` is a documented extension
  point) that faithfully called the reap but never stamped `owner_task` had a
  permanently **vacuous** backstop: `record.subscriptions` grew without bound
  exactly as before, and such a subscription additionally pinned its record
  against `InMemoryTaskStore._evict_over_capacity`'s live-subscriber skip for
  the process lifetime. `InMemoryTaskStore.subscribe` is now a delegation, the
  abstract `subscribe` docstring states both halves, and
  `tests/test_rt003_task_store_reap_conformance.py` asserts both against every
  factory in `_STORE_FACTORIES` — including end-to-end, on a subscription the
  suite never touches, so a stamp-less implementation fails instead of passing
  vacuously as it did before.
  (`agent_sdk/tasks/store.py`, `agent_sdk/tasks/memory.py`,
  `tests/test_rt003_task_store_reap_conformance.py`)

### 📋 Release process (RT-003, gh-review triage correction)
- The two issues fixed under 🔴 Breaking changes and the first two 🟠
  Security entries above were resolved in `workspace/todos/active/w040-gh-issues.md`
  (now archived), whose own RT-002 note already concluded the terminal-task
  error-code fix is a voluntary stable-core break requiring this
  major-equivalent version bump — never the `v0.6.1` patch the todo file
  originally targeted. `pyproject.toml` was left unbumped after that
  conclusion landed, leaving the tree self-contradictory: a version bump the
  CHANGELOG itself demanded, an unbumped `pyproject.toml`, both todo
  checkboxes still unticked, and `REVIEWS.md`'s Round 10 audit still
  recording both findings as deferred to "the next gh-review triage cycle"
  — this cycle. This release closes that gap: `pyproject.toml` bumped to
  `0.7.0`, both todo checkboxes ticked and the file archived, and
  `REVIEWS.md`'s two Round 10 deferred rows carry a resolution marker
  naming this version.

## [0.6.0] — 2026-08-18

### 🔴 Breaking changes
- GH-134 (corrects GH-52): `ToolSet.tool()`'s `openWorldHint` MCP annotation
  seeding (`agent_sdk/agent/registry.py`) moved from the outer `tool()`
  scope — where it was force-set `False` for `tier == 1 or read_only`,
  before `adapter_params` was known — into `decorator()`, evaluated after
  the function signature is scanned. GH-52 (w016) correctly seeded
  `openWorldHint=False` for `read_only=True` tools but overgeneralized by
  also tying it to `tier == 1`, misclassifying every tier-1
  `SourceAdapter`-backed tool (a tool that DOES talk to an external system)
  as closed-world by default. `openWorldHint` is now `True` iff the tool
  has at least one `SourceAdapter`-backed keyword-only parameter, `False`
  otherwise — independent of tier — while `read_only`'s
  `readOnlyHint`/`destructiveHint` seeding and an explicit `annotations=`
  override are unchanged. Filed under `🔴 Breaking changes`, not
  `⚠️ Behavior changes` (RT-007) — this is a stable-core MCP wire-shape
  break (`ToolDecl.annotations`, defined in `agent_sdk/agent/registry.py`
  and serialized ad hoc into the `tools/list` response in
  `agent_sdk/routes/mcp.py`; there is no `models/` type for MCP tool
  declarations at all). DESIGN.md §4.0's wire-shape conformance exemption
  requires **both** that the changed shape live in `models/` **and** that
  the change be spec-conformance-driven (RT-004; the same two-condition
  test REVIEWS.md Round 8 applied to GH-135). This change satisfies only
  the second condition — its sole purpose is correcting this SDK's
  `tools/list` output to conform to MCP's `openWorldHint` semantics (a
  tier-1 SourceAdapter-backed tool talks to an external system and must
  not report closed-world) rather than a voluntary redesign — but fails
  the first, since neither `ToolDecl` nor the wire dict it feeds lives in
  `models/`. Per REVIEWS.md Round 9, the exemption **does not apply and
  cannot be cited** for it, for the same reason (failing one of the two
  required conditions) that Round 8 already disqualified GH-135. **This
  heading, the emit/parse split and the Migration callout below are still
  required regardless** — they document the wire break itself, not an
  exemption claim. **Version:** per REVIEWS.md Round 9, this entry
  requires this batch to ship as `0.6.0`, not the next `0.5.x` patch, when
  cut — same as GH-135 below.
  - **Emit:** every tier-1 SourceAdapter-backed tool's MCP `tools/list`
    `annotations.openWorldHint` flips `False`→`True` on upgrade, changing
    how MCP consent UIs classify/badge these tools (open- vs. closed-world).
    Separately (RT-015), because `openWorldHint` is now seeded
    unconditionally, `ToolDecl.annotations` (and the wire `tools/list`
    `annotations` field) is never `None` again — including for a tier-2,
    non-`read_only` tool with no `SourceAdapter`-backed parameter, which
    previously fell through to `None` (the old seeding only ran for
    `tier == 1 or read_only`) and now gets `{"openWorldHint": False}`.
  - **Parse:** this SDK is an MCP *server* only and never parses
    `annotations`/`openWorldHint` on any inbound tool declaration, so there
    is no in-repo parse path affected by this change. The parse-side impact
    lands entirely on external MCP clients reading this agent's `tools/list`
    response — see Migration.
  - **Migration:** any MCP client or consent UI that (a) branches on
    `annotations is None` vs. a populated dict, or (b) classifies/badges a
    tool open- vs. closed-world from `openWorldHint`, must re-check that
    logic against both changes above before upgrading. No code change is
    required in this SDK itself — this is a receiver-side migration only.
  (`agent_sdk/agent/registry.py`, `tests/test_mcp_conformance_w9.py`)
- GH-135: `ToolEntry.invoke()`/`invoke_gen()` (`agent_sdk/agent/registry.py`)
  now raise a new `ToolInputValidationError` — wrapping the original
  `pydantic.ValidationError` as `.validation_error` — when
  `input_model.model_validate(arguments)` rejects the caller-supplied
  tool_call arguments, instead of letting the raw `pydantic.ValidationError`
  propagate. `ToolInputValidationError` does **not** subclass
  `pydantic.ValidationError` (it is a plain `Exception`), so this is a
  genuine breaking change to `ToolSet`/`@tool` dispatch, stable core per
  DESIGN.md §4.0, that is neither a `models/` wire shape nor required by
  any external protocol spec: it fails **both** conditions of the §4.0
  exemption, so the exemption **does not apply and cannot be cited** for
  it (RT-007) — unlike GH-134 above, which is spec-conformance-driven but
  (per RT-004 / REVIEWS.md Round 9) still fails the `models/` condition,
  landing in the same not-exemption-eligible outcome by a different route.
  **Version:** per the explicit sign-off recorded in REVIEWS.md Round 8,
  this entry requires this batch to ship as `0.6.0`, not the next `0.5.x`
  patch, when cut.
  - **Migration:** any dispatch surface — inside or outside this SDK — that
    wraps a call to `ToolEntry.invoke()` / `invoke_gen()` / `invoke_any()`
    in `except pydantic.ValidationError` must change that clause to
    `except ToolInputValidationError` (`from agent_sdk import
    ToolInputValidationError` — exported from the stable core surface per
    RT-013; do not reach into `agent_sdk.agent.registry`), or the exception
    now falls through uncaught. This SDK's own **four** dispatch sites
    (`agent/loop.py`'s sync/streaming/resume tool-call branches,
    `routes/mcp.py::_handle_tools_call`, `routes/admin.py::try_tool`, and
    `contrib/commitments/executor.py::_fire`) are all updated.
  - **Migration (RT-006, persisted data):** the commitments executor records a
    failure reason in the commitments DB. Its generic `except Exception`
    branch persists `type(exc).__name__`, so introducing
    `ToolInputValidationError` between the raise site and that catch-all would
    have silently changed the stored string from `"ValidationError"` to
    `"ToolInputValidationError"` for every existing deployment. `_fire()` now
    catches `ToolInputValidationError` explicitly and persists the stable,
    explicit reason `"invalid_tool_input"` (exported as
    `INVALID_TOOL_INPUT_REASON`). **Any query, dashboard or alert matching
    `last_error == "ValidationError"` on the commitments table must be updated
    to `"invalid_tool_input"`** for the caller-input case; a ValidationError
    raised by the tool BODY still records `"ValidationError"`, and the two are
    now distinguishable — which they were not before.
    (`agent_sdk/contrib/commitments/executor.py`,
    `tests/test_contrib_commitments.py`)
  - The discriminator exists so a `ValidationError` raised by the tool BODY
    (e.g. constructing a `ContentModel` with bad data downstream) is no
    longer misreported to the model as bad input-argument coercion — which
    previously drove an unresolvable retry loop, since the model has no way
    to fix arguments that were never the problem.
  (`agent_sdk/agent/registry.py`,
  `agent_sdk/agent/loop.py`, `agent_sdk/routes/mcp.py`,
  `agent_sdk/routes/admin.py`, `agent_sdk/__init__.py`,
  `tests/test_gh135_tool_body_validation_error.py`,
  `tests/test_rt013_tool_input_validation_error_export.py`)

### 🟠 Security
- RT-003 (SI-2, redteam on GH-135): `ToolInputValidationError.__init__`
  (`agent_sdk/agent/registry.py`) no longer sets its own exception message to
  `str(validation_error)`. Pydantic renders a `ValidationError` with each
  error's `msg`/`input` baked in — e.g. a custom `@field_validator` that
  raises `ValueError(f"bad token {v!r}")` puts the raw rejected value
  straight into that rendering — so wrapping it verbatim armed a leak for
  any downstream `except Exception as e: str(e)` handler, exactly what
  GH-135's SI-2 acceptance criteria required stay unreachable via a bare
  `str(exc)`. The message is now a fixed, non-interpolating
  `"tool {tool_name!r} input validation failed"`; the raw
  `pydantic.ValidationError` remains reachable only via `.validation_error`,
  which `safe_validation_message()` (`agent_sdk/agent/loop.py`) already
  consumes to build the loc+type-only, redacted diagnostic actually surfaced
  to callers. (`agent_sdk/agent/registry.py`,
  `tests/test_rt003_tool_input_validation_error_message.py`)
- GH-129: boot now emits a `WARNING` when `DEV_MODE=True` and
  `AZURE_STORAGE_CONNECTION_STRING` is set (`agent_sdk/app.py`), mirroring
  the existing dev-mode-mismatch warning that previously covered only the
  sibling `azure_storage_account_name` path. Root cause confirmed against a
  real production incident: roughly 30 days of local/test runs with
  `DEV_MODE=True` pointed at a live connection string minted 18,969 admin
  API keys into the production credential store, silently, with no
  boot-time signal. SI-2: the warning names the setting only — the
  connection string value itself never appears in the emitted log record.
  RT-008: the SI-2 regression test asserting that absence lives in a
  guard-free module so it runs in the default `pytest -q` suite — its
  original home, `tests/test_app_azure_wire.py`, is skipped wholesale when
  `npx` is missing, which silently disabled the SI-2 gate on any runner
  without Node. (`agent_sdk/app.py`,
  `tests/test_gh129_dev_mode_connection_string_warning.py`,
  `tests/test_app_azure_wire.py`)
- GH-130: `ContentModel.to_plain_text()` implementations that join untrusted
  field values into a delimited text render now pass each value through a new
  `_sanitize_cell()` helper (`agent_sdk/models/content_types.py`) before
  joining. An untrusted `|` — or its visual confusables U+2502 (`│`) / U+FF5C
  (`｜`) — previously fabricated an extra column in a `" | ".join(...)`
  render, and an embedded line break previously fabricated an extra
  row/entry in a `"\n".join(...)` render, silently misrepresenting structured
  data to any reader of the plain-text fallback (including tool-result
  folding). Documented as a standing delimiter-safety contract on
  `ContentModel.to_plain_text`, binding for future `ContentModel` subclasses.
  - **Scope (RT-007 correction):** the sanitiser is applied across **all 14
    Standard Profile renderers**, not only `ComparisonTable`/`EntityList` as
    an earlier revision of this entry stated — `KpiCard`, `TimeSeriesChart`,
    `ComparisonTable`, `BarChart`, `EntityList`, `MarketBriefing`,
    `WaterfallChart`, `MultiCategoryChart`, `FundPerformance`, `EmailList`,
    `CalendarEvents`, `UserProfile`, `UserList`, `DocumentList` — and covers
    each type's own `title`/`entity_type`/`as_of` fields (RT-006), which are
    plain `str` and carry the same risk as any other cell.
  - **Neutralised set (RT-007 correction):** not just CR/LF but the full
    `str.splitlines()` break set — CR, LF, VT, FF, FS/GS/RS, NEL,
    U+2028/U+2029 — plus all remaining C0, DEL and C1 controls, each mapped
    to a space. C1 is not optional: NEL (`\x85`) is treated as a line break
    by many log/terminal consumers and CSI (`\x9b`) is a single-byte ANSI
    escape introducer.
- RT-001 (redteam on GH-130): `MarketBriefing.prose` and
  `TextSection.content` are **excluded** from `_sanitize_cell` and routed
  through a new `safe_block_text()` / `_sanitize_block()` pair
  (`agent_sdk/common/redact.py`, `agent_sdk/models/content_types.py`) that
  preserves `\n`, `\t` and `|` while still neutralising ANSI/terminal escape
  introducers, NEL, U+2028/U+2029 and the rest of C0/DEL/C1. `MarketBriefing`
  is the SDK's sole prose-exception type (DESIGN §4.3): its `to_markdown()`
  output **is** the A2A/AG-UI DataPart value (`a2ui/translator.py`) and the
  MCP `structuredContent {"markdown": ...}` payload (`routes/mcp.py`), so
  running those two fields through a single-line cell sanitiser collapsed
  every newline to a space and rewrote `|` to `/` — destroying headings,
  lists, paragraphs and markdown tables in the one payload designed to carry
  them. No delimiter is fabricated for these fields: `to_markdown()` joins
  *sections*, and nothing downstream re-parses the rendered text
  positionally. Choose the helper by the **field's** contract, not by the
  enclosing method's name. **Behavior-visible:** the residual wire-payload
  impact of this correction — every field `to_markdown()` interpolates is now
  sanitised where none was before — is recorded under `⚠️ Behavior changes`
  below, not here, matching the GH-134/GH-135 heading discipline (RT-007).
  (`agent_sdk/common/redact.py`,
  `agent_sdk/models/content_types.py`, `tests/test_content_types.py`)
- GH-138: `AGENT_SDK_OAUTH_ONE_TIME_CONSENT` (GH-136) is **per-registration**
  (per `client_id`), not automatically org-wide — DCR mints a fresh,
  unconsented `client_id` on every registration, so a returning client skips
  repeat approval but a brand-new user's own registration still hits the
  admin-key gate. The `config.py` and `routes/oauth.py` docstrings previously
  overclaimed "org-wide access... that is the point," which could lead an
  operator to enable the flag expecting it alone to unblock every org member,
  then hit the admin gate again on the second user with no documented reason
  why. Both docstrings now describe the two real scopes (per-registration vs.
  genuine org-wide) and point at the new CLI below for the latter.
  - New: `python -m agent_sdk provision-org-oauth-client [--public-url <url>]
    [--yes]` formalizes the "pin a static `client_id`" workaround as a guided
    setup step — mints and pre-approves ONE client offline (the CLI's own
    credential-store access is the trust boundary), prompts for explicit
    confirmation before minting a client every org member will share (skippable
    with `--yes`), validates the `redirect_uri` against the same
    `_valid_redirect_uri` check the authorize route uses, and prints the
    pin-in instructions for the connector platform.
  (`agent_sdk/config.py`, `agent_sdk/routes/oauth.py`, `agent_sdk/__main__.py`,
  `tests/test_provision_org_oauth_client.py`)

### ⚠️ Behavior changes
- GH-130 / RT-001: `MarketBriefing.to_markdown()`'s output — the A2A/AG-UI
  DataPart value (`agent_sdk/a2ui/translator.py`) and the MCP
  `structuredContent {"markdown": ...}` payload (`agent_sdk/routes/mcp.py`) —
  is no longer a byte-for-byte passthrough of the model's field values.
  Before this batch, `to_markdown()` interpolated `title`, `as_of`, every KPI
  `title`/`value`/`unit`, chart/table section titles, `prose`, and
  `TextSection.content` with **zero** sanitisation. Now:
  - `title`, `as_of`, KPI fields, and chart/table titles route through
    `_sanitize_cell()`: any `str.splitlines()` break char (CR, LF, VT, FF,
    FS/GS/RS, NEL, U+2028/U+2029) plus the remaining C0/DEL/C1 controls
    collapse to a space, and `|` plus its confusables (U+2502, U+FF5C)
    rewrite to `/`.
  - `prose` and `TextSection.content` route through `_sanitize_block()`
    (`safe_block_text()`) instead: `\n`, `\t` and `|` are preserved as
    markdown structure and CR/CRLF normalise to `\n`, but ANSI/terminal
    escape introducers (ESC, CSI), NEL, U+2028/U+2029 and the rest of
    C0/DEL/C1 still collapse to a space.
  - **Migration:** any consumer of this wire payload that depended on
    receiving `MarketBriefing`/section field values byte-for-byte — e.g. a
    round-trip checksum, or a downstream renderer that itself relied on raw
    control/escape bytes surviving inside `prose`/`TextSection.content`/
    titles — will now observe those bytes replaced. No action is needed for
    the ordinary markdown-rendering path: headings, lists, paragraphs and
    tables inside `prose`/`TextSection.content` are unaffected, since `\n`,
    `\t` and `|` are preserved exactly (see the multiline-prose regression
    tests below).
  (`agent_sdk/models/content_types.py`, `agent_sdk/common/redact.py`,
  `tests/test_content_types.py`)
- RT-010/RT-011 (redteam on GH-139): `BedrockModelClient.converse()`
  (`agent_sdk/agent/bedrock.py`) now classifies three
  `botocore.exceptions.ClientError` codes — `ThrottlingException`,
  `TooManyRequestsException`, `ServiceQuotaExceededException` — as
  `ErrorCategory.RATE_LIMITED` instead of falling through to the generic
  `ErrorCategory.UPSTREAM` catch-all, mirroring `OpenAIModelClient`'s
  existing `RateLimitError` clause (GH-94). This is wire-visible for every
  A2A/AG-UI/MCP consumer of a Bedrock-backed agent:
  `agent_sdk/common/wire_errors.py` maps `RATE_LIMITED` → HTTP `429` and
  `UPSTREAM` → HTTP `502`, so both the HTTP status and
  `AgentError.public()["category"]` (`"upstream"` → `"rate_limited"`) change
  for these three codes on upgrade. No other `ClientError` code is affected
  — every other code still maps to `UPSTREAM`/`502` exactly as before (see
  `test_client_error_non_rate_limit_code_stays_upstream`).
  - **Migration:** any caller that branched on Bedrock's `502`/`upstream`
    response to detect throttling (e.g. a custom retry loop reading the wire
    error `category`) must also handle `429`/`rate_limited` for these three
    codes after upgrading.
  - Separately, `_boto_client()`'s bearer-auth path (RT-011) now pre-seeds
    dummy static credentials directly on the botocore session
    (`bcore_session.set_credentials(...)`) before client construction,
    purely to short-circuit `Session.create_client()`'s unconditional
    `get_credentials()` call — bearer auth signs exclusively through the
    registered `token_provider` and never reads these dummy values. The
    practical effect is also behavior-visible: the bearer-token path no
    longer consults the host's ambient AWS profile chain at all
    (`~/.aws/config`, `AWS_PROFILE`, SSO/login sessions,
    `credential_process`) during client construction — previously an
    interfering ambient profile (e.g. one requiring `botocore[crt]`) could
    raise an unrelated vendor exception before the bearer signer was ever
    consulted. A deployment that relied on ambient-profile side effects
    running during bearer-token client construction will no longer see
    them.
  (`agent_sdk/agent/bedrock.py`, `tests/test_bedrock_error_boundary.py`,
  `tests/test_bedrock_credential_store.py`)

### 🔧 Fixes
- RT-008 (redteam on GH-134): `ToolSet.tool()` now logs a `WARNING` at
  registration time for a tier-2 tool with no `SourceAdapter`-backed
  parameter and no explicit `annotations={"openWorldHint": ...}` override
  (`agent_sdk/agent/registry.py`). The `bool(adapter_params)` derivation
  itself is unchanged and correct — see the docstring at its call site and
  `workspace/learning/LRN-043-mcp-tier1-tools-openworldhint-missing.md` for
  why it is a complete claim, not a heuristic, under the SDK's
  dependency-injection contract — but a tier-2 *composite* tool is the
  shape most likely to reach an external system by a route other than a
  declared adapter parameter (a nested call into another tool's function, a
  contrib source that doesn't itself follow the `SourceAdapter` contract),
  so an author relying on that route now gets a boot-time nudge toward the
  explicit override instead of a silently closed-world annotation.
  `docs/tools.md` gained a short "MCP annotations" section documenting the
  same contract. (`agent_sdk/agent/registry.py`, `docs/tools.md`,
  `tests/test_mcp_conformance_w9.py`)
- GH-139: `BedrockModelClient._boto_client()`'s bearer-auth path now sets
  `signature_version="bearer"` explicitly via `botocore.client.Config`
  (`agent_sdk/agent/bedrock.py`). botocore's own gate for preferring bearer
  auth (`_should_prefer_bearer_auth`) reads the real process `os.environ`,
  not this client's isolated per-instance credential dict, so it never
  fired here — resolution silently fell through to SigV4 with no IAM
  credentials configured, failing at signing time with
  `NoCredentialsError` even though `bearer_token`/`token_provider` were
  correctly wired. Setting `signature_version` explicitly resolves to
  `'bearer'` directly, independent of that environment-based gate.
  - RT-005 (redteam on RT-013): the accompanying "did it really resolve to
    bearer?" guard now probes `botocore.auth.AUTH_TYPE_MAPS` — the registry
    `RequestSigner.get_auth_instance()` itself consults, raising
    `UnknownSignatureVersionError` on a miss — instead of reading back
    `built_client.meta.config.signature_version`. That read-back returned the
    exact value set two lines earlier: verified against botocore 1.43.32,
    `Config(signature_version='totally-bogus-scheme')` is echoed back verbatim
    and no signer resolution happens at construction time, so the guard could
    never fire in production while its test — which fabricated the impossible
    state on a `MagicMock` — stayed green. The probe now runs at the same
    point as the botocore>=1.39 floor check and is exercised against the real
    module.
  - RT-010/RT-011's wire-visible consequences of this same batch — the
    `ClientError` throttling-code → `RATE_LIMITED`/`429` reclassification and
    the bearer path's ambient-AWS-profile decoupling — are recorded under
    `⚠️ Behavior changes` above, not here, matching the GH-134/GH-135 heading
    discipline (RT-007).
  (`agent_sdk/agent/bedrock.py`, `tests/test_bedrock_credential_store.py`)
- GH-131: `wave-cycle.js`'s fallback for a missing `args.today` called
  `new Date()`, but the workflow sandbox bans the `Date` global outright —
  and the fallback fired whenever `args` arrived JSON-encoded as a string
  (reading `.today` off a string is always `undefined`), producing a
  `Date`-related crash with zero agents spawned instead of an error naming
  the actual missing argument. Args are now normalized first (JSON-parsed
  if string-encoded; a missing/falsy `args` becomes `{}`), then the
  workflow fails fast naming whichever of `waveFile`/`today` is absent —
  never falling back to `Date`. (`.claude/workflows/wave-cycle.js`,
  `harness/workflows/wave-cycle.js`, `tests/test_workflows.py`,
  `tests/test_gh131_wave_cycle_args_normalization.py`)
- GH-132: `wave-cycle.js`'s unit/phase redteam loops now gate exit only on
  `critical`/`high` findings (`blockingFindings()`) — previously any
  finding, including routine `low`-severity nits, counted toward the
  loop's exit condition, so an adversarial reviewer's low-severity nit
  alone was enough to force the round cap (5 unit / 8 phase) on
  effectively every run. `medium`/`low` findings are still surfaced
  (recorded once to a deferred note when the loop exits clean on blocking
  severity) but no longer keep the loop spinning. Also adds: batching the
  fix fan-out into one agent per round covering every file, unless
  blocking findings span more than `FIX_BATCH_FILE_THRESHOLD` (6) files;
  a `MAX_LRN_PER_WAVE` (20) cap on codified LRN files per wave; and a hard
  `AGENT_CALL_BUDGET` backstop — a flat 150-call floor for the handful of
  calls before the wave file is parsed, recomputed once `wave.groups.length`
  is known as `Math.max(150, 45 * wave.groups.length + 80)` so the ceiling
  scales with the wave's own shape, overridable via `args.agentBudget` for a
  wave whose honest cost exceeds even that — every dispatched agent call is
  now counted, and exceeding the budget stops the wave loudly (throws)
  instead of continuing to spend agent calls silently.
  - RT-009: the `medium`/`low` deferred note is no longer written only on the
    clean loop-exit branch. Every round accumulates its non-blocking findings
    into a loop-scoped store via a new `accumulateNonBlocking()` helper
    (deduped by the same `file + description` key `sigs()` uses), and the note
    is written **once, after the loop, from one place** — so the null-gate,
    findings-mismatch, round-budget-exhausted and tests-red exits all record
    their findings too, and a finding that resurfaces across rounds appears
    once rather than once per round.
  - RT-002: that RT-009 fix originally landed in the `wave-cycle.js` mirrors
    only. `sdk-wave.js` — the runner `.claude/skills/wave/SKILL.md` launches
    for SDK waves — kept the clean-exit-only write and had no accumulator at
    all, silently discarding every medium/low finding on all other exit paths.
    It is now ported there, and the RT-009 gates in `tests/test_workflows.py`
    are parametrized over **every** runner instead of the `wave-cycle.js`
    runtime copy alone. The one gate that did span `sdk-wave.js` asserted only
    that the literal `-medium-low.md` appeared somewhere in the loop section —
    true even when the write sits inside the clean-exit branch — so it passed
    vacuously; it is replaced with a structural (brace-depth) check that the
    write is *not* nested inside `if (blocking.length === 0)`.
  (`.claude/workflows/wave-cycle.js`, `harness/workflows/wave-cycle.js`,
  `.claude/workflows/sdk-wave.js`, `tests/test_workflows.py`)

### ✅ Features
- RT-002 (GH-130 follow-up): new public **`safe_cell_text`** in the C-007
  redaction family (`agent_sdk/common/redact.py`), re-exported from the
  package root (`agent_sdk.safe_cell_text`, `__all__`) and therefore stable
  core under strict SemVer (DESIGN.md §4.0). It is the helper that actually
  discharges the GH-130 delimiter-safety contract for a **delimited
  single-line render**: `safe_error_text(value, max_len=None)` composed with
  the full separator alphabet (`|`/`│`/`｜`, `<`, `>`, `(`, `)`, `[`, `]`,
  `=` neutralised everywhere; `:`, `,`, `@`, en/em dash and `→` neutralised
  only where they could form the template's spaced joiner, so emails and ISO
  timestamps survive intact).
  Previously this logic existed only as the module-private
  `agent_sdk/models/content_types.py::_sanitize_cell`, while the contract it
  implements was declared mandatory for third-party domain cards in three
  places — so downstream code could comply only by hand-rebuilding the
  alphabet per card module, which `docs/content-types.md` explicitly
  instructed. `_sanitize_cell` is now a thin alias for the public helper; no
  render output changes. **`safe_error_text` is not a substitute** — it
  performs no separator neutralisation at all, so any domain card following
  the old §4.0 wording literally was still exposed to the identity-fabrication
  attacks GH-130 closed. `ContentModel`'s contract docstring, DESIGN.md §4.0
  and `docs/content-types.md` (including its canonical `ClimateRiskReport`
  example, which previously demonstrated the per-renderer opt-in the same
  document forbids 70 lines later) all now name `safe_cell_text`. Registered
  as C-018 in `workspace/components/README.md`.
- GH-133: `OpenAIModelClient.__init__` (`agent_sdk/agent/openai_client.py`)
  accepts new optional `max_retries: int | None` and `timeout: float | None`
  parameters, forwarded verbatim to the underlying
  `AsyncOpenAI`/`AsyncAzureOpenAI` constructor when set. Left unset (the
  default), the openai SDK's own defaults apply and behavior is unchanged.
  Documents a retry asymmetry: `SourceAdapter._request()` retries once on a
  429/503 response, but `OpenAIModelClient` has no retry-once policy of its
  own — `max_retries`/`timeout` are its only retry/timeout control surface,
  delegated entirely to the openai SDK's own retry/backoff. Reachable via two
  new `BaseAgentSettings` fields (`agent_sdk/config.py`):
  `openai_max_retries` (env `AGENT_SDK_OPENAI_MAX_RETRIES`, int) and
  `openai_timeout` (env `AGENT_SDK_OPENAI_TIMEOUT`, float) — both
  `AGENT_SDK_`-prefixed per DESIGN.md §4.0 (RT-005: an earlier bare-name
  draft, `OPENAI_MAX_RETRIES`/`OPENAI_TIMEOUT`, was caught before release and
  renamed). `Agent._build_model_client` (`agent_sdk/app.py`) forwards both
  through to `OpenAIModelClient`; unset (the default) omits the kwargs
  entirely rather than passing explicit `None`.
  (`agent_sdk/agent/openai_client.py`, `agent_sdk/config.py`, `agent_sdk/app.py`,
  `tests/test_gh133_openai_retry_timeout.py`,
  `tests/test_rt009_openai_max_retries_timeout_seam.py`)
- GH-136: new opt-in `oauth_one_time_consent`
  (`AGENT_SDK_OAUTH_ONE_TIME_CONSENT`, default `False`) setting. When enabled,
  a DCR client an admin has **already** approved re-authorizes without the
  consent page on subsequent visits — the operator consents once, and that
  same registration's users connect without needing an admin API key for
  every visit. Previously every authorization required an admin key, and that
  key also grants `/admin/api/credentials` — so org-wide connector rollout had
  no safe path other than distributing the credential-store key itself. Reads
  back the `consented` flag that already existed on the client record (set by
  the POST approval path, previously read only by the LRU eviction guard) from
  `GET /oauth/authorize`. Default `False` means no existing deployment changes
  behavior on upgrade. **Scope note (GH-138, below):** this is per-registration
  consent, not automatically org-wide — see the Security entry above for the
  distinction and the CLI path for genuine org-wide sharing.
  (`agent_sdk/app.py`, `agent_sdk/auth/middleware.py`, `agent_sdk/config.py`,
  `agent_sdk/routes/oauth.py`, `tests/test_oauth_one_time_consent.py`)
- `/setup`'s Phase 0 "Client auth model" interview now asks the per-user vs.
  per-org OAuth consent scope question whenever OAuth is selected — GH-136's
  one-time-consent feature had no discoverability path, so a new agent
  developer would only learn the distinction existed after hitting the exact
  confusion GH-138 documents (a second org member blocked after the first was
  approved). Phase 3 now writes `AGENT_SDK_OAUTH_ONE_TIME_CONSENT=true` to
  `.env` for either scope choice, and the Day-2 operations list surfaces
  `provision-org-oauth-client` for the per-org follow-up against a real
  `PUBLIC_URL`. Also closes a previously-unguarded `harness/` ↔ `template/`
  drift on this skill file (uv vs. pip install instructions, a missing
  retry-config interview step), with a new sync-guard test in the same
  `xfail(strict)` pattern as the existing workflow-file guards.
  (`harness/skills/setup/SKILL.md`, `template/.claude/skills/setup/SKILL.md`,
  `tests/test_workflow_sync.py`)

## [0.5.44] — 2026-07-24

### 🔴 Breaking changes
- **`DataPart.data` narrows from `dict[str, Any] | list[Any]` to `dict[str, Any]`**
  (`agent_sdk/models/a2a.py`) — part of the GH-128 fix for the non-conformant bare-array A2UI
  wire shape, detailed in full under "Protocol surface changes" below. Both directions change:
  outbound, every A2A `DataPart` this SDK emits for A2UI now wraps the message array as
  `{"messages": [...]}` instead of delivering it bare; inbound, a `DataPart` whose `data` is a
  bare array now fails Pydantic validation (`-32602`, Invalid Params) instead of being accepted.
  **Migration:** any A2A client reading A2UI delivery must change from `part.data` to
  `part.data.messages`. RT-005 (redteam, low, versioning discipline): flagged that shipping a
  breaking wire-shape change under a same-minor patch bump (0.5.43 → 0.5.44, not 0.6.0) could
  surprise a consumer pinning `~=0.5.43`. Resolved by keeping the version at 0.5.44 rather
  than bumping to 0.6.0 — consistent with this project's established convention of surfacing
  breaking changes via an explicit `🔴 Breaking changes` section with a Migration callout rather
  than reserving them for a minor/major bump (precedent: 0.5.40's `TaskStore.interrupt_ttl_remaining`
  breaking change, also shipped under a same-minor patch bump, see below). This section is that
  callout, given its own top-level heading — matching 0.5.40's placement, and promoted out from
  inside "Protocol surface changes" where the fuller writeup still lives — precisely so a reader
  scanning only `Breaking changes` headers across releases does not miss it. Redteam follow-up
  (low, versioning discipline — a second pass on RT-005): citing 0.5.40 as *precedent* still left
  the top-of-file SemVer promise ("SemVer applies to the stable core (DESIGN.md §4.0)") and this
  entry's own practice in tension for any reader who checks §4.0 without reading changelog
  precedent — a consumer pinning `~=0.5.43` has no reason to expect a stable-core wire type to
  narrow without a major bump just because a *different* prior release also did it. Resolved for
  good, not just for this release: DESIGN.md §4.0 now states a standing, explicit **wire-shape
  conformance exemption** — a stable-core wire-shape break driven by external protocol conformance
  (not a voluntary redesign) may ship under a patch/minor bump provided it carries a dedicated
  `🔴 Breaking changes` heading + Migration callout, exactly as this entry does. §4.0 is the rule
  now; this entry and 0.5.40's are its precedent, not its justification — future breaking wire-shape
  conformance fixes cite §4.0 directly instead of re-litigating this argument per release. The §4.0
  exemption is a signed-off, owned decision (not merely this CHANGELOG note): **REVIEWS.md Round 7**
  records the rejected alternative (a major bump for every stable-core wire break) and the accepted
  risk to consumers pinning `~=0.5.x`.

### 🟡 Protocol surface changes
- `split_a2ui_delivery()` (new, `agent_sdk/a2ui/translator.py`): discovered during the GH-126
  redteam pass, tracked separately as it is unrelated to GH-126's scope. `translate()` computes
  a per-artifact A2UI sequence — `createSurface` → `updateComponents` → `updateDataModel` →
  `deleteSurface` — as one logical `list[dict]`, but A2UI v0.9.1's client contract folds ONE
  delivered array atomically and paints once after the fold. Delivering all four messages in a
  single array (the prior behavior) meant a strictly spec-conformant Path-A renderer — built from
  the public spec alone, with no knowledge of this SDK's internals — would unmount the surface via
  `deleteSurface` during the fold, before it was ever painted: **nothing would render, for every
  A2UI artifact this SDK emits**, on any consumer that didn't happen to special-case this SDK's
  bundling. `split_a2ui_delivery()` splits that sequence into an `open` array
  (createSurface/updateComponents/updateDataModel) and a `close` array (deleteSurface), and both
  delivery callers now send them as two independently-folded wire units, open before close:
  `agent/runner.py::build_artifact` emits two A2A DataParts on the artifact instead of one;
  `routes/ag_ui.py`'s `ArtifactEvent` branch emits two `A2UI_UPDATE` CUSTOM events instead of one.
  On the A2A side each array is now delivered as `DataPart(data={"messages": [...]})`. **This is
  a breaking wire-shape change, not just a count change** (see the dedicated `🔴 Breaking changes`
  section above): every released version through v0.5.42
  (back to the initial commit — verified via `git show v0.5.42:agent_sdk/agent/runner.py`) emitted
  `DataPart(data=a2ui_messages, ...)` with `data` as a bare `list`, which was already non-conformant
  — the A2A base spec requires `DataPart.data` to be a JSON object (`a2a.json`/`types.ts`, pinned
  v0.3.0 tag) — but shipped that way across every tagged release to date. 0.5.44 fixes the shape by
  wrapping the message array under a `"messages"` key, matching the AG-UI CUSTOM event's
  `value.messages` convention exactly (same key, same shape). **Migration for A2A consumers:** any
  client parsing `DataPart.data` as an array for A2UI must change to reading `part.data.messages`
  (was `part.data`) — this will silently break on upgrade otherwise. `agent_sdk/models/a2a.py`'s
  `DataPart.data` is now typed `dict[str, Any]` (was `dict[str, Any] | list[Any]`) so the old
  bare-array shape fails at construction time, closing GH-128. The bare-array shape was caught by
  `/sdk-test` Leg 3's static conformance gate (a2a-advisor) before the v0.5.44 tag and fixed under
  GH-128. This is also a wire-*count* change
  for every A2UI emission (previously one DataPart/event per artifact, now up to two) — flagged
  here as a protocol surface change, not a plain fix, since any consumer that assumed exactly one
  DataPart/event per A2UI artifact must now expect two. The agent card's A2UI extension hint
  (`deleteSurfaceSemantics`, GH-113) is updated from `"post-paint"` to `"split-delivery"` to match
  — non-normative in both cases, but the value itself changed.
  Covered by `tests/test_a2ui_wire.py` (`test_split_a2ui_delivery_isolates_delete_surface`,
  `test_split_a2ui_delivery_empty_input`) plus updated assertions in
  `tests/test_gh113_delete_surface_semantics.py`, `tests/test_a2ui_group_d.py`,
  `tests/test_protocol_fixes_w6.py`, `tests/test_protocol_wire.py`, `tests/test_a2a.py`. See
  DESIGN.md §5.4/§7.1 for the full wire contract. Filed and closed as fixed: GH-127, GH-128.
  (`agent_sdk/a2ui/translator.py`, `agent_sdk/agent/runner.py`, `agent_sdk/routes/ag_ui.py`,
  `agent_sdk/a2ui/catalog.py`, `agent_sdk/console/static/a2ui.js`, `agent_sdk/console/static/chat.js`,
  `agent_sdk/models/a2a.py`, `agent_sdk/testing/chat.py`, `DESIGN.md`)
- RT-003 (redteam, low, `agent_sdk/models/a2a.py`): the `DataPart.data` narrowing above
  (`dict[str, Any]`, was `dict[str, Any] | list[Any]`) is symmetric — it also tightens INBOUND
  parsing, not just the outbound A2UI wire shape migration documented above. A `Message.parts`
  `DataPart` whose `data` is a bare array — the exact shape A2UI v0.9.1's own A2A binding mandates
  for an inbound `action` DataPart (see LRN-134) — now fails Pydantic validation at parse time and
  is rejected as `-32602` (Invalid Params) instead of being accepted. No functional regression
  today: the SDK has no inbound A2UI-action `DataPart` consumer (`Message.parts` `DataPart.data` is
  never read anywhere in `agent_sdk`), so nothing that previously worked stopped working. Recorded
  because it forecloses a future spec-conformant inbound A2UI action `DataPart` without first
  adding a bare-array-tolerant parse — if inbound A2UI actions are ever supported, they must be
  parsed through such a path (e.g. a dedicated inbound type/validator that accepts a bare array
  before Pydantic sees it), not through this tightened `DataPart` model. Pinned by
  `test_inbound_data_part_bare_array_rejected_as_invalid_params` (`tests/test_protocol_wire.py`),
  which documents the current end-to-end rejection via `POST /v1/message:send`.

### 🔧 Fixes
- GH-126 / RT-001: `apply_data_model_update()` (`agent_sdk/a2ui/translator.py`)
  now matches A2UI v0.9.1's `updateDataModel` semantics on both value- and
  path-handling.
  - Omitting `value` (the `MISSING` sentinel) deletes the key at `pointer`
    (`target.pop(leaf, None)`, a no-op if already absent) instead of leaving
    the target unchanged. `apply_data_model_update()` has no production
    callers today — `translate()`, the SDK's only emit path, always sets an
    explicit `value` — so this closes a latent server/renderer divergence.
  - A2UI v0.9.1 overrides RFC 6901 for `updateDataModel.path`: "omit `path`
    or use `/` to replace the whole data model." `""` and `"/"` are now both
    handled, identically, as a genuine whole-model replace —
    `model.clear(); model.update(value)` — evaluated before the
    root-relative check, so neither spelling falls through to ordinary
    pointer traversal. Because this is an in-place mutator (it cannot
    reassign the caller's `model` reference), *value* must be a `dict` for
    a whole-model replace; any other type raises `ValueError`. `MISSING` is
    a no-op on both spellings. An earlier revision of this fix reasoned from
    the console renderer's `pointerSet` (`agent_sdk/console/static/a2ui.js`)
    alone, whose `pointerTokens("/")` returned a literal one-segment token
    list (addressing the ordinary child key `model[""]`) rather than folding
    to the whole-model-replace empty-token-list case — that premise was
    itself non-conformant to the spec, not a valid reference. Both
    `pointerTokens` and this helper now implement the spec's `"/"` override
    directly against the A2UI spec text, and agree with each other as a
    consequence of that, not as the justification for it.
  - Parent-key navigation for ordinary (non-whole-model) pointers is a
    single traversal shared by set and delete, scaffolding missing
    intermediate dicts unconditionally and then branching on `MISSING`
    (pop) vs. set — mirroring `pointerSet`'s shape, so e.g. deleting
    `/a/b/c` on `{}` converges with the renderer's `{a: {b: {}}}` on both
    sides. Three documented, latent VALUE/TRAVERSAL divergences remain (not
    live bugs — `translate()` never emits a numeric-token, array-shaped,
    scalar-shadowed, or whole-model-replace pointer): RT-002a — a numeric path
    token (e.g. the `0` in `/metrics/0`) is treated as a literal string dict key
    here, not a list index; RT-002b — a pre-existing scalar (non-dict, non-list)
    intermediate node is preserved by this helper (set raises, delete
    no-ops) where `pointerSet` destructively overwrites it with `{}`/`[]`;
    RT-002c — a whole-model replace (`""`/`"/"`) with a non-`dict` value
    raises `ValueError` here (the helper is an in-place mutator and cannot
    write a non-object `dataModel`) where `pointerSet`'s empty-tokens branch
    (`value === undefined ? doc : value`) returns the scalar verbatim
    (`pointerSet({}, "/", "scalar")` → `"scalar"`). Each of the three — RT-002a
    (`..._on_numeric_token`), RT-002b (`..._on_scalar_intermediate_delete`), and
    RT-002c (`..._on_whole_model_replace_non_dict`) — is pinned by its own live
    node cross-check that recomputes the `pointerSet` reference at test time, so
    none can drift silently against a hand-copied literal. A FOURTH divergence —
    the deliberate `..`-token parent-escape guard (RT-JSON-POINTER-001, next
    bullet) — is a security divergence rather than a value/traversal one; the
    `apply_data_model_update()` docstring enumerates all four together so the
    tally cannot drift.
  - RT-JSON-POINTER-001: the parent-escape guard rejects ONLY a decoded
    token EQUAL to `..` (e.g. `/foo/../bar`, `/..`). This check is complete:
    it runs after `~1`/`~0` decoding and `..` has no tilde form, so nothing
    can hide a parent-escape segment from it. A prior revision additionally
    tested each decoded token for the `/..` / `../` SUBSTRINGS; those clauses
    were false-positives only — a `/` inside a decoded token can arise solely
    from `~1` (a literal key character, the split on `/` having already
    happened), so they fired exclusively on legitimate `~1`-formed literal
    keys and never on a genuine escape. Concretely `/foo~1../bar` decodes to
    the literal key `foo/..` then `bar`; the renderer's `pointerSet` accepts
    it and writes `{"foo/..": {"bar": ...}}`, and this helper now converges
    (sets the same literal key) instead of wrongly rejecting it. Rejecting a
    genuine `..` token remains a deliberate stricter-than-renderer guard (the
    renderer treats `..` as a literal key), pinned as a live-cross-checked
    divergence.
  - RT-EMPTY-SEGMENT-001: removed the over-broad `//`-prefix guard. An empty
    path segment is not a component-root escape — per RFC 6901 it addresses
    the empty-string key `model[""]`, an ordinary key within the component
    root, never the envelope or a parent. The old guard rejected only a `//`
    PREFIX while the helper already accepted every equivalent spelling that
    reaches the same empty-string key (`/a//b` → `model["a"][""]["b"]`, `/a/`
    → `model["a"][""]`), so it blocked one spelling of a legitimate operation
    and was no boundary. `//`-prefixed pointers now converge with the
    renderer's `pointerSet` (`pointerSet({}, "//bar", "X")` →
    `{"": {"bar": "X"}}`), cross-checked live. The genuine parent-escape guard
    (a decoded `..` token) is unaffected.
  - RT-002 (a later, separate redteam finding on the fix above — distinct
    from the RT-002a/RT-002b/RT-002c divergence labels earlier in this
    entry): the intersection of BOTH spec rules — path omitted/`"/"` (whole
    data model) AND `value` omitted (`MISSING`, delete-at-path) — is
    deliberately defined as a no-op. The spec states two independent rules:
    "omit `path` or use `/` to replace the whole data model" and "omit
    `value` to delete the key at path." Composed, those two rules are
    genuinely ambiguous, not spec-decided: read one way, an
    `updateDataModel` with both omitted addresses the whole model, where
    there is no single key at path for the delete rule to target — the
    delete has no referent, so the operation no-ops (this SDK's reading);
    read the other way, a spec-literal peer could treat omit-path +
    omit-value as "clear the whole model." The no-op is therefore an
    SDK-defined resolution of that ambiguity, not a spec certainty — both
    this helper and the console renderer's `pointerSet` empty-tokens branch
    (`value === undefined ? doc : value`) agree on the no-op reading, which
    is a consequence of choosing it consistently across the SDK, not proof
    the spec mandates it. This is NOT "clear the model" under the SDK's
    reading: the spec-supported way to unambiguously clear the model
    remains an explicit whole-model replace with an empty object
    (`value={}`), honored as `model.clear(); model.update({})`, so a
    caller who wants a clear is never stranded by the no-op reading. Pinned
    by
    `test_apply_data_model_update_whole_model_missing_is_noop_per_spec_no_key_at_path`,
    which documents the SDK's chosen reading of the ambiguous composition
    (not a spec oracle), alongside the existing `..._missing_value_is_noop`
    renderer-convergence tests. Cross-implementation interop risk only: a
    spec-clarification request for this composition is worth filing
    upstream with the A2UI spec maintainers so a genuinely conformant
    third-party peer has an authoritative answer rather than two SDK
    surfaces agreeing by internal convention.

  Covered by `test_apply_data_model_update_empty_pointer_replaces_whole_model`,
  `test_apply_data_model_update_slash_pointer_replaces_whole_model`,
  `test_apply_data_model_update_empty_and_slash_pointer_are_symmetric`, their
  `_missing_value_is_noop`/`_rejects_non_dict_value` counterparts, the
  convergence-table tests
  (`test_apply_data_model_update_converges_with_pointer_set_reference` and its
  live-node counterpart,
  `test_apply_data_model_update_converges_with_live_pointer_set_reference`),
  and the RT-002a/RT-002b/RT-002c divergence pins. See the docstring of
  `apply_data_model_update()` for the full contract.
  (`agent_sdk/a2ui/translator.py`, `agent_sdk/console/static/a2ui.js`)

### ⚠️ Behavior changes
- RT-004: the `MISSING` sentinel's effect on `apply_data_model_update()`
  changed from a documented no-op to delete-at-path (`target.pop(leaf, None)`).
  Both `apply_data_model_update` and `MISSING` are importable submodule
  utilities on `agent_sdk.a2ui.translator` — NOT part of the package public
  API: neither is in any `__all__`, and `agent_sdk.a2ui.__init__` re-exports
  only `A2uiCapabilities`, `get_system_prompt_section`, and `translate`. They
  are therefore provisional per the SemVer note at the top of this file, so a
  behavior change ships in a patch. Still flagged explicitly because the
  symbols ARE importable: any external code that reached into the submodule and
  imported `MISSING` relying on the previously-documented no-op now silently
  deletes the key at `pointer` instead (the old behavior was a latent bug, and
  there are no in-repo callers). The whole-model-replace forms (`""`/`"/"`)
  with `MISSING` remain a no-op (see the value-semantics contract in the
  `apply_data_model_update` docstring).

## [0.5.43] — 2026-07-20

### 📖 Docs
- GH-124: `for_custom_emit()`'s (`agent_sdk/a2ui/translator.py`) deliberate
  Extended-tier bypass on the AG-UI CUSTOM-event path — a client that
  declares `tier="core"` still receives in-catalog Extended Standard-Profile
  types (e.g. `WaterfallChart`), unlike `allows()` on the A2A DataPart path,
  which does enforce Extended-tier gating — was re-flagged as a HIGH
  conformance bug by a fresh `/agent-stack-check` run. On review this is the
  intentional, already-tested LRN-049 decision, not a defect:
  `tests/test_rt001_ag_ui_custom_extended_gate.py` already pins
  `WaterfallChart` emitting under `tier="core"`, and AG-UI's silent-ignore of
  unknown CUSTOM events is the safety net A2A DataPart lacks, so withholding
  data here has no protective value and only breaks graceful degradation.
  GH-124 closed as not-a-bug. Strengthened the `for_custom_emit()` docstring
  with this rationale so it isn't re-flagged. No behavior change.
  (`agent_sdk/a2ui/translator.py`)

## [0.5.42] — 2026-07-20

### 🟠 Security
- GH-122: consent-page `Content-Security-Policy: form-action` now covers the **entire** redirect chain (consent-page GET, 401 re-render, error redirect, success redirect) via a shared `_redirect_security_headers()` helper, closing a gap where Chromium/Electron enforce `form-action` against the form-owning document's CSP across the whole chain (crbug.com/932518) rather than a later 30x hop's CSP alone. The advertised origin is now rebuilt from sanitized components (`_validated_origin()`) instead of interpolating the raw `netloc`/`.hostname`, closing a CSP-header-injection vector (RFC 3986 `reg-name` permits `;`/space characters that `urlparse().hostname` doesn't reject). IPv6-literal `redirect_uri`s are now rejected outright (fail-closed) rather than best-effort sanitized. (`agent_sdk/routes/oauth.py`)

### 🔧 Fixes
- GH-118: `sdk-wave.js`/`wave-cycle.js` (and harness/template mirrors)'s `archiveIntent` import-resolution gate now handles sub-package imports and both absolute/relative import forms via a four-way disambiguation ladder, kept in sync across runner copies by `test_workflow_sync.py`. (`.claude/workflows/sdk-wave.js`, `.claude/workflows/wave-cycle.js`)

### 🧪 Test / CI
- Codifies LRN-126 through LRN-132 from wave w035's redteam rounds (`workspace/learning/`).

## [0.5.41] — 2026-07-15

### ✅ Features
- GH-113: `a2ui_extension()` (`agent_sdk/a2ui/catalog.py`) now advertises a new extension param `deleteSurfaceSemantics: "post-paint"` alongside `supportedCatalogIds`/`acceptsInlineCatalogs` — carries the show-then-close `deleteSurface` convention (DESIGN.md §5.4/§7.1), previously inferable only from the admin console's `a2ui.js` renderer source, on the card itself. `deleteSurfaceSemantics` is a **non-normative, SDK-specific hint** — it is not a field A2UI v0.9.1 or Standard Profile v1 defines, and a consumer implementing its own renderer (Path B or third-party) must already know this SDK's convention to interpret the key/value; it is not a spec-defined discovery mechanism, just a wire hint that spares reverse-engineering the renderer source. Additive, non-breaking. (`agent_sdk/a2ui/catalog.py`, `DESIGN.md`)

### 🔧 Fixes
- GH-119: `agent_sdk/app.py`'s CORS allow-list now unions the deployment's own resolved base-URL origin (`{scheme}://{netloc}` of `settings.resolved_base_url`) alongside the existing `CORS_ORIGINS` entries and `https://claude.ai`, so the bundled console's same-origin requests aren't 403'd by `guard_origin()` on a non-claude.ai deployment that never explicitly listed itself in `CORS_ORIGINS`. **Operator-visible:** the effective allow-list is now wider than `CORS_ORIGINS` alone. RT-001: only the ORIGIN component is unioned, never the full URL — browser `Origin` headers are always path-less (RFC 6454), so a path-prefixed `PUBLIC_URL` (e.g. a reverse-proxy deployment at `https://gw.example.com/agents/x`) contributes only `https://gw.example.com`, or the entry could never equal a real `Origin`. (`agent_sdk/app.py`)
- GH-120 / GH-121: a `long_running` tool may return a `DeferredResult` whose handle resolves to ANOTHER `DeferredResult` (nested deferral). `ToolEntry.invoke_any` (`agent_sdk/agent/registry.py`) now follows that chain up to `_MAX_DEFERRED_RESOLUTIONS` (2 handles total) instead of returning the nested object verbatim — previously the un-awaited nested handle's `repr` was baked into the MCP `tools/call` wire text under a false `isError: false`. Nesting beyond the bound closes/cancels the handle and raises `AgentError`, which every caller (`routes/mcp.py`, `routes/admin.py`, the commitments executor) now maps to its `isError`/`ok:false` path — `routes/admin.py`'s `try_tool` did NOT handle `DeferredResult` at all before this wave (see the `invoke_any` signature-change entry below); only `routes/mcp.py` and the commitments executor were previously correct. (`agent_sdk/agent/registry.py`)
- RT-001 (redteam, C-012): the nested-resolution loop was extracted to a new module-level `resolve_deferred_result(result, *, tool_name, handle_timeout)` (registered as **C-012**) so `runner._run_deferred_background` — the A2A/AG-UI background awaiter for a `DeferredEvent` — shares the IDENTICAL nesting-depth bound and rejection point as `invoke_any` instead of maintaining its own divergent branch. A `long_running` tool's nesting-depth contract can no longer drift by transport. The shared guarantee is scoped to DEPTH, not the timeout budget (see C-012 in `workspace/components/README.md`). (`agent_sdk/agent/registry.py`, `agent_sdk/agent/runner.py`)
- RT-001 (redteam, `agent_sdk/agent/registry.py`, **public signature change**, C-010): `ToolEntry.invoke_any(arguments, adapters)` gained two new keyword-only params, `timeout: float | None = None` and `policies: LoopPolicies | None = None`. When `timeout` is given it bounds the initial invoke/drain AND the DeferredResult-resolution handle(s) it awaits under ONE shared deadline — the handle gets only the budget remaining after the initial call, never a fresh `timeout` seconds on top (RT-003). When omitted (the commitments executor's call shape — unchanged), the initial call stays unbounded and only a returned `DeferredResult` is bounded, via `resolve_tool_timeout` against `policies` (or a default `LoopPolicies()`). Existing positional callers (`invoke_any(arguments, adapters)`) are source-compatible — both new params default to the prior unbounded/no-policy behavior. `routes/mcp.py`'s `_handle_tools_call` and `routes/admin.py`'s `try_tool` now both dispatch through `invoke_any(..., timeout=timeout)` instead of each re-implementing the `is_generator`/`DeferredResult` branch inline. Registered as **C-010** in `workspace/components/README.md`. (`agent_sdk/agent/registry.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/routes/admin.py`)
- RT-001 (redteam, SI-2, `agent_sdk/routes/admin.py`): `POST /admin/api/tools/{name}/try` built its `ValidationError` response from raw Pydantic `e['msg']` under a `# never echo input values` comment that was false — `errors(include_input=False)` strips only the `input` key, NOT `msg`, so a tool's own `@field_validator` that interpolates the rejected value into its error message (e.g. `raise ValueError(f"invalid token {v!r}")`) reflected that value verbatim into the admin response. A tool argument can itself be a credential/token, making this an SI-2 leak on the admin surface. Routed through `safe_validation_message()` (`agent_sdk/agent/loop.py`), the same helper `routes/mcp.py` already used — keeps only `loc` + `type`. **Wire-visible:** the try-tool endpoint's validation-error shape changed from `{"error": {"category": "validation", "errors": [{"loc", "msg", "type"}, ...]}}` to `{"error": {"category": "validation", "message": <str>}}`. (`agent_sdk/routes/admin.py`)
- RT-001 (redteam, `agent_sdk/agent/loop.py`): an async-generator (`is_generator`) tool whose TERMINAL yield is a `DeferredResult` was not detected as deferred — only the coroutine branch ran the `isinstance(result, DeferredResult)` handoff. The raw `DeferredResult` leaked onto `ToolResultEvent`/AG-UI `TOOL_CALL_RESULT` and was `str()`-folded into the model conversation, and the handle was never awaited (`ResourceWarning: coroutine never awaited`; the long-running job never ran). The generator branch now runs the same handoff, so a generator tool's terminal `DeferredResult` behaves identically to a coroutine's across the MCP and A2A/AG-UI surfaces. (`agent_sdk/agent/loop.py`)
- RT-001 (redteam, `agent_sdk/agent/runner.py`): `_run_deferred_background`'s SUCCESS path built and serialized the terminal artifact (`build_artifact()` / `TaskArtifactUpdateEvent.wire()`) OUTSIDE any try/except, unlike the synchronous `run_task_worker`'s equivalent (guarded) `ArtifactEvent` branch. A raise here (e.g. `_validate_a2ui_wire` rejecting a malformed domain card) escaped the fire-and-forget `asyncio.Task` nobody awaits, stranding the A2A task in WORKING forever with every SSE subscriber queue left un-sentinel-closed until the TTL sweep. The build/serialize step is now wrapped: a `ValueError` maps to the existing `-32006` ("invalid agent response") code — mirroring `run_task_worker`'s mapping — anything else to `-32603` ("internal error"), both routed through the new `_fail()` helper (FAILED + synthetic `ToolResultEvent(ok=False)` + closed streams; SI-2: only a fixed string is echoed, never exception/handle text). (`agent_sdk/agent/runner.py`)
- RT-002 (redteam, wire behavior — AG-UI): on deferred-task **FAILURE** (timeout / cancellation / tool error / terminal-artifact build failure), `runner._run_deferred_background`'s `_fail()` now publishes a synthetic `ToolResultEvent(ok=False)` → AG-UI `TOOL_CALL_RESULT`, closing the tool-call lifecycle that the pre-`DeferredEvent` `TOOL_CALL_START` opened. Previously the failure path emitted no matching result, so strict AG-UI clients observed a `TOOL_CALL_START` with no `TOOL_CALL_RESULT`. `frame=None`, so A2A SSE consumers skip it; only the AG-UI RunMapper consumes it. (`agent_sdk/agent/runner.py`)
- RT-002 (redteam, `agent_sdk/agent/runner.py`): a FAILED task must never retain an artifact that was never delivered on any stream. The wave's initial reorder serialized the `TaskArtifactUpdateEvent` frame before mutating `task.artifacts`, closing the `.wire()`-raises sub-case — but the append still preceded `publish()`, so a `publish()` failure (a persistent `TaskStore` whose durable write fails) flipped the task to FAILED (sync path) / propagated out of the background task (deferred path) with a never-delivered artifact still attached. The append now runs only AFTER `publish()` has delivered the frame, at BOTH call sites (`run_task_worker`'s `ArtifactEvent` branch and `_run_deferred_background`'s success path). (`agent_sdk/agent/runner.py`)
- GH-110: `agent_sdk/routes/mcp.py`'s defense-in-depth Origin allow-list check (RT-004, shipped pre-0.5.x) was enforced on every MCP browser-reachable streaming surface but was missing from `agent_sdk/routes/ag_ui.py`'s `POST /ag-ui/run` and all 6 `agent_sdk/routes/a2a.py` handlers (`message_send`, `message_stream`, `tasks_list`, `tasks_get`, `tasks_cancel`, `tasks_resubscribe`) — an inconsistent partial hardening of RT-004's own stated intent ("every browser-reachable streaming surface"). `mcp.py`'s 5 duplicate inline checks are now extracted into a shared `guard_origin(request)` predicate (new `agent_sdk/common/origin.py`, C-009); `a2a.py`/`ag_ui.py` are newly guarded by 7 net-new call sites, not deduplicated from an existing copy. Behavior is unchanged for MCP; `a2a.py`/`ag_ui.py` now reject a present-but-disallowed `Origin` header with 403 (static `"origin not allowed"` detail — the untrusted header value is never interpolated into the response or a log line, SI-2) while an absent or allow-listed Origin still passes through unaffected. (`agent_sdk/common/origin.py`, `agent_sdk/routes/a2a.py`, `agent_sdk/routes/ag_ui.py`, `agent_sdk/routes/mcp.py`)
- RT-003 (folded into the GH-110 fix): `InterruptEvent.expires_at` (`agent_sdk/agent/events.py`) renamed to `expires_in` — the field has always held seconds-remaining-until-expiry (a relative duration computed by `TaskStore.interrupt_ttl_remaining`), never an absolute time, and the old name was a holdover from the 0.5.40 AGUI-1 fix that superseded its own wording without updating it. Also updated where it's set (`agent_sdk/agent/runner.py`) and read (`agent_sdk/routes/ag_ui.py`). Internal-only — `InterruptEvent` is not exported from any `__init__`, constructed only in `agent_sdk/agent/loop.py`, so this is not a public API break. The wire field (`Interrupt.expiresAt`, ISO-8601 string) is unaffected. (`agent_sdk/agent/events.py`, `agent_sdk/agent/runner.py`, `agent_sdk/routes/ag_ui.py`)
- RT-001 (redteam finding on this wave, reverted): a prior revision of the GH-110 fix also switched `agent_sdk/routes/a2a.py`'s `_now_iso()` and `agent_sdk/agent/runner.py`'s `_now()` from `datetime.now(timezone.utc).isoformat()` (microsecond precision, explicit `+00:00` offset) to the shared `iso_utc()` helper (fixed-width, no microseconds, literal `Z` offset) — a stable-core A2A wire format change (`TaskStatus.timestamp`, DESIGN.md §4.0) bundled untracked into an Origin-hardening todo, with no CHANGELOG entry and no conformance test pinning the new format. Reverted out of this wave; `_now_iso()`/`_now()` are unchanged (still `datetime.now(timezone.utc).isoformat()`). A future consolidation onto `iso_utc()` must land under its own tracked todo, its own CHANGELOG entry, and a passing conformance test. (`agent_sdk/routes/a2a.py`, `agent_sdk/agent/runner.py`, `agent_sdk/common/iso8601.py`)
- GH-111: `mcp_get` and `mcp_delete` (`agent_sdk/routes/mcp.py`) never called the existing `_negotiated_version()` helper that `mcp_post` already uses, so a present-but-unrecognized `MCP-Protocol-Version` header value was silently accepted on those two verbs instead of the 400 `mcp_post` already returns for the same invalid-value case. Both now return `400 {"error": "unsupported MCP-Protocol-Version"}` (with a `MCP-Protocol-Version` response header naming the server's preferred version) when the header is present but unrecognized; an absent header is unaffected on both verbs (locked GH-77/w022 ruling — not re-litigated). `mcp_get`'s return type widened to `StreamingResponse | JSONResponse`. (`agent_sdk/routes/mcp.py`)
- GH-112: `ChatDriver.a2a_turn` (`agent_sdk/testing/chat.py`, a provisional surface — see header) walked the agent card's `additionalInterfaces` for a `JSONRPC`/`HTTP+JSON` fallback transport whenever `preferredTransport` was unsupported, but never acted on the result — every request unconditionally POSTed to `/v1/message:send` regardless of the computed value, so the walk executed but its outcome was discarded; the old regression test only passed because the unconditional POST would have succeeded either way, not because the fallback logic did anything. DESIGN.md's v1 non-goals already scope A2A client support to HTTP+JSON only, so the dead code is deleted rather than wired up: `a2a_turn` now raises `ValueError` for any `preferredTransport` other than `"HTTP+JSON"`, with no `additionalInterfaces` fallback. `agent_sdk/__main__.py`'s `test-chat --url`/`--a2a` help text now states the HTTP+JSON-only limitation. (`agent_sdk/testing/chat.py`, `agent_sdk/__main__.py`)
- F1 (post-release protocol re-audit, independently raised by `a2a-advisor` and `a2ui-advisor`): `store.close_streams()` calls inside the FAILURE-HANDLING paths themselves — `_run_deferred_background`'s `_fail()`, `run_task_worker`'s `except AgentError`/`except Exception` handlers, and `tasks_cancel`'s terminal publish — were not guarded by `try`/`finally`. A `publish()` failure INSIDE one of those already-failing paths (as opposed to a `publish()` failure that merely triggers entry into the path, which the existing RT-002 tests cover) could itself skip stream teardown, stranding SSE subscribers un-sentinel-closed until the TTL sweep. All four sites now wrap their terminal `publish()` call(s) in `try`/`finally: store.close_streams(...)`, mirroring the guard already present on the deferred-success path. Theoretical risk only — `InMemoryTaskStore`'s `publish()`/`close_streams()` never raise; this hardens custom/persistent `TaskStore` implementations under double-failure conditions. (`agent_sdk/agent/runner.py`, `agent_sdk/routes/a2a.py`)
- AG-UI advisor (post-release protocol re-audit, Low): `agent_sdk/routes/admin.py`'s `overview` and `selfcheck_info` diagnostics endpoints displayed the raw configured `settings.cors_origins` instead of the GH-119-resolved allow-list `guard_origin()`/`CorsMiddleware` actually enforce (which also includes the deployment's own resolved-base-URL origin). Cosmetic — the enforcement layer already read the correct resolved value — but the admin diagnostics could show a narrower list than what was actually allowed. Both endpoints now report `sorted(request.app.state.cors_origins)`. (`agent_sdk/routes/admin.py`)

### 🧪 Test / CI
- `tests/test_rt002_failed_task_no_stranded_artifact.py` — `.wire()`-raises and `publish()`-raises sub-cases for both the sync `ArtifactEvent` path and the deferred-background path; asserts a FAILED/erroring task retains no undelivered artifact
- `tests/test_rt002_deferred_failed_tool_result.py`, `tests/test_rt002_close_streams_finally_on_publish_failure.py`, `tests/test_rt002b_deferred_terminal_frame_no_duplicate.py`, `tests/test_rt002c_sync_worker_terminal_frame_no_flip.py` — synthetic failure `TOOL_CALL_RESULT`, `close_streams()` in `finally`, and no-duplicate/no-flip terminal-frame guarantees
- `tests/test_gh120_invoke_any_nested_deferred_result.py`, `tests/test_gh121_nested_deferred.py`, `tests/test_rt001_deferred_nesting_parity.py`, `tests/test_rt001_invoke_any_shared_timeout.py`, `tests/test_rt001_gen_tool_terminal_deferred_result.py` — nested-`DeferredResult` depth bound, cross-surface parity, shared-deadline budget, and the async-generator terminal-`DeferredResult` handoff
- `tests/test_rt002_invoke_any_deferred_result.py` — `invoke_any()` resolves a `DeferredResult` from a `long_running=True` COROUTINE tool (not just the generator form) end-to-end through the real `CommitmentExecutor`
- `tests/test_rt001_deferred_task_handle_cancel.py` — max-depth cleanup calls `.cancel()` (not just `.close()`) so an abandoned `asyncio.Future`/`Task`-backed handle, not only a coroutine one, is actually cancelled rather than left running unobserved
- `tests/test_admin_try_tool_deferred_result.py` — `try_tool`'s `DeferredResult` resolution (resolved value returned, never a raw repr) and prompt timeout handling
- `tests/test_admin_try_tool_validation_leak.py` — pins the SI-2 fix: a custom `@field_validator`'s rejected input value never appears in the `try_tool` response, which still names the offending field
- `tests/test_rt001_deferred_artifact_build_failure.py` — a deferred tool whose resolved value makes `build_artifact()` raise deterministically reaches FAILED with streams closed, mirroring `test_gh87_deferred_task.py`
- `tests/test_common_origin_guard.py` (new) — unit coverage for `guard_origin()` in isolation: absent Origin passes, allow-listed Origin passes, disallowed Origin raises `HTTPException(403, "origin not allowed")`
- `tests/test_gh110_origin_allowlist.py` (new) — 403 for a disallowed Origin and pass-through for absent/allowed Origin, across `POST /ag-ui/run` and all 6 `a2a.py` handlers
- `tests/test_http_protocol.py` — 4 new cases: `mcp_get`/`mcp_delete` with a bogus `MCP-Protocol-Version` → 400; regression cases confirming the no-header path on both verbs is unaffected
- `tests/test_chat_driver.py` — `test_sc_e3_additional_interfaces_fallback`/`test_sc_e3_no_fallback_raises` rewritten to assert `ValueError` for any non-`"HTTP+JSON"` `preferredTransport`, including when `additionalInterfaces` lists a supported transport
- `tests/test_gh113_delete_surface_semantics.py` (new), `tests/test_card_console.py` — `a2ui_extension()`/agent-card assertions that `params.deleteSurfaceSemantics == "post-paint"`
- `tests/test_rt001_a2a_timestamp_wire_format.py` (new) — pins `TaskStatus.timestamp` (via `message:send` and `tasks:cancel`) to the microsecond-precision, `+00:00`-offset form, guarding against the reverted `iso_utc()` switch silently reappearing
- `tests/test_f1_close_streams_double_failure.py` (new) — real store subclasses whose `publish()` raises on EVERY call (not just once, unlike the existing RT-002 stores) drive the F1 double-failure scenario across all three fix sites: `run_task_worker`'s generic exception handler, `_run_deferred_background`'s `_fail()` under `CancelledError`, and `tasks_cancel`'s terminal publish — asserting `close_streams()` still runs in every case

### — Other
- GH-114: added `workspace/learning/LRN-115-agui-capabilities-fail-closed-tier-none-default.md`, documenting GH-74's deliberate fail-closed `tier="none"` default in `agent_sdk/routes/ag_ui.py`'s `_capabilities()` as intentional — not a bug to "align" with `A2uiCapabilities.from_metadata(None)`'s fail-open default. Pure documentation debt; no code or test change.

## [0.5.40] — 2026-07-11

### 🔴 Breaking changes
- `TaskStore` (`agent_sdk/tasks/store.py`) gained a new concrete method `interrupt_ttl_remaining(task_id) -> float | None`, defaulting to `None` (unknown) so every pre-existing external `TaskStore` subclass keeps instantiating without modification. Subclasses that predate this hook now silently stop emitting `Interrupt.expiresAt` on AG-UI interrupt outcomes (previously they emitted a wrong, monotonic-clock-derived absolute value on that field — see the AGUI-1 entry below). Override `interrupt_ttl_remaining` to compute seconds-remaining from your store's own tracked deadline and clock to restore the field. `InMemoryTaskStore` (`agent_sdk/tasks/memory.py`) already overrides it.

### 🔧 Fixes
- GH-104: `agent_sdk/app.py`'s `_A2A_CODE` HTTP-status→JSON-RPC-error-code table had no `404` entry, so an unmatched `/v1/*` route fell through to the generic `-32603` (Internal Error) default instead of the spec-correct `-32601` (Method not found) — the same code MCP's own method-dispatch-miss fallback already uses (`agent_sdk/routes/mcp.py`). This reverses a deliberate w021/RT-003 ruling that left 404 unmapped without considering `-32601`. (`agent_sdk/app.py`)
- GH-105: `MarketBriefing`, the SDK's one "prose exception" `ContentModel`, leaked a bare-string `Tool.outputSchema`/`structuredContent` on the MCP surface (`{"type": "string"}` / a raw markdown string) — MCP 2025-06-18 requires both to always be JSON objects. Now wrapped as `{"markdown": <string>}` on the MCP surface (and the agent card's `x-sdk.outputSchema`, which shares the same registry method). The AG-UI/A2A `DataPart` wire contract (`agent_sdk/a2ui/translator.py`) is unchanged and still emits the bare markdown string — that ratification (RTGA-001/RTGA-005) only ever covered AG-UI/A2A, not MCP. (`agent_sdk/agent/registry.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/routes/agent_card.py`)
- AGUI-1: `agent_sdk/routes/ag_ui.py` emitted `Interrupt.expiresAt` as an int epoch-ms, but the upstream `ag-ui-protocol` SDK types the field `Optional[str]` (confirmed against the installed `ag-ui-protocol==0.1.19` package) — a spec-strict consumer's reference Pydantic model would fail validation. The value also originated from a `time.monotonic()`-based deadline, so a naive int→str cast would have produced a near-1970 date. Fixed by threading a clock-agnostic *relative* TTL through the stack: `TaskStore.interrupt_ttl_remaining()` (see Breaking changes above) → `agent_sdk/agent/runner.py` sets `event.expires_at` to the relative seconds-remaining → `ag_ui.py` rebases it against wall-clock `time.time()` and serializes via the new `agent_sdk/common/iso8601.py` helper as ISO-8601 UTC. See `workspace/learning/LRN-111`, `LRN-112`. (`agent_sdk/routes/ag_ui.py`, `agent_sdk/common/iso8601.py`, `agent_sdk/agent/events.py`, `agent_sdk/agent/runner.py`, `agent_sdk/tasks/memory.py`, `agent_sdk/tasks/store.py`)
- AGUI-2: the admin console's `chat.js` folded a completed assistant turn back into `state.aguiMessages` using the multimodal list-of-parts content shape that's only valid for `UserMessage` — `AssistantMessage.content` is `Optional[str]` per the upstream spec. Every later `RunAgentInput` in the session replayed the malformed assistant message; invisible against this SDK's own server (which tolerates either shape) but would 422 on turn two against a spec-strict third-party AG-UI server. Fixed to `content: buf.text()` (plain string). (`agent_sdk/console/static/chat.js`)
- AGUI-3: `chat.js`'s AG-UI resume path sent `resume: [{ interruptId, status: "resolved", payload: text }]` — a bare-string `payload`. `agent_sdk/contrib/action_gate/gate.py::parse_decision()` only reads a decision out of a dict payload (`payload = raw_payload if isinstance(raw_payload, dict) else None`); a bare string was silently discarded and every action_gate-gated tool confirmation driven from the console's AG-UI tab landed on `Outcome.UNCLEAR` regardless of the user's actual approve/reject intent. Fixed to `payload: { decision: text }`. Found by this release's own static conformance re-audit, not the originating wave. (`agent_sdk/console/static/chat.js`)

### 🧪 Test / CI
- `tests/test_a2a_error_envelope.py::test_unknown_v1_route_404_a2a_envelope` — asserts `-32601` (was `-32603`)
- `tests/test_mcp_conformance_w9.py` — `MarketBriefing` outputSchema/structuredContent object-wrapper shape on MCP; agent-card `x-sdk.outputSchema` mirrors it (RT-004); AG-UI/A2A bare-string wire contract confirmed unchanged
- `tests/test_iso8601.py` (new), `tests/test_task_memory_store.py` (new) — the ISO-8601 helper and `interrupt_ttl_remaining` hook
- `tests/test_ag_ui.py`, `tests/test_ag_ui_group_b.py`, `tests/test_gh97_ag_ui_thread_run_id_synthesis.py` — updated for the relative-TTL `expires_at` contract
- `tests/test_card_console.py::test_agui_assistant_turn_fold_uses_plain_string_content` (new) — pins AGUI-2
- `tests/test_card_console.py::test_agui_resume_payload_matches_action_gate_contract` (new) — pins AGUI-3

### — Other
- This release's `/sdk-test` Leg 3 re-audit (full 4-advisor `/agent-stack-check`) also surfaced several Medium/Low findings unrelated to GH-104/GH-105/AGUI-1–3 — deliberately deferred, not fixed here, per `workspace/sdk-candidates.md` Candidates 4–8: an AG-UI/A2A Origin allow-list defense-in-depth gap (Medium), a missing `MCP-Protocol-Version` check on the MCP GET/DELETE verbs (Medium), a dead transport-selection code path in the `ChatDriver` test utility (Medium), a third-party-interop trap in A2UI's atomic per-artifact message bundling (Medium), and an undocumented-as-LRN capability-default divergence from GH-74 (Low). None affect this SDK's own server/console surfaces.

## [0.5.39] — 2026-07-11

### 🔧 Fixes
- `TimeSeriesDataPoint.value` (`agent_sdk/models/content_types.py`) is required-but-nullable on the frozen `time_series` Standard Profile v1 contract — a data-gap point must still carry `"value": null`, never omit the key. `_Wire.wire()`'s blanket `model_dump(..., exclude_none=True)` was silently dropping the key whenever `value` was `None`, which (a) violated MCP's declared `outputSchema` for any tool emitting a `TimeSeriesChart` via `structuredContent`, and (b) broke the same frozen contract on A2UI's wire delivery over both A2A DataPart and AG-UI CUSTOM (`A2UI_UPDATE`). Fixed via a `model_serializer(mode="wrap")` on `TimeSeriesDataPoint` that re-inserts `value: null` when the field is `None`, without disturbing the Python-level `is None` semantics `TimeSeriesChart.to_plain_text()` relies on. Surfaced independently by both the MCP and A2UI static conformance audits (`LRN-110`). (`agent_sdk/models/content_types.py`)
- `agent_sdk/routes/agent_card.py`: removed a dead `_is_placeholder` local left orphaned by the w024/GH-86 description-fallback refactor — `settings.is_placeholder_name` itself is unchanged and still used elsewhere.

### 🧪 Test / CI
- `tests/test_a2ui_wire.py::test_time_series_wire_data_keys_conform_to_profile` — updated to assert `value: null` survives the wire for a data-gap point (previously asserted the dropped-key bug as spec-conformant) and that a genuinely absent optional field (`label`) is still correctly excluded.

### — Other
- Static conformance audit (`/agent-stack-check . --static-only`, run as `/sdk-test` Leg 3 ahead of this release) also flagged `agent_sdk/a2ui/translator.py`'s `A2uiCapabilities.for_custom_emit()` as a possible Core/Extended tier-gating gap on the AG-UI CUSTOM path. Investigated and confirmed this is the deliberate, already-shipped behavior from `test_rt001_ag_ui_custom_extended_gate.py` (v0.5.20, `LRN-049`): AG-UI CUSTOM events are gated only on `tier=='none'`, not on Core/Extended, because AG-UI consumers silently ignore unknown CUSTOM types and stricter gating only breaks discovery. No code change; left as-is.

## [0.5.37] — 2026-07-10

### 🔧 Fixes
- GH-95: `MarketBriefing`'s section types (`BriefingKpiItem.value`/`.delta`, `ChartSection.data`, `TableSection.data`) previously accepted non-finite floats with no validation, silently splitting the dual-part artifact contract — `model_dump_json()` serializes `inf`/`nan` as JSON `null` while `to_markdown()`/`to_plain_text()` render them literally as `"inf"`/`"nan"`, so a client's structured and text views of the same card would disagree. Fixed via per-field validators scoped to exactly the four fields GH-95's AC named, using a shared `_assert_finite()` helper that recurses through dict/list/tuple nesting and any embedded pydantic `BaseModel` values. (RT-001: an earlier revision broadened this onto a `_Wire`-wide `model_validator` covering every `ContentModel` field SDK-wide and shipped it as a patch despite self-declaring a breaking change — reverted to the AC's original scope, so this is a non-breaking patch fix.) (`agent_sdk/models/content_types.py`)
- GH-96: `agent_sdk/routes/ag_ui.py`'s `stream()` now catches any non-`StreamTerminated` exception raised inside its event loop (e.g. from `mapper.map()` or a store call) and yields a `RUN_ERROR` terminal frame with the static message `"internal error"` before the `finally` unsubscribe runs — previously such an exception propagated past the post-loop `terminal_sent` safety net and the SSE connection died with no terminal frame at all, violating the AG-UI "exactly one terminal event" invariant. The error message is intentionally static (never `str(exc)`) per SI-2: the exception can carry tool/user payload. (`agent_sdk/routes/ag_ui.py`)
- GH-97: `_validate()` no longer rejects the client's raw `body` for missing/malformed `threadId`/`runId` — those fields are already synthesized into local variables and used for `RUN_STARTED` before `_validate` runs, so the old check unconditionally emitted `RUN_ERROR: "threadId is required"` immediately after a valid `RUN_STARTED`. `_validate` now only checks `messages` shape and content. (`agent_sdk/routes/ag_ui.py`)
- GH-98: `TOOL_PROGRESS` (added in GH-88/w025) is now declared in `agent_card.py`'s `CUSTOM_EVENTS`/`_CUSTOM_EVENT_SCHEMAS` (`{message: string, toolName: string}`) and handled by the admin console's `chat.js` `handleCustom()` — previously the event was genuinely emitted on the wire but absent from both the agent card and the console's reference renderer, which fell through to "unrecognized CUSTOM event". (`agent_sdk/routes/agent_card.py`, `agent_sdk/console/static/chat.js`, `DESIGN.md`)
- GH-99: the `load_skill` unknown-skill-name error path (`agent_sdk/agent/loop.py`) now truncates to 64 chars and strips control characters from the caller/model-supplied skill name before embedding it in `ToolResultEvent.error`, matching the sanitization the adjacent unknown-tool branch already applied — previously the raw name reached `ToolResultEvent.error` (and from there the AG-UI `TOOL_CALL_RESULT` SSE frame) unsanitized (SI-2). (`agent_sdk/agent/loop.py`)
- GH-100: `Agent(exclude_from_catalog=[...])` lets always-on/guardrail skills be inlined into `persona`/`artifacts_dir` (unconditionally in the system prompt) while being omitted from the advertised skills catalog text folded into that same system prompt — the skill remains fully loadable via `load_skill`/`app.state.skills.load()`, it is just not listed. Validated at `build_app()` boot (unknown names raise `ValueError`); no post-build mutation hook. (`agent_sdk/app.py`, `agent_sdk/agent/skills.py`, `DESIGN.md`)
- GH-101: `ToolSet.tool()` now logs a `WARNING` at registration time when a tool function's `__name__` ends in `_tool` and no explicit `name=` override was supplied — the `_tool` suffix is registered verbatim (never stripped), which was a recurring cause of a skill/persona being authored against a tool name that doesn't exist. Never raises, never renames. (`agent_sdk/agent/registry.py`, `docs/tools.md`)

### 🧪 Test / CI
- `tests/test_content_types.py` — GH-95 cases (`BriefingKpiItem`/`ChartSection`/`TableSection` reject non-finite, finite payloads round-trip); RT-001 cases proving fields outside the AC's four (`MetricItem`, `BarItem`, `WaterfallSegment`, `ComparisonTable` rows, `FundPerformance.irr`, free-form `metadata`) intentionally still accept non-finite floats; RT-003 cases proving `_assert_finite` catches a non-finite float nested inside a foreign (non-`_Wire`) `BaseModel` embedded in `ChartSection.data`/`TableSection.data`
- `tests/test_gh96_ag_ui_terminal_event_coverage.py` — forces a non-`StreamTerminated` exception mid-stream, asserts exactly one `RUN_ERROR` frame terminates the SSE stream
- `tests/test_gh97_ag_ui_thread_run_id_synthesis.py` — omitted/empty-string/non-string `threadId`/`runId` synthesize correctly and never trigger a post-`RUN_STARTED` `RUN_ERROR`
- `tests/test_card_console.py` — strengthened to derive the emitted-event-name set from `ag_ui.py`'s event types and assert it equals `CUSTOM_EVENTS` (card-vs-emitted parity, not just card-vs-console)
- `tests/test_agent_skills.py` — `TestUnknownSkillSI2SurfaceCoverage`: a crafted control-char/oversized skill name never appears verbatim in the AG-UI `TOOL_CALL_RESULT` payload or the A2A `ToolResultEvent.error`
- `tests/test_skills_catalog.py` — `exclude_from_catalog` omits entries from `catalog_text()` while `load()` still resolves them; unknown name raises at `build_app()`
- `tests/test_gh101_tool_suffix_name_warning.py` — `_tool`-suffixed name with no `name=` warns (via `caplog`); explicit `name=` override suppresses it; non-suffixed name never warns

## [0.5.36] — 2026-06-24

### 🔧 Fixes
- GH-94: `openai.RateLimitError` now raises `AgentError(ErrorCategory.RATE_LIMITED, "model rate limit exceeded; retry later")` instead of being swallowed by the bare `except Exception` as a generic `"model invocation failed"` — callers can now distinguish transient rate-limit failures from fatal errors; `Retry-After` header is extracted into `detail={"retry_after": n}` when present. (`agent_sdk/agent/openai_client.py`)

### 🧪 Test / CI
- `tests/test_gh94_rate_limit_error.py` — 4 cases: `RateLimitError` → `RATE_LIMITED` category, message distinct from fatal, fatal errors still `UPSTREAM`, `Retry-After` header extraction

## [0.5.35] — 2026-06-24

### ✅ Features
- GH-93: `pip install "agent-sdk[openai]"` now installs the `openai` package via a declared optional extra; `build_app()` probes eagerly for `openai` when `OPENAI_MODEL` or `AZURE_OPENAI_ENDPOINT` is set and raises `ImportError` with a clear `agent-sdk[openai]` install hint if absent; `converse()` in `openai_client.py` now re-raises `ModuleNotFoundError` before the bare `except Exception` so missing-package errors are never swallowed as generic `AgentError`. (`pyproject.toml`, `agent_sdk/app.py`, `agent_sdk/agent/openai_client.py`)

### 🧪 Test / CI
- GH-93: `tests/test_gh93_openai_missing_package.py` — 2 cases: startup import probe raises `ImportError` with install hint when openai absent; `converse()` propagates `ModuleNotFoundError` unmodified
- GH-92: replace `MagicMock` / `AsyncMock` with real in-memory fakes in `test_scheduler.py` (`types.SimpleNamespace`), `test_a2ui_group_d.py` (`_StubContentModel` concrete subclass), `test_azure_commitment_store.py` (`_FakeTableClient` dict-backed ETag-aware fake); zero `unittest.mock` usage remaining in those files

## [0.5.34] — 2026-06-22

### ✅ Features
- GH-91: `_validate_emits` (SC-F1) now accepts `AsyncIterator[T]` and `AsyncGenerator[T, None]` return annotations on async-generator tools with `emits=T`; wrong yield type raises `ValueError` with a clear message at boot. (`agent_sdk/app.py`)

### 🔧 Fixes
- GH-90: harness A2A multi-turn driver now continues via `contextId` (not `taskId`) when the prior turn's task was completed; `taskId` reuse is correctly gated to `input-required` / `auth-required` continuations only. Eliminates false `transport-divergence` failures on multi-turn `/acceptance` runs. (`harness/workflows/acceptance-api.js`, `harness/skills/acceptance/SKILL.md`)

### 🧪 Test / CI
- `tests/test_gh91_generator_emits_validation.py` — 4 cases: `AsyncIterator[T]` passes, `AsyncGenerator[T, None]` passes, wrong type raises, no annotation passes

## [0.5.31] — 2026-06-21

### ✅ Features
- GH-88: async-generator tool contract — `@tools.tool` now accepts `AsyncGenerator` functions; tools may `yield ToolProgressEvent(...)` for interim progress and `return` their terminal artifact. Backward-compatible: existing coroutine tools unchanged. (`agent_sdk/agent/registry.py`, `loop.py`, `events.py`)
- GH-87: first-class long-running / deferred-task delivery — a tool can return `DeferredResult(handle)` to register a background job; the A2A task stays `WORKING` and streams `TaskStatusUpdateEvent{state:"working"}` until the handle resolves, then delivers the artifact and transitions to `COMPLETED`; timeout → `FAILED`. New `agent_sdk/agent/deferred.py`. (`agent_sdk/agent/loop.py`, `runner.py`, `registry.py`, `routes/a2a.py`)
- GH-87: `@tool(long_running=True, tool_timeout_override=N)` decorator kwargs — per-tool timeout override independent of global `TIER_TIMEOUTS`.

### 🔧 Fixes
- GH-89: `harness/workflows/acceptance-api.js` — `require('crypto').randomUUID()` replaced with caller-provided `args.runId` (minted in the skill where `require` is available); `/acceptance` gate is now functional on all agents.
- GH-88: `ToolProgressEvent` wired to AG-UI `CUSTOM{name:"TOOL_PROGRESS"}` and A2A `TaskStatusUpdateEvent{state:"working",final:false}` so long-running tools emit visible progress on both transports.

### 🧪 Test / CI
- `tests/test_gh88_tool_interim_emit.py` — async-generator tool interim-emit coverage
- `tests/test_gh87_deferred_task.py` — deferred-task resolve, timeout, and working-state coverage

## [0.5.28] — 2026-06-21

### ⚠️ Breaking changes
- acd28c9 feat(w024/GH-86): `build_app()` now raises `ValueError` at boot in production (`DEV_MODE=false`) when `AGENT_NAME` is unset or set to the reserved placeholder `"agent"`. Previously such agents booted with the degraded `"agent"` identity. **Migration:** production agents must set `AGENT_NAME` to a non-placeholder value or `build_app()` now fails; set `DEV_MODE=true` to retain the prior warn-only behavior. Note: `"agent"` (case-insensitive) is permanently reserved as the unset sentinel — choose any other name.

### 🔧 Fixes
- 6aa8431 fix(w024/GH-86): card `description` now falls back to `display_name` sentinel when blank, never emits `""` (A2A §3.1 compliance, LRN-101)
- 9c8e8d4 fix(azure-dev): warn at boot when `AZURE_STORAGE_ACCOUNT_NAME` set without connection string in DEV_MODE

### 📖 Docs
- 6798bbb docs(harness): add no-mock rule for SDK tests in `tests/`

## [0.5.24] — 2026-06-20

### 🟡 Protocol surface changes
- eb303e5 feat(w023): TaskStatus.error extension declared with `https://` URI in agent card (GH-78)
- eb303e5 feat(w023): credential-forwarding extension URI corrected to `https://` scheme (GH-79)
- 2f5786b feat(w022): AG-UI transport made fail-closed — A2UI_UPDATE suppressed unless client sends `forwardedProps.a2uiClientCapabilities` (GH-74)
- 2f5786b feat(w022): MCP absent-header behaviour: Streamable HTTP 400s on absent `Mcp-Protocol-Version`; legacy SSE exempted per spec §10 SHOULD (GH-77)
- 2f5786b feat(w022): `POST /v1/tasks/{id}:subscribe` route confirmed correct per A2A v0.3.0 §2 binding table (GH-75, LRN-099)
- 2f5786b feat(w022): `urn:agui:run:v1` extension URI corrected to `https://agent-sdk.dev/extensions/ag-ui-run/v1` (GH-85, LRN-097)
- 6f5af70 fix(w022-redteam3): agent card now uses `registry.tier1()` — Tier-2 (A2A-only) tools no longer appear in card `skills` section (LRN-094)
- bbfe353 fix(w022-redteam): `ag_ui_run` Content-Type 415 guard added; reject present non-JSON body before SSE stream opens (LRN-093 parity)

### ✅ Features
- eb303e5 feat(w023): `agent_sdk.contrib.Scheduler` — `@cron(interval_seconds)` decorator + `sched.lifespan` context manager for background jobs; `agent_sdk.scheduler` stub raises `ImportError` with migration guide (GH-81)
- eb303e5 feat(w023): `/acceptance` skill wired to named workflow via `scriptPath` form (GH-83 workaround, LRN-096)
- 2f5786b feat(w022): `A2uiCapabilities.for_custom_emit()` — per-transport A2UI capability resolver; `ag_ui.py` uses it to gate `A2UI_UPDATE` emission
- 2f5786b feat(w022): `urn:agui:run:v1` → `https://` extension added to `capabilities.extensions` (GH-73)
- 2f5786b feat(w022): `A2UI_UPDATE` valueSchema `messages.items.type='object'` added (GH-76)
- 2f5786b feat(w022): `TaskStore.list_tasks_for_identity` returns `tuple[list[Task], str|None, int]`; third element is total match count for correct `totalSize` in `GET /v1/tasks` (GH-75)

### 🔧 Fixes
- eb303e5 feat(w023): wave-cycle archive gate extended to cover `tests/`, `workspace/learning/`, `workspace/scenarios/results/`, `workspace/prd/` paths via `offendingHarnessPaths` (GH-84)
- f08214c fix(GH-83): acceptance skill `scriptPath` resolution hardened
- f5249d8 fix(GH-84): archive null guard + commit gate hardened
- 2f5786b feat(w022): `_create_task_record`/`_resume_or_error` archive `model_copy` of inbound `Message` — eliminates `contextId` mutation side-effect (LRN-048)
- bbfe353 fix(w022-redteam): reference binding tables, `docs/protocols.md`, `DESIGN.md` corrected to `POST /v1/tasks/{id}:subscribe` (was `:resubscribe`)
- bbfe353 fix(w022-redteam): `agent_sdk/routes/mcp.py` module docstring corrected to document Streamable vs legacy SSE absent-header divergence

### 🧪 Test / CI
- 993e2c5 fix(w023-redteam4): LRN frontmatter consistency guard test added; 8 id mismatches corrected
- 6f5af70 fix(w022-redteam3): `test_card_mcp_surface_parity.py` — live card vs MCP `tools/list` parity test
- 2f5786b feat(w022): tests for GH-73/74/75/76/77 (ag-ui caps, card extensions, MCP version gate, route, schema)

### — Other
- 986894a docs(w023): LRN-096/097/098 codified — named-workflow args drop, extension URI scheme, scheduler pattern
- 25bb71a chore(w022): plan.md updated; w020b + w022 archived

## [0.5.19] — 2026-06-19

### ✅ Features

- **loop: `max_output_tokens` configurable via `LoopPolicies` (GH-73)** —
  `LoopPolicies` gains `max_output_tokens: int = 8192` (`DEFAULT_MAX_OUTPUT_TOKENS`).
  Every `model.converse()` call now forwards `max_tokens=policies.max_output_tokens`,
  preventing silent model-side truncation on long completions. Default 8 192 matches
  Bedrock Converse defaults; callers can override at `Agent` construction.

### 🔧 Fixes

- **harness/acceptance-api.js: A2A transport four-bug fix (GH-71)** —
  1. URL corrected to `POST /v1/message:stream` (colon path, not `/v1/message/stream`).
  2. JSON-RPC envelope removed — the HTTP+JSON binding takes a flat `MessageSendParams`
     body, not a `{jsonrpc,method,id,params}` wrapper.
  3. `messageId` added to every outgoing message (A2A v0.3.0 §4.1 MUST).
  4. SSE event parsing switched to `ev["kind"]` (`"task"` / `"status-update"` /
     `"artifact-update"`) — the A2A HTTP+JSON binding emits kind-discriminated objects,
     not JSON-RPC method frames. `taskId` now harvested from the first `kind == "task"`
     frame (authoritative) before the `status-update` fallback.

- **sdk/agent: Bedrock credentials from credential store (GH-72)** —
  `BedrockModelClient.__init__` accepts four kwargs: `bearer_token`,
  `aws_access_key_id`, `aws_secret_access_key`, and `aws_session_token`.
  `Agent._build_model_client()` resolves all four from `NS_BEDROCK` in the
  encrypted credential store and forwards them; none are read from `os.environ`
  (SI-6). `aws_session_token` is forwarded alongside the access/secret pair only
  when present — it is required for STS / temporary credentials; long-lived IAM
  keys omit it. Absence of all four falls through to the boto3 default chain
  (env vars / instance-profile IAM). Thread-safe double-checked locking added to
  `_boto_client()`. (Targeted 0.5.18; shipped under 0.5.19.)

- **sdk/build: `-> None` return annotation no longer skips emits mismatch check (RT-002)** —
  `inspect.get_annotations` collapses an explicit `-> None` and a missing annotation
  to the same Python `None`. `app.py` now checks `fn.__annotations__` directly:
  the emits/return-type validation is skipped only when `"return"` is absent from
  `__annotations__`; an explicit `-> None` with a non-`None` `emits=` now raises
  `ValueError` as intended.

- **sdk/a2a: unknown-route 404 now emits -32603 not -32001 (RT-003)** —
  `_A2A_CODE` previously mapped `404 → -32001` (TaskNotFound), mislabelling every
  unrouted `/v1/` hit. The `404` entry is removed; the `.get(status, -32603)` fallback
  applies instead. `-32001` is still raised explicitly by task routes when a task is
  absent. `test_a2a_error_envelope.py::test_unknown_v1_route_404_a2a_envelope` tightened
  to assert exactly `-32603`.

### 🧪 Test / CI

- `tests/test_gh71_acceptance_api_stream.py` — four AC tests covering the corrected
  A2A streaming path: colon URL, flat body, `messageId` presence, `kind`-based SSE
  event parsing.
- `tests/test_bedrock_credential_store.py` — credential-store injection tests for
  `BedrockModelClient` (`bearer_token`, IAM static keys, default-chain fallback).
- `tests/test_emits_return_type.py` — case (h): explicit `-> None` with `emits=` raises
  `ValueError` (was silently skipped).
- `tests/test_a2a_error_envelope.py` — `test_unknown_v1_route_404_a2a_envelope` now
  asserts `error.code == -32603` exactly.

---

## [0.5.17] — 2026-06-19

### ✅ Features

- **harness/skills: standardise on `uv sync --frozen` + `uv.lock` across upgrade, setup, new-agent (GH-70)** —
  `harness/skills/upgrade/SKILL.md` now runs `uv lock` after every SHA bump and uses
  `uv sync --frozen --extra dev` for the reinstall; `harness/skills/setup/SKILL.md`
  generates `uv.lock` in Phase 2 and uses `uv sync --frozen` for the first install;
  `harness/skills/new-agent/SKILL.md` adds a `uv lock` generation step before the
  first install. All three skills now commit `uv.lock` alongside `pyproject.toml`.
  `template/Dockerfile` updated in `wailuen/a2a-agent-template` — uses
  `uv sync --frozen` with uv from `ghcr.io/astral-sh/uv:latest`.

### 🔧 Fixes

- **harness: two wave-cycle.js copies reconciled into byte-identical superset** —
  `.claude/workflows/wave-cycle.js` was a stale fork missing every fail-closed null-gate
  hardening that `harness/workflows/wave-cycle.js` carried. The copies are now unified;
  `tests/test_workflow_sync.py` asserts byte-identity to prevent future drift.

### 🧪 Test / CI

- **tests: `test_learning_index.py` guards LRN file ↔ index consistency** —
  Any LRN file written to `workspace/learning/` without a corresponding index row in
  `README.md` is now caught by CI (the redteam learning-check loop would otherwise
  miss it).
- 1600572 chore: track uv.lock — resolves RT-004 ambiguous lockfile

## [0.5.16] — 2026-06-18

### 🟠 Security

- **harness: ADR credential gitignore globs were entirely absent (GH-66)** —
  `harness/.gitignore` did not exist; neither `workspace/adr/ADR-000-*-credentials.md`
  nor `workspace/adr/ADR-001-*-credentials.md` was gitignored anywhere, despite
  `CLAUDE.md` asserting both are protected. Created `harness/.gitignore` with both
  globs so `/provision`-written credential inventory files are never accidentally committed.

### ✅ Features

- **sdk/models: `metadata` escape hatch on all ContentModel profile types (GH-63)** —
  Added `metadata: dict[str, Any] | None = None` to the 13 `ContentModel` subclasses
  that previously lacked it (`KpiCard`, `ComparisonTable`, `BarChart`, `EntityList`,
  `MarketBriefing`, `WaterfallChart`, `MultiCategoryChart`, `FundPerformance`,
  `EmailList`, `CalendarEvents`, `UserProfile`, `UserList`, `DocumentList`), matching
  the existing pattern on `TimeSeriesChart` and `CategoryValue`. Domain code can now
  pass disclosure annotations (e.g. `coverage_note`) via `metadata={"coverage_note":
  "Partial: 5 of 20 funds"}` without silent field loss. `extra='ignore'` preserved
  for backward compatibility.

### 🔧 Fixes

- **harness/skill: `/provision` now probes Storage Table Data Contributor RBAC before writing `.env` (GH-60)** —
  Phase 1b runs `az storage table list --auth-mode login` after collecting the account
  name. A 403 halts with the exact `az role assignment create` fix command; success
  prints "RBAC confirmed". Degrades gracefully when `az` is unauthenticated.

- **sdk/build: `AzureTableCredentialStore` error message now mentions `pyproject.toml` (GH-62)** —
  `_INSTALL_HINT` in `azure_utils.py` updated to include the `pyproject.toml`
  dependency form alongside the bare `pip install` form.

### 🧪 Test / CI

- `tests/test_content_types.py` — metadata round-trip tests for `GH-63`.

### — Other

- **harness/workflow: `acceptance-api.js` now uses `require('crypto').randomUUID()` (GH-58)** —
  Replaces `globalThis.crypto.randomUUID()` (Node 19+ only) with the Node 15.6+
  compatible form. Fixes `TypeError` on Node 18 LTS CI hosts.

- **harness/workflow: `sdk-wave.js` redteam prompts now include Dimension 5 (GH-65)** —
  Both unit and phase redteam prompts explicitly require checking for stubs, TODOs,
  and unmet ACs — matching `wave-cycle.js`'s "Run all 8 dimensions" instruction.

---

## [0.5.15] — 2026-06-18

### 🔧 Fixes

- **a2ui/ag-ui: domain catalog types now always emitted when tier ≠ "none" (GH-56)** —
  `A2uiCapabilities.allows()` previously gated domain `ContentModel` types on catalog
  membership (`model_cls.catalog_id in self.catalogs`), silently suppressing `A2UI_UPDATE`
  for consumers that omit `forwardedProps.a2uiClientCapabilities.catalogs`. This inverted
  the AG-UI spec contract (consumers silently ignore unknown CUSTOM events; servers emit
  freely). Fixed by removing the catalog-membership gate: domain types are now emitted
  whenever `tier != "none"`. Tier gating within the standard catalog (core vs extended)
  is unaffected. The `catalogs` list remains available for informational purposes.

### 🧪 Test / CI

- New tests in `tests/test_a2ui_group_d.py` and `tests/test_protocol_fixes_w6.py`
  verifying domain catalog emission with standard-only capabilities, and tier=="none"
  suppression regression guard.

---

## [0.5.14] — 2026-06-17

### 🟡 Protocol surface changes

- **a2a: terminal taskId now returns -32004 instead of creating a new task (GH-51)** —
  Removed `_continue_from_terminal()` which violated A2A v0.3.0 §6 item 14. A
  `message/send` or `message/stream` targeting a terminal `taskId` now returns
  `-32004 UnsupportedOperation` (send) or `-32001 TaskNotFound` (stream), never
  a silent new task. Spec-correct multi-turn continuation uses `contextId` only
  (no `taskId`): `_create_task_record()` calls `TaskStore.context_messages()` to
  carry prior conversation history into the new task.

- **a2a: `TaskStore.context_messages()` — contextId continuation API** —
  New method on `TaskStore` ABC (default `[]`) and `InMemoryTaskStore`
  implementation. Scans terminal tasks by `contextId` + `identity`, returns the
  most recent task's `messages` list for model-context prepopulation. Identity
  isolation enforced: different users cannot inherit each other's history on the
  same `contextId`.

### 🔧 Fixes

- **mcp: `ToolEntry.input_schema()` now always emits `required: []` + `additionalProperties: false` (GH-47)** —
  No-model branch returns a fully closed schema; Pydantic branch post-processes
  with `schema.setdefault("additionalProperties", False)` and
  `schema.setdefault("required", [])` so existing `required` arrays are preserved
  but empty schemas are closed. Fixes MCP `tools/list` responses that previously
  omitted these fields.

### 🧪 Test / CI

- `tests/test_w017_gh51_multiturn.py` — new test module covering contextId
  continuation (inherits prior history), stream continuation, fresh context (no
  prior history), terminal-taskId rejection (-32004), stream-terminal rejection
  (-32001), interrupt resume, and per-identity isolation.
- `tests/test_w017_gh47_input_schema.py` — new test module covering no-model
  closed schema, all-optional model schema, required-fields preservation, and
  MCP `tools/list` integration.

---

## [0.5.13] — 2026-06-17

### 🟡 Protocol surface changes

- **a2a: JSON parse errors return -32700, not -32602 (GH-45)** —
  `_parse_send()` now calls the new `a2a_parse_error()` helper
  (`common/wire_errors.py`) for unparseable request bodies, matching JSON-RPC
  2.0 §5 (Parse Error). -32602 (Invalid Params) remains reserved for valid JSON
  that fails `MessageSendParams` validation.

- **a2a: A2UI DataParts gated behind X-A2A-Extensions opt-in (GH-50)** —
  `_capabilities()` now reads the `X-A2A-Extensions` request header and only
  enables A2UI DataPart emission when it advertises the A2UI extension URI.
  Absent the header, capabilities resolve to `tier='none'` so no A2UI MIME
  DataPart is emitted — the client must opt in.

- **mcp: openWorldHint=false for tier-1 / read-only tools (GH-52)** —
  `ToolSet.tool()` now emits `annotations.openWorldHint = False` for tools with
  `tier=1` or `read_only=True`, overriding the MCP 2025-06-18 default of `true`
  so pure read-only query tools are no longer misclassified as world-altering.

### 🔧 Fixes

- **loop: tool ValidationError surfaces field/type so the model can self-correct (GH-48)** —
  A targeted `except ValidationError` branch now builds a tool-result error from
  `loc` + a type-derived phrase via `_safe_validation_message`, instead of
  collapsing into the generic `"tool '{name}' failed"`. SI-2: `msg` and `input`
  are never echoed (both can embed the raw rejected value). The error `loc` is
  walked against the tool's `input_model` so only schema-declared field names
  and list indices are echoed — user-supplied dict keys and `extra_forbidden`
  field names are redacted to `<key>`/`<extra>`, closing the residual loc-borne
  input-leak gap.

### 🔨 Harness

- **acceptance-api: per-invocation thread isolation + failureClass + deterministic follow-ups (GH-53, GH-55)** —
  `acceptance-api.js` now suffixes `THREAD_ID` and all `/tmp/acc-{s.id}-*`
  filenames with a per-invocation UUID, eliminating cross-contamination between
  concurrent runs of the same scenario; `SCENARIO_RESULT_SCHEMA.failureClass`
  gains the `harness-contamination` value; and `buildScenarioPrompt` now honours
  a scenario's `followUpTurns` array, injecting pinned follow-up queries verbatim
  on both A2A and AG-UI paths before falling back to auto-generation.

### 📖 Documentation

- **learning: resolve LRN-028 ID collision + reindex README (GH-54)** —
  The duplicate `LRN-028` is renumbered to a free ID, a new LRN codifies the
  acceptance-api `THREAD_ID` contamination risk with a Check clause that greps
  `harness/workflows/acceptance-api.js`, and `workspace/learning/README.md` is
  reindexed to cover the full LRN-018+ range.

## [0.5.12] — 2026-06-17

### 🟡 Protocol surface changes

- **mcp: gate serverInfo.title behind negotiated version 2025-11-25 (GH-43)** —
  `serverInfo.title` is absent when clients negotiate `2025-06-18` or `2025-03-26`;
  it is only included when the negotiated MCP protocol version is `2025-11-25` or later.
  MCP `SUPPORTED_PROTOCOL_VERSIONS` tuple locked to newest-first order via assert.

### ✅ Features

- **harness: tier-based parallel wave execution (ce34027)** —
  `wave-cycle.js` now resolves a `groupDeps` map from the wave file and executes
  todo groups whose dependencies are all complete concurrently within each tier,
  rather than strictly sequentially. Groups with no inter-group deps run in
  the same tier.

- **harness: pre-archive commit-intent guard (GH-40)** —
  Archive phase in `harness/workflows/wave-cycle.js` now runs a `git status --short`
  check before moving the wave file to `completed/`, cross-referencing dirty paths
  against the wave's `Creates:` entries. If any Creates file is uncommitted the
  archive is blocked (fail-closed). `ARCHIVE_INTENT_SCHEMA` is the structured gate.

### 🔧 Fixes

- **fix(content): DocumentList.to_plain_text() renders type and modification date (GH-42)** —
  `DocumentItem.type` and `last_modified` / `modified` date are now included in
  `to_plain_text()` output, matching the full wire contract for `DocumentList`.

### 📖 Documentation

- **docs: document lifespan_extras scheduling entry point (GH-41)** —
  `Agent.__init__` docstring now fully describes the `lifespan_extras` parameter
  with a minimal `asyncio.create_task` example for periodic background tasks.
  DESIGN.md §10.4 (new) identifies `lifespan_extras` as the single scheduling
  entry point and cross-references `commitments_lifespan` and `webhooks_renewal_lifespan`
  as canonical patterns. No new public API surface added.

- **docs: round-3 conformance audit deferred findings recorded in REVIEWS.md** —
  All 10 findings from the v0.5.12 `/agent-stack-check` gate (1 High deferred,
  5 Medium, 4 Low) are acknowledged with rationale. No Critical or blocking items.

## [0.5.9] — 2026-06-16

### ✅ Features

- **f53fd07 harness: adapt template skills into .claude + /debug threshold raised to round 4+** —
  Copied 16 skills and `wave-cycle.js` from `template/.claude/` into the SDK's `.claude/`
  project directory (SDK-adapted variants: `agent_sdk/` paths, SI invariants, sdk-test recovery).
  `/debug` escalation threshold raised from round 3 to round 4+ across `wave-cycle.js`,
  `wave/SKILL.md`, `implement/SKILL.md`, and `debug/SKILL.md` in harness, template, and `.claude/`.

- **14cef76 harness: full sync with template — advisor agents, conformance skills, reference docs** —
  Added 4 advisor agent specs (`a2a-advisor`, `a2ui-advisor`, `ag-ui-advisor`, `mcp-advisor`),
  5 conformance check skills (`a2a-check`, `a2ui-check`, `ag-ui-check`, `mcp-check`,
  `agent-stack-check`), 2 authoring skills (`add-artifact`, `sdk-issue-scan`), 3 protocol
  reference docs, and `.harness-manifest.json` to `harness/`. Template received `new-agent`
  skill and `.claude-plugin`; drifted files (`analyst.md`, `planner.md`, `agent-verify`,
  `upgrade`, `acceptance`) synced from harness as source of truth.

- **b491085 acceptance skill: dual-path A2A + AG-UI testing** —
  `/acceptance` now drives every scenario on both transports concurrently. A2A path uses
  `POST /v1/message/stream` (JSON-RPC SSE, `TaskArtifactUpdateEvent`/`TaskStatusUpdateEvent`);
  AG-UI path uses `POST /run` SSE. Both must score ≥ 7 for `passed=true`. New
  `transport-divergence` failure class. Added `--transport a2a|agui|both` flag.

- **575fa5c acceptance-api workflow: dual-path A2A + AG-UI** —
  Rewrote `acceptance-api.js` from AG-UI-only to dual-path. Schema changed from
  `minScore/turns` to `a2aMinScore/aguiMinScore/a2aTurns/aguiTurns`. A2A leg drives
  `POST /v1/message/stream` with `httpx` streaming and persists `taskId` across turns.
  AG-UI leg uses `ChatDriver.agui_turn()`. Both run per-scenario; summary log shows
  A2A min + AG-UI min + diverged count. `args.transports` wires the `--transport` flag through.

## [0.5.6] — 2026-06-16

### 🟡 Protocol surface changes

- **a2a: GET /v1/tasks — implement tasks/list (GH-32, A2A-D3)** —
  Replaced -32004 stub with real implementation using `store.list_tasks_for_identity`.
  Response matches A2A v0.3.0 `ListTasksResponse` shape:
  `{tasks, totalSize, pageSize, nextPageToken}`. Cursor-based pagination
  with identity isolation (tasks are never visible to other identities).

- **a2a: transport type narrowed to Literal (A2A-D1)** —
  `AgentCard.preferred_transport` and `AgentInterface.transport` now use
  `Literal["JSONRPC","GRPC","HTTP+JSON"]` instead of unconstrained `str`.
  Prevents invalid transport values from passing Pydantic validation.

- **a2a: route name confirmed spec-correct (GH-32 / A2A v0.3.0 §11.3.2)** —
  `POST /v1/tasks/{task_id}:subscribe` retained. `:resubscribe` was never
  implemented. Spec fetch from `a2aproject/A2A` confirmed `:subscribe` is the
  correct HTTP+JSON binding name.

- **mcp: per-surface PRM routing (GH-33)** —
  A2A (`/v1/`) and AG-UI (`/ag-ui/`) surfaces now emit the bare PRM
  (`/.well-known/oauth-protected-resource`) in their `WWW-Authenticate` challenge.
  MCP (`/mcp`) continues to use the path-suffixed form (`…/mcp`). Bare PRM
  endpoint added at `GET /.well-known/oauth-protected-resource`.

- **mcp: AS metadata resource_indicators_supported (GH-35)** —
  `GET /.well-known/oauth-authorization-server` now includes
  `"resource_indicators_supported": true` (RFC 8707 §5).

- **ag-ui: skill tags flow to AgentSkill (GH-34)** —
  `@tool(tags=[...])` values propagate to `AgentSkill.tags` on the agent card.
  Tier label (`tier-N`) moved to `x-sdk.tier` — never appears in `tags`.

- **ag-ui: TaskStatus.error field for failed tasks (GH-38)** —
  Failed tasks now populate `status.error: {code, message}` in the A2A wire.
  `WireError` is set in all failure branches: `DoneEvent(ok=False)`,
  `except AgentError`, and `except Exception`.

- **a2ui: updateComponents upsert-by-id semantics** —
  `a2ui.js` renderer now maintains a `_componentMap` (JS `Map` keyed by
  `component.id`) per surface. `updateComponents` upserts each component
  by id rather than replacing the full list. Fixes stale-component accumulation.

- **a2ui: duplicate createSurface guard** —
  A second `createSurface` for an already-open surface now logs a protocol-error
  warning and skips processing instead of silently overwriting the surface state.

- **a2ui: updateDataModel null-vs-absent semantics** —
  `MISSING` sentinel distinguishes absent `value` (delete the pointer) from
  explicit `null` (set to null). `apply_data_model_update()` on the server
  and the JS `pointerSet` in `a2ui.js` both apply delete-vs-null semantics.

### 🟠 Security

- **config: HTTPS enforcement for public deployment** —
  `_deployment_invariants()` in `config.py` raises `ValueError` at boot if
  `PUBLIC_URL` is non-local and does not start with `https://`. Loopback
  hosts (`localhost`, `127.0.0.1`, `::1`, `0.0.0.0`) are exempt.

### ✅ Features

- **a2ui: SurfaceRegistry duplicate-open tracking** —
  `SurfaceRegistry` class in `translator.py` tracks open surfaceIds and
  emits a `warnings.warn` on duplicate `open()` calls.

- **a2ui: catalog compact schemas + few-shot examples** —
  `catalog.py` injects `_COMPACT_SCHEMAS` and `_FEW_SHOT_EXAMPLES` into the
  system prompt section for `KpiCard`, `TimeSeriesChart`, `ComparisonTable`,
  and `FundPerformance` — giving the LLM concise wire contracts and worked examples.

- **mcp: tool name length check at decoration time** —
  `ToolSet.tool()` now raises `ValueError` immediately if the tool name exceeds
  64 characters (was only checked at `build_app()` time).

- **ag-ui: interrupt expiresAt forwarded to wire** —
  `InterruptEvent.expires_at` field added; populated from `record.interrupt_deadline`
  after `store.mark_interrupted()`; forwarded as `expiresAt` (milliseconds) in the
  AG-UI INTERRUPT event.

- **ag-ui: parentMessageId always present** —
  `TOOL_CALL_START` events always emit `parentMessageId` (as `null` if no prior
  message) — removes the optional-omission ambiguity.

### 🔧 Fixes

- **a2ui: message type guard regression fixed** —
  `a2ui.js` validation guard removed `|| !msg.type || typeof msg.type !== "string"`.
  A2UI messages have no `type` field; the check was always truthy and silently
  skipped every received message. Corrected guard: `version` field only.

- **ag-ui: assistant history content as multimodal array** —
  `chat.js` line ~481: `content: buf.text()` changed to
  `content: [{type:"text", text: buf.text()}]` — matches the multimodal array
  shape used for user turns and required by AG-UI spec.

- **ag-ui: resume status "approved" → "resolved"** —
  Three test files updated from `status: "approved"` to `status: "resolved"`
  with `payload: {decision: "approved"}`. `"resolved"` is the canonical AG-UI
  interrupt-resolution status literal.

- **ag-ui: expires_at falsy guard** —
  `ag_ui.py`: `if event.expires_at:` changed to `if event.expires_at is not None:`
  to avoid suppressing a valid `0.0` deadline.

- **a2ui: paintSurface fallback on missing root** —
  `a2ui.js`: removed `|| entry.components[0]` fallback when no `id:"root"` component
  exists. Now renders a visible `.a2ui-fallback` error node instead of silently
  promoting an arbitrary component.

- **a2ui: MIME dispatch heuristic removed** —
  `chat.js`: removed `|| Array.isArray(part.data)` from the A2UI artifact dispatch
  condition. Dispatch is now by MIME type string only.

- **ag-ui: _fold_history safe text extraction** —
  `ag_ui.py`: `p.get("text", "")` instead of `p["text"]` in `_fold_history`
  prevents `KeyError` on history parts without a `text` key.

### 🧪 Test / CI

- `tests/test_w014_fixes.py` — 7 new tests: subscribe route, resubscribe gone,
  tool tags flow, tags default empty, card skill tags, AS metadata, failed task error
- `tests/test_a2ui_wire.py` — 11 new tests: SurfaceRegistry duplicate warning,
  `apply_data_model_update` null/absent/scope (M2/M3), system prompt schema
- `tests/test_a2a.py` — `test_tasks_list` and `test_tasks_list_isolation` added;
  `test_error_table` updated for `GET /v1/tasks` 200 + `ListTasksResponse` shape
- `tests/test_ag_ui.py`, `tests/test_ag_ui_resume.py` — resume status `"resolved"` + payload
- `tests/test_http_protocol.py` — per-surface PRM routing assertions (C3-H2, C3-H5)
- `docs/protocols.md` — `:subscribe` is spec-correct per A2A v0.3.0 §11.3.2
- `REVIEWS.md` — Round 2 conformance audit log; all Critical/High fixed; 7 deferrals acknowledged

## [0.5.5] — 2026-06-15

### 🟡 Protocol surface changes

- **a2a: correct error code on terminal-task message/send (A2A-F1)** —
  `_resume_or_error` now returns `-32004` (UnsupportedOperation, HTTP 501) when
  `message/send` targets a completed/failed/canceled task. Previously used
  `-32002` (TaskNotCancelable, HTTP 409) which per A2A §2 maps exclusively to
  `tasks/cancel`. Tests updated: `test_a2a.py` GH-16 assertion and
  `test_protocol_fixes_w9_group_a.py` now assert `(501, -32004)`.

### ✅ Features

- **a2ui: system prompt Profile v1 wire-contract injection (A2UI-F1)** —
  `agent_sdk/a2ui/catalog.py` exports `get_system_prompt_section()` returning a
  compact `## A2UI Output Format` block listing every registered FROZEN component
  with its required/optional field types. `app.py` appends this section to the
  system prompt when content types are registered, giving LLMs prompt-level
  guidance on PascalCase component names and field shapes.

### 🔧 Fixes

- **ag-ui: history message content uses canonical multimodal array (AG-UI-F-M-01)** —
  User messages pushed to `aguiMessages` history in `chat.js` now use
  `content: [{type:"text", text}]` (AG-UI multimodal form) instead of
  `content: text` (flat string). `_fold_history` server-side already handled
  both; canonical form eliminates divergence and future-proofs multimodal payloads.

### 🧪 Test / CI

- `tests/test_a2ui_wire.py` — 2 new tests: `get_system_prompt_section()` always
  returns a str; returns non-empty string containing "A2UI" + "KpiCard" when types
  are registered
- `tests/test_a2a_error_envelope.py` — terminal-task `message/send` asserts -32004

## [0.5.4] — 2026-06-15

### 🟡 Protocol surface changes

- **a2a: comprehensive /v1/ HTTP error envelope (GH-25 / A2A-C1/C2/H1)** —
  `_a2a_auth_envelope` now wraps ALL `StarletteHTTPException` on `/v1/` paths
  (not just 401/403). Code map: 401/403→-32000, 404→-32001, 405→-32004,
  415→-32005, others→-32603. Added `RequestValidationError` handler returning
  400 + -32602 with field **locations only** — never echoes submitted values
  (SI-2). `tasks_get` guards against `task_id` containing `:` (returns -32004
  instead of -32001 for route-collision hits).

- **mcp: remove malformed `scope=""` from WWW-Authenticate challenge (GH-27 / MCP-C1)** —
  `_prm_challenge(prm_url)` helper extracted in `middleware.py`; returns
  RFC 6750 §3-conformant `Bearer resource_metadata="{prm_url}"` with no
  empty-scope param. All five challenge sites (middleware, 2× oauth, admin)
  now use the shared helper. Flip-flopping root cause fixed: SC-C3 test
  invariant corrected to assert ABSENCE of `scope=`.

- **ag-ui: TOOL_CALL_ARGS + TOOL_CALL_END consumer handling (GH-31 / AG-UI-C1/C2)** —
  `chat.js` now accumulates `TOOL_CALL_ARGS.delta` fragments per `toolCallId`
  in a `Map` and parses the full JSON only at `TOOL_CALL_END`, with a try/catch
  fallback for partial/malformed JSON.

- **a2ui: MetricItem.trend wire type corrected to string (A2UI-H3)** —
  `@field_serializer("trend")` on `MetricItem` collapses any `KpiTrend` instance
  to its `direction` string before serialization. Profile v1 specifies `trend`
  as `"up"/"down"/"flat"` string only; the object form is now Python-internal only.

- **a2ui: TimeSeriesChart series fields excluded from wire (A2UI-H4)** —
  `TimeSeriesDataPoint.series` and `TimeSeriesChart.series` marked
  `Field(exclude=True)`; both are Python-internal only. Wire output now matches
  the Profile v1 contract: `data:[{date,value,label?}]` only.

### 🟠 Security

- **mcp: Origin validation on /mcp endpoints (MCP-H2)** —
  `mcp_post` and `mcp_get` now validate the `Origin` header against
  `app.state.cors_origins` (MCP spec §10/§12 MUST for DNS-rebinding defense).
  Requests without an `Origin` header (non-browser tools) pass through unchanged.
  `app.state.cors_origins` set at app construction in `app.py`.

- **a2a: 422 validation errors never echo user input (SI-2)** —
  New `_a2a_validation_envelope` handler for `RequestValidationError` on `/v1/`
  returns field **locations** only (never values) in the -32602 message.

### 🔧 Fixes

- **ag-ui: AGENT_ARTIFACT wire payload documented as camelCase (AG-UI-H1 / C2)** —
  `docs/protocols.md` corrected: `AGENT_ARTIFACT.value` fields are `dataType`,
  `toolName`, `data` (camelCase wire) — not snake_case as previously documented.
  `DESIGN.md` updated to match.

- **a2ui: JSON fallback for unknown structured components (GH-28 / A2UI-H1)** —
  `a2ui.js` `paintSurface` now renders unknown components with a non-null object
  value as formatted JSON in a `<pre class="a2ui-json">` block instead of
  discarding structured data via the text-only fallback.

### 🧪 Test / CI

- `tests/test_a2a_error_envelope.py` (new, 7 tests) — 405/422/404 envelope,
  -32602 no-value-echo, task_id colon guard, MCP Origin validation
- `tests/test_http_protocol.py` (new, 7 tests) — WWW-Authenticate exact format
  (no scope=), path-suffixed PRM URL, MCP SSE GET 401, cross-surface consistency
- `tests/test_oauth_flow.py` (new, 7 tests) — token endpoint grant types, DCR
  redirect URI validation, scope omission from token response
- `tests/test_a2ui_wire.py` (new, 13 tests) — KpiTrend string-only wire,
  TimeSeriesChart no-series wire, translate() output structure
- `tests/test_mcp_conformance_w9.py` SC-C3 — flipped to assert `scope=` ABSENT
  (fixing the root cause of repeated GH-27 flip-flopping)
- `tests/test_card_console.py` — routing parity tightened to assert
  `case "TOOL_CALL_ARGS"` and `case "TOOL_CALL_END"` appear in switch body

### — Other

- `ec10fd0` docs: LRN-015/016/017 — MCP coercion failure, SSRF single-predicate, wave gate architecture
- `ab84eb9` chore: v0.5.3 — harness /upgrade pytest path + /agent-verify --no-stack-check clarification

## [0.5.2] — 2026-06-15

### 🔧 Fixes

- **mcp: structuredContent coercion failure now returns isError:True (GH-23)** —
  `_handle_tools_call()` previously swallowed `model_validate` exceptions with
  `except: pass`, returning `isError: False` with no `structuredContent` — a spec
  MUST violation (MCP §4). Now returns `isError: True` with the exception class name;
  attacker-influenced field values are no longer echoed into model context.

### 🔧 Security

- **mcp: SSRF defense — `safe_get()` utility + shared IP-block predicate (GH-24)** —
  Added `agent_sdk/common/http.py` exporting `safe_get(url)` and `_is_non_public_ip()`.
  `safe_get` resolves hostname via async DNS, blocks RFC 1918 / loopback / link-local
  (169.254.x.x IMDS) / reserved / multicast targets, and disables redirect-following.
  The duplicate IP-block logic in `SourceAdapter._on_request` and
  `validate_credential_url` is refactored to call the shared predicate.
  `harness/CLAUDE.md` SI-1 updated to document `safe_get` as the approved escape hatch
  for user-URL fetching outside a `SourceAdapter`.

### 🧪 Test / CI

- `tests/test_w011_mcp_ssrf.py` — 19 new tests: coercion-failure `isError:True`,
  coercion-success `structuredContent` present, `_is_non_public_ip` parametric
  (13 addresses), `safe_get` loopback/IMDS/RFC1918 blocked, public URL passes,
  `follow_redirects=False` enforced.

## [0.5.1] — 2026-06-15

### 🧪 Test / CI

- **wave-cycle.js — pytest gate architecture (GH-19)** — Added `GATE_SCHEMA`
  `{exitCode, passCount, failCount, failures}` and schema-gated gate agents at
  unit-redteam and phase-redteam checkpoints. Gate RED → targeted test-fix
  agent dispatched; `testsRed` flag propagated to return object.

- **wave-cycle.js — post-proto-fix gate (GH-20)** — Added schema-gated gate
  agent between `proto:fix` and `recheck` dispatch so a protocol fix that
  breaks tests is caught before the audit loop continues.

- **wave-cycle.js — implement prompts scoped (GH-21)** — Implement agents now
  run only scoped tests (`pytest -q tests/test_<specific>.py`) during
  implementation; the centralized gate catches suite-wide regressions.
  Full-suite runs during implementation were driving unnecessary memory pressure.

- **wave-cycle.js — pre-archive gate (GH-22)** — Schema-gated gate agent runs
  at the top of the Archive phase. Suite RED blocks archive and re-run is
  required, preventing red-suite commits from reaching the learning store.

## [0.5.0] — 2026-06-15

### 🟡 Protocol surface changes

- **A2A — bare-Message sync-reply path** — `message/send` now supports an optional
  `sync_reply` hook on `Agent`. When registered, the hook is called before task creation;
  returning a non-`None` string skips the task and returns a bare `Message` directly
  (A2A v0.3.0 §2 quick-response pattern). Closes GH-SC-A1.

- **A2A — Content-Type guard → -32005 / HTTP 415** — `_parse_send()` now inspects
  `Content-Type` before attempting `json.loads`. A non-`application/json` body returns
  `-32005 ContentTypeNotSupported` at HTTP 415 instead of the previous `-32602 /
  HTTP 400`. Closes GH-15.

- **A2A — terminal-task re-message returns -32002 / HTTP 409** — `_resume_or_error()`
  now distinguishes "task not found" (`-32001` / 404) from "task is terminal"
  (`-32002 TaskNotCancelable` / 409). Closes GH-16.

- **AG-UI — TOOL_CALL_ARGS injected on resume** — the synthetic interrupt-resume
  tool-call sequence now emits `TOOL_CALL_START → TOOL_CALL_ARGS(delta="{}") →
  TOOL_CALL_END` satisfying the ≥1 ARGS requirement for strict consumers. Closes GH-14.

- **AG-UI — `_fold_history` ContentPart extraction** — `content` arrays in
  `messages[].content` are now extracted as `"".join(p["text"] for p in parts)` instead
  of `str(content)`. Fixes garbled input for CopilotKit-style frontends. Closes GH-17.

- **AG-UI — SSE heartbeat** — `sub.get()` is now wrapped in
  `asyncio.wait_for(timeout=15.0)`; a `TimeoutError` emits an SSE comment keepalive
  (`": ping"`) and resumes waiting. Keeps long idle runs alive across proxies.

- **MCP — `tools/list` cursor pagination** — `_handle_tools_list` now returns
  `nextCursor` (base64-encoded int offset) and accepts `cursor` in the request.
  PAGE_SIZE = 64. Agents with ≥65 Tier-1 tools now paginate correctly per MCP §3.

- **MCP — `structuredContent` for non-BaseModel artifacts** — when `emits=` is
  declared but the artifact is not already a `BaseModel`, the route attempts
  `entry.decl.emits.model_validate(artifact)` before the `structuredContent` gate.
  Dicts from tool returns that match the `emits` schema now produce `structuredContent`.

- **MCP — tool name ≤64 chars enforced at registration** — `registry.py` raises
  `ValueError` if a tool name exceeds 64 characters, catching MCP spec violations
  at boot rather than at `tools/list` time.

- **A2UI — pre-wire assertion** — `_validate_a2ui_wire()` asserts the message list
  is non-empty and every message carries a `version` key before delivery. Bad tool
  returns now surface as agent errors rather than silent partial updates.

- **A2UI — `a2ui_allowed_components` setting** — `BaseAgentSettings` gains
  `a2ui_allowed_components: list[str] | None`. When set, `build_app()` validates
  that all registered content types are in the allow-list.

- **A2A — scalar artifact DataPart** — `build_artifact()` for plain scalar results
  (non-ContentModel, non-mapping) now emits both a `TextPart` and a
  `DataPart(kind="data", data={"value": payload}, metadata={"mimeType": "application/json"})`.

- **A2A — `/v1/card` requires identity** — `extended_card()` now carries
  `Depends(require_identity)`, enforcing authentication before exposing extended
  card fields.

### ✅ Features

- **`ChatDriver.resume()`** — new method to continue an interrupted task by
  `taskId` + `contextId`, sending back the user's reply after an `input-required`
  interrupt. Implements D7.8 of the A2A consumer spec.

- **`ChatDriver` credentials forwarding** — `ChatDriver.__init__` now accepts a
  `credentials: dict[str, str]` kwarg; entries are merged into every request header,
  enabling per-call credential injection for the A2UI extension and other custom
  headers.

- **`ChatDriver` agent.json fallback** — card discovery now falls back from
  `/.well-known/agent-card.json` to `/.well-known/agent.json` on 404, matching the
  server's legacy alias route.

- **`ChatDriver` `additionalInterfaces` transport selection** — when
  `preferredTransport` is unsupported, `a2a_turn()` walks `additionalInterfaces` to
  find a supported transport instead of failing immediately.

- **`A2AError` class constants** — `A2AError` now exposes named class-level
  constants for all 7 A2A error codes (`TASK_NOT_FOUND`, `TASK_NOT_CANCELABLE`,
  `PUSH_NOT_SUPPORTED`, `UNSUPPORTED_OPERATION`, `CONTENT_TYPE_NOT_SUPPORTED`,
  `INVALID_AGENT_RESPONSE`, `NOT_AUTHORIZED`).

- **`/provision` skill** — interactive credential-store interview for a new agent:
  bootstraps admin API key, seeds model backend keys, and writes
  `workspace/adr/ADR-001-<env>-credentials.md`. Targets Azure Table Storage
  as the primary store.

- **Credential ADR discipline** — a `PostToolUse` hook in `.claude/settings.json`
  fires after every admin credential write and prompts updating `ADR-001`.
  `/provision` Phase 3 auto-writes the inventory file.

- **`harness/CLAUDE.md` template** — agent-facing harness conventions file seeded
  into downstream agent `.claude/CLAUDE.md` at `/new-agent` time.

### 🔧 Fixes

- **Azure Table Storage enforced as primary store** — `build_app()` now emits a
  `WARNING` at boot when the credential store falls back to SQLite outside
  `DEV_MODE`. The admin console boot-check route surfaces this warning.

- **`Agent.close()` hardened** — `close()` guards every sub-close call against
  `AttributeError` and `Exception`, preventing partial-init teardown from masking
  the original exception.

- **MCP `WWW-Authenticate` `scope=""` removed** — the Bearer challenge at
  `middleware.py:65` no longer appends `, scope=""` when no scopes are enforced,
  per RFC 6750 §3.

- **GH-18: `pytest -q tests/` → `pytest -q` in wave-cycle.js** — all 5 agent
  prompt templates in `harness/workflows/wave-cycle.js` that passed an explicit
  `tests/` path to pytest now use bare `pytest -q`, respecting `addopts` ignores
  from `pyproject.toml`. Closes GH-18.

### 🧪 Test / CI

- **Zero-tolerance mypy + warnings gate** — `mypy` and `filterwarnings = ["error"]`
  are both hard gates in `/sdk-test`; any new type error or deprecation warning
  blocks release.

- **`/sdk-test` Leg 3 — static conformance at release** — protocol conformance is
  now gated once at SDK release (via `/agent-stack-check` on the SDK source) rather
  than per downstream agent upgrade. `/upgrade` runs `--no-stack-check`.

- **`/sdk-release` is the only commit+push path** — wave completion stages changes;
  `/sdk-release` is the only flow that commits, tags, and pushes, ensuring the full
  3-leg test gate always runs before any code reaches `origin/main`.

- **5 new test modules** — `test_protocol_fixes_w9_group_a.py`,
  `test_ag_ui_group_b.py`, `test_mcp_conformance_w9.py`,
  `test_a2ui_group_d.py`, `test_emits_return_type.py` — covering the w009 protocol
  fixes. 491 tests total.

---

## [0.4.4] — 2026-06-14

### Fixed

- **OData parameterization in `AzureTableCommitmentStore`** — all OData filter strings
  in `list()`, `claim_due()`, and `reap_stale_firing()` now use named parameters
  (`@partition_key`, `@status`, `@now`, `@cutoff`) with a `parameters=` dict instead
  of string interpolation. The `now` parameter in `claim_due()` was previously
  injectable via its public signature; `status` in `list()` was injectable but
  only internally sourced today. Manual `replace("'", "''")` escaping removed —
  the `azure-data-tables` SDK handles OData escaping client-side.

- **Test hardening** — `test_claim_due_only_returns_due_pending` and
  `test_list_filters_by_*` updated to assert parameterized form;
  `partition_key` parameter presence asserted in filter tests;
  `test_list_odata_escapes_single_quote_in_identity_binding` renamed to
  `test_list_parameterizes_single_quote_in_identity_binding` with updated docstring.

---

## [0.4.3] — 2026-06-14

### Added

- **Tool signature validation at registration** — `ToolSet` now rejects invalid tool
  signatures at decoration time: required keyword-only params that are not `SourceAdapter`
  subclasses, required positional params that are not pydantic `BaseModel` subclasses,
  and `*args`/`**kwargs` all raise `TypeError` immediately.

- **`validate_namespace()` in credential store** — `source_name` values are now validated
  against `^[a-z_][a-z0-9_]{0,63}$` at both `register_source()` and `resolver_for_source()`
  time. Rejects hyphens, uppercase, and digit-leading names before they can reach OData
  filter strings.

### Fixed

- **API key fast-reject on format mismatch** — `ApiKeyStore.verify()` now uses
  `^ak_([0-9a-f]{16})_[A-Za-z0-9_-]+$` regex; tokens that don't match the format
  return `None` immediately without scanning the credential store. Eliminates the
  timing oracle between "wrong format" and "key not found."

- **OData injection in `AzureTableCredentialStore.list_fields()`** — switched from
  string-interpolated `PartitionKey eq '{namespace}'` to parameterized
  `PartitionKey eq @partition_key` with `parameters={"partition_key": namespace}`.

- **Test mock hardened** — `_query_entities` in `test_azure_credential_store.py` now
  raises `AssertionError` if called without a `parameters` dict, making any future
  regression back to string interpolation loudly visible.

---

## [0.4.2] — 2026-06-14

### Fixed

- **A2A `:subscribe` path** — `POST /v1/tasks/{id}:subscribe` is the spec-correct
  HTTP+JSON binding (A2A spec §11.3.2). Route confirmed as `:subscribe`; a stale
  `:resubscribe` alias was removed so only the spec-correct path is registered.

- **Bootstrap 401 carries `WWW-Authenticate`** — `admin.py` bootstrap-path rejection
  (invalid/expired token) now includes `Bearer resource_metadata="..."` in
  `WWW-Authenticate`, completing the P6-03 (`resource_metadata` on all 401s) fix.

- **AG-UI resume: synthetic `TOOL_CALL_START/END` before orphan `TOOL_CALL_RESULT`**
  — on interrupt-resume runs, `TOOL_CALL_RESULT` was emitted into the new SSE stream
  with no preceding lifecycle events (those occurred in the prior interrupted stream).
  `_RunMapper` now tracks `_seen_starts` and injects synthetic `TOOL_CALL_START` +
  `TOOL_CALL_END` before any `TOOL_CALL_RESULT` whose START was not emitted in the
  current stream.

- **`ChatDriver.agui_turn` handles `RUN_FINISHED` interrupt outcome** — the event loop
  now has a `RUN_FINISHED` branch: when `outcome.type == "interrupt"`, the `"interrupt"`
  emit key fires with the first interrupt object; the loop always breaks on `RUN_FINISHED`
  regardless of outcome type.

- **`build_artifact` docstring** — corrected to describe the post-P6-02 dual-part
  contract (TextPart + DataPart always; no "TextPart only" path for ContentModel).

### Changed

- **`/redteam` skill** (`harness/` and `template/`) — added pre-release scope rule
  (LRN-002): full-scope run mandatory at release gate; wave-scoped run only covers
  changed code and is not sufficient.

- **`workspace/learning/LRN-006`** — Check section rewritten with correct
  `A2uiCapabilities` construction (no non-existent `.a2ui_enabled` attribute).

---

## [0.4.1] — 2026-06-14

### Fixed

- **MCP `Mcp-Protocol-Version` response header on `initialize`** (GH #4) — header now reflects the
  version negotiated in the body (e.g. `2025-06-18`), not the request-header fallback default
  (`2025-03-26`). Root cause: `_negotiated_version()` in `routes/mcp.py` read the *request* header
  (absent on first contact) and the result was locked into `base_headers` before dispatch.
  Fix: after `_handle_initialize` resolves `protocolVersion`, override the response header to match.

- **`x-agui.customEvents` schema** (GH #5) — entries are now `{name, valueSchema}` objects instead
  of a flat `string[]`. AG-UI CUSTOM event conformance requires `valueSchema` on each entry.

- **`ContentModel` artifacts always emit `DataPart`** (GH #6) — `build_artifact()` previously only
  appended a `DataPart` when the A2UI extension was activated by the client. Plain A2A clients now
  receive a raw `DataPart` (model dump) alongside the `TextPart`, satisfying A2A §D3.

- **`WWW-Authenticate` carries `resource_metadata` on all 401 responses** (GH #7) — auth middleware
  previously added `resource_metadata` only for `/mcp` paths; all other protected routes (A2A,
  AG-UI, admin) returned bare `Bearer realm="agent"`, breaking RFC 9728 OAuth discovery for
  non-MCP clients.

- **`Access-Control-Expose-Headers` in CORS preflight 204** (GH #8) — the OPTIONS preflight
  response now includes `Access-Control-Expose-Headers: WWW-Authenticate, Mcp-Session-Id,
  X-A2A-Extensions`, matching the non-preflight path. Previously absent, which silently blocked
  some user-agents from reading the `WWW-Authenticate` header.

### Added

- **`python -m agent_sdk bump-patch`** — increments the patch segment of the SDK version in
  `pyproject.toml` (e.g. `0.4.1 → 0.4.2`). Used by the `.githooks/pre-push` hook and wave
  commit workflow to keep the version monotonically increasing.

- **`.githooks/pre-push`** — git hook that auto-bumps the patch version and commits the change
  before every push to `main`. Activate with `git config core.hooksPath .githooks`.

- **`workspace/learning/` LRN-001–LRN-006** — codified learnings from GH #4–#8: HTTP wire-level
  test coverage, pre-release full-scope redteam requirement, `resource_metadata` uniformity,
  CORS preflight expose-headers, MCP version header/body sync, ContentModel DataPart invariant.

- **`tests/test_protocol_wire.py`** — HTTP wire-level tests for all five protocol surfaces
  (CORS, auth challenge format, MCP version negotiation, agent card shape, ContentModel artifact
  parts). Complements `test_protocol_fixes_w6.py` (9 unit-level regression tests).

- **Acceptance skill mandatory `/agent-stack-check` gate** — both `harness/skills/acceptance/SKILL.md`
  and `template/.claude/skills/acceptance/SKILL.md` now mandate a full-scope `/agent-stack-check`
  pass before acceptance can be marked complete, even when the wave did not touch protocol surfaces.

---

## [0.4.0] — 2026-06-14

### Added

- **Azure Table Storage persistence backends** — `AzureTableCredentialStore`,
  `AzureTableCommitmentStore`, `AzureTableSubscriptionStore` replace SQLite for multi-replica
  Azure Container Apps deployments. Auto-detected from `AZURE_STORAGE_CONNECTION_STRING`
  (connection string) or `AZURE_STORAGE_ACCOUNT_NAME` (managed identity). AES-256-GCM
  encryption envelope preserved end-to-end. ETag optimistic concurrency preserves
  at-most-once commitment firing across replicas. Install with `pip install agent-sdk[azure]`.

- **`migrate-store` CLI** — `python -m agent_sdk migrate-store [--data-dir ./data]
  [--dry-run] [--force]` migrates existing SQLite credential, commitment, and subscription
  data to Azure Table Storage.

- **`NS_MODEL` namespace + model-backend credential store** — LLM API keys
  (OpenAI, Azure OpenAI, Anthropic) are now stored in the encrypted credential
  store under the reserved `__model__` namespace, never in `.env`. The admin
  console gains a "Model Backend" section (`GET/PUT /admin/api/credentials/__model__/*`)
  with fields for `openai_api_key`, `azure_openai_api_key`, and `anthropic_api_key`.
  `NS_MODEL` exported from `agent_sdk`.

- **OpenAI / Azure OpenAI as built-in model backends** — set `OPENAI_MODEL`
  (or `AZURE_OPENAI_ENDPOINT` + `AZURE_OPENAI_DEPLOYMENT`) in `.env` (non-secret
  operational vars) and seed the API key once via `/admin → Model Backend`. No
  `model_client=` plumbing in `main.py` required; `Agent.build_app()` resolves
  the key from the credential store automatically.

### Changed

- **`BaseAgentSettings`** — gains three new optional fields for Azure Storage auto-detection:
  `AZURE_STORAGE_CONNECTION_STRING` (`SecretStr | None`), `AZURE_STORAGE_ACCOUNT_NAME`
  (`str | None`), `AZURE_STORAGE_TABLE_PREFIX` (`str`, default `"agent"`). Also gains five
  non-secret fields for OpenAI/Azure backends: `OPENAI_MODEL`, `OPENAI_BASE_URL`,
  `AZURE_OPENAI_ENDPOINT`, `AZURE_API_VERSION`, `AZURE_OPENAI_DEPLOYMENT`. Removed
  guidance to put API keys in `.env` via `SecretStr` subclass fields — that is now an
  SI-6 violation.
- **`Agent._build_model_client()`** — accepts `credential_store` and resolves OpenAI
  key from `__model__/openai_api_key` (or `azure_openai_api_key`) automatically.
  Bedrock path unchanged.

---

## [0.3.0] — 2026-06-13

### Changed

- **Credential store clarity** — `SourceAdapter.credential()` docstring now
  explains the full lifecycle (admin console → encrypted store → decrypt on
  call). `BaseAgentSettings` comments clarify that `MASTER_KEY` encrypts the
  store (not an upstream API key) and that Bedrock uses IAM (no key in `.env`).
  `.env.example` gains a prominent box listing what belongs and what does not.
  `CLAUDE.md` credential model table adds a "How to access it" column plus
  four labeled anti-pattern examples. SI-4 reference adds a step-by-step
  store lifecycle and common anti-patterns; SI-6 reference lists what does
  belong in `.env` to contrast with upstream keys.

---

## [0.2.0] — 2026-06-13

### Added

- **`ArtifactLoader`** — prompts live in `src/artifacts/*.md` as Jinja2
  templates (StrictUndefined, frontmatter-aware, compiled once at init).
  `Agent` gains `artifacts_dir=` and `artifact_vars=`; `persona=` remains
  supported for backward compat. `ArtifactLoader` exported from
  `agent_sdk`. Template and AlphaGeo example migrated.
  Harness gains `/add-artifact` opt-in migration skill.

- **`/acceptance` skill** — autonomous acceptance gate, the final step in
  the agent development lifecycle (after `/provision` + `/agent-verify`).
  Generates 30+ seed scenario files across 7 dimensions (happy path per
  tool, multi-turn depth, edge cases, A2UI content type coverage, skill
  activation, interrupt/resume, error/degraded upstream), then drives live
  multi-turn AG-UI conversations against the provisioned agent and
  judge-scores every turn 1–10 for content coherency. Self-healing fix
  loop (max 5 rounds) classifies each failure (`code-bug`,
  `content-type-gap`, `persona-gap`, `upstream-issue`, `bad-scenario`),
  dispatches targeted fix agents, restarts the server, and re-tests only
  the failing scenarios — autonomously, without human intervention.
  Does not exit until all scenarios score ≥ 7 or the round budget is
  exhausted. Persona-gap escalations are non-blocking.
  `--ux` path runs the same scenarios sequentially in a single Playwright
  browser session against the admin test console, adding a rendering
  fidelity score (1–10) that exercises the full intended purpose of every
  A2UI Standard Profile component type emitted (click, sort, filter, form
  submit, hover tooltip, deleteSurface lifecycle, console error check).
  Both scores must be ≥ 7 per turn for a UX pass. OBO agents require a
  one-time manual browser login; everything after is autonomous.
  Results written to `workspace/scenarios/results/run-NNN.json` with
  per-scenario score history across runs.

- **`acceptance-api.js` workflow** — parallel fan-out runner invoked by
  `/acceptance`. Each scenario agent drives a 3–5 turn conversation via
  `ChatDriver` over `POST /ag-ui/run` (SSE), persisting message state
  across turns in `/tmp/`, scoring each reply, generating contextual
  follow-ups from the actual agent response, and classifying failures.
  Returns `SCENARIO_RESULT_SCHEMA`-validated structured objects.

- **`/provision --env [dev|prod]`** — new environment flag controls which
  ADR credentials file is written. After minting the first admin API key,
  `/provision` now writes `workspace/adr/ADR-000-<env>-credentials.md`
  (gitignored) so skills like `/acceptance` can authenticate autonomously
  on future runs without re-bootstrapping. On 409 (already bootstrapped),
  checks for an existing ADR-000 before halting. Auto-adds the credentials
  glob to `.gitignore` if absent.

- **`A2AError`** exported from `agent_sdk.testing` — typed exception
  carrying `code` and `message`; raised by `ChatDriver` on A2A error
  responses and interrupt states. Now part of `testing.__all__`.

- **Chat console markdown rendering** — agent replies in the test console
  are rendered as Markdown (bold, italic, inline/fenced code, headings,
  lists, blockquotes). `streamingBubble` re-renders incrementally so
  formatting resolves live while the model is typing, not only at end of
  stream. No external deps; all model output via DOM text nodes (XSS-safe,
  strict CSP compliant).

- **Chat console responsive full-height layout** — transcript and SSE
  trace panels fill the full viewport height with composer pinned at the
  bottom. Responsive breakpoints: ≤900 px single-column stacked panels,
  ≤600 px trace panel hidden.

### Fixed

- **A2A / AG-UI / A2UI / MCP full-stack conformance** — 17 findings from
  `/agent-stack-check` + 8 iterative `/redteam` cycles resolved to zero
  Critical/High across all four protocol layers and six seams:
  - Body size caps (1 MB) on `message/send` and `ag-ui/run` (MCP-consistent).
  - DNS-rebinding guard in `SourceAdapter._on_request`; reads `dev_mode`
    Pydantic attribute (was incorrectly `DEV_MODE` env-var name).
  - SI-7 build-time check: `SourceAdapter.__init__` requires non-empty
    `allowed_hosts` or `_no_http = True` opt-out for non-HTTP adapters.
  - `CommitmentsSource._no_http = True` to pass the SI-7 check.
  - Bootstrap token written to `stderr` (was `stdout` — leaked to captured
    output).
  - Log handler changed to `stderr` to prevent log lines in captured output.
  - SI-2: unknown tool name in loop sanitized before log interpolation
    (truncate to 64 chars, replace control chars).
  - AG-UI `AGENT_ARTIFACT` wire uses camelCase `{dataType, toolName, data}`
    (was snake_case; AG-UI camelCase invariant).
  - AG-UI `A2UI_UPDATE` envelope wraps message array: `{messages: [...]}`.
  - Agent card removes `urn:agui:run:v1` from `capabilities.extensions[]`;
    AG-UI is advertised via `x-agui.endpoint` only (wrong slot per A2UI F2).
  - `forwarding.bind()` called in `ag_ui_run` before creating the worker
    task so credentials are bound in the correct context.
  - `serverInfo` in MCP `initialize` response includes `title` field
    (MCP 2025-06-18).
  - `register_content_type` enforces global component-name uniqueness.
  - Console `chat.js` AGENT_ARTIFACT consumer reads camelCase keys
    (`dataType`, `toolName`).
  - `a2uiClientCapabilities` in console includes `version`, `catalogs`,
    `tier` on both A2A and AG-UI paths.

- **`ChatDriver` A2A consumer conformance** (D7 hard-MUST floor):
  - Card discovery: fetches and caches `/.well-known/agent-card.json`
    before first request; selects transport from `preferredTransport`.
  - Message/Task discrimination: checks `result.get("kind") == "message"`
    before accessing `task["id"]`.
  - `X-A2A-Extensions` header sent on `message:send`; response echo read
    to confirm activation (`_a2ui_active` flag).
  - Interrupt states (`input-required`, `auth-required`) fire `"interrupt"`
    emit and raise `A2AError` instead of polling to timeout.
  - `extract_a2ui` dispatches on `DataPart.metadata.mimeType`
    (`"application/a2ui+json"`) at the part level, not artifact level.
  - `A2UI_MIME` sourced from `A2UI_MIME_TYPE` constant in
    `models/content_types` (removes local duplicate).

---

## [0.1.0] — 2026-06-13

Initial release.

### Added
- `Agent` / `build_app()`: single FastAPI app exposing A2A v0.3.0
  (HTTP+JSON), AG-UI (SSE), A2UI v0.9.1 Standard Profile v1 artifacts,
  MCP (2025-06-18, Streamable HTTP) behind OAuth 2.1, the agent card, and
  the admin console.
- `ToolSet` / `@tool` with tiers (1 = query: A2A+MCP, 2 = composite: A2A
  only), `emits=` content types, console `sample=`, adapter injection via
  keyword-only annotations, `ToolInterrupt` for input-/auth-required
  pauses with typed resume handlers.
- `SourceAdapter` base: allowed-hosts enforcement on every hop, redirect
  pinning, retry-once policy, namespaced credential resolution from the
  AES-256-GCM encrypted store.
- Loop policies: max turns, tiered tool timeouts, wall-clock deadline
  (suspended during interrupts), cumulative token budget across resumes,
  task-local result cache.
- Auth: API keys (single-use bootstrap token on zero-key startup), OAuth
  2.1 AS for `/mcp` (S256 PKCE, refresh rotation with family revocation,
  two-value audience), kind-tagged identities with per-surface assertions,
  rate limiting with trusted-proxy-aware client IPs.
- Standard Profile v1: 14 frozen content types; domain-card extension API
  (`ContentModel` subclass + own `catalog_id` + `register_content_type`).
- `agent_sdk.testing`: `FakeModelClient`, `reply`, `tool_call`,
  `ChatDriver` (multi-turn AG-UI/A2A driver for integration tests and
  `python -m agent_sdk test-chat`).
- Admin console (vanilla JS, strict CSP) at `/admin`: keys, credentials,
  tool try-out, self-check.
- Repo-level `template/` (the ~10-file agent footprint) and `docs/`.
- Claude Code harness plugin (`harness/`) with 18 seeded skills covering
  the full agent development lifecycle: scaffold → implement →
  zero-tolerance redteam → conformance → acceptance → ops.
- AlphaGeo climate-risk agent (`examples/alphageo/`) as the worked
  reference implementation and SDK CI target.
- `contrib/` (EXPERIMENTAL): `action_gate`, `obo`, `commitments`,
  `webhooks` — validated by the m365 reference agent port.
