# w066 — GitHub issues 251–260

Sourced from open issues on wailuen/a2a-sdk, filed 2026-10-25 by /sdk-autoloop cycle 1 from the verified w065 deferred lists (each re-checked at v0.22.0, 9d1b07b). Rulings were posted on every issue before this wave (links per todo). GH-186 and GH-224 are labelled `deferred`.
Groups run in parallel unless a todo names a `Depends:` on another group's item. Items inside one group share files and run in order.
Target: 0.23.0. The runtime turns A2UI on only when the card advertises it (GH-257), and `TimeSeriesChart` rejects x_key/y_key other than date/value (GH-258). Both are Breaking.

Each issue body lists file:line and the fix for every numbered item. Implement every numbered item in the issue body exactly as described there; where the ruling comment differs from the body, the ruling wins. Do NOT edit `template/` except the peer copies named in GH-256 (G4); they land via commit+push to wailuen/a2a-agent-template inside this wave, and the commit stages only those paths (LRN-085/LRN-071). Shared files edited by more than one group (`CHANGELOG.md`, `DESIGN.md`, `docs/protocols.md`, `workspace/components/README.md`) are edited with in-place Edit, each item touching only its own row or section, never a whole-file rewrite. Each item adds its own entry to `CHANGELOG.md` `[Unreleased]`, naming every changed `agent_sdk/` file by repo path (LRN-491), and keeps exactly one `## [Unreleased]` heading (LRN-494). Breaking items go under `### 🔴 Breaking changes` with a Migration line. Tests run against `build_app()` over the ASGI transport, not hand-written fake clients (LRN-496). Every new client-facing error string is fixed text that never echoes input (SI-2).

---

## G1 — console (chat.js, a2ui.js) and console/regression tests

- [ ] `GH-254` chat.js role/fold parity with ChatDriver and Reset race ‖ group:G1
  - Creates: (modifies `agent_sdk/console/static/chat.js`, `tests/test_gh234_agui_chat_driver.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/testing/chat.py`
  - Severity: medium
  - Root cause: the CHUNK role guard checks only `seenChunkIds`, the history fold has no empty/id check, and Reset neither aborts the request nor guards the A2A contextId write-back.
  - AC (item 1): a role is recorded for an id only before any text for that id was buffered (CONTENT or CHUNK), matching `chat.py:312`. A node test feeds CONTENT(k1) then CHUNK(k1, role "tool") and asserts the text is kept as assistant.
  - AC (item 2): the fold skips empty text and gives an id-less buffer a minted id. Node test.
  - AC (item 3): the A2A path captures a generation/thread at send and drops the contextId write-back after a Reset. Node test.
  - AC (item 4, lows): Reset aborts the in-flight fetch with an AbortController, and stale CUSTOM/system lines are dropped. A resume click while busy shows a fixed "busy" note. The thread-change test changes the thread mid-stream via an onFrame hook.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/254#issuecomment-6393089186
  - GH: https://github.com/wailuen/a2a-sdk/issues/254

- [ ] `GH-255` a2ui.js renderers lack field-length caps; duplicated cap helpers ‖ group:G1
  - Creates: (modifies `agent_sdk/console/static/a2ui.js`, `tests/test_gh239_console_caps.py`, `DESIGN.md` (§7.1 only), `workspace/components/README.md` (C-059 row only), `CHANGELOG.md`)
  - Reads: `agent_sdk/models/content_types.py`
  - Severity: medium
  - Depends: GH-254
  - Root cause: the caps cover only row counts; the column note is a second copy of moreNote; MultiCategoryChart reads periods with no null guard.
  - AC (item 1): a single `clip(text, max)` helper is applied to every string a dedicated renderer prints. Node test with a 10,000-char name.
  - AC (item 2): `capRows(items, limit)` and `moreNote(n, noun)` are parameterised. Columns use them, and `moreColumnsNote` is removed.
  - AC (item 3, lows): MultiCategoryChart survives a null period. Its totals use only the shown categories (with Math.abs), notes are labelled, and categories are capped so periods×categories ≤ 1,000. Time-series keeps the newest points. Generic renderer sections are capped. The dead `closed` branch is fixed so a createSurface after deleteSurface is ignored. Node test for each. DESIGN.md §7.1 lists the caps.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/255#issuecomment-6393089342
  - GH: https://github.com/wailuen/a2a-sdk/issues/255
  - Reuses: C-059  # extend the shared capRows/moreNote helpers; update the C-059 row.

- [ ] `GH-253` restore deleted GH-235 nesting tests; console node tests cannot fail ‖ group:G1
  - Creates: (modifies `tests/test_gh235_nested_json_and_resume.py`, `tests/test_gh239_console_caps.py`, `tests/test_gh214_no_delete_surface.py`)
  - Reads: `agent_sdk/routes/oauth.py`, `agent_sdk/routes/a2a.py`, `agent_sdk/common/json_strict.py`
  - Severity: medium
  - Depends: GH-255
  - Root cause: the w065 test rewrite dropped the object-nesting route tests, and the stub-DOM node tests never attach to a parent.
  - AC (item 1): `test_oauth_register_nested_is_invalid_client_metadata` and `test_a2a_deep_metadata_never_breaks_task_list` are restored (see ae2d876). `nested()` can build objects as well as lists, and a two-entry below-cap test exists.
  - AC (item 2): the replay test attaches nodes to a parent and asserts exactly one painted child per surface.
  - AC (item 3): the always-on `"deleteSurface" not in chat` source check is its own test with no node skip. A `test_*_available_in_ci` guard fails when `CI` is truthy and node is absent. `isConnected` is checked against a real parent.
  - AC (item 4, low): source-only tests lose `@needs_node`.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/253#issuecomment-6393089017
  - GH: https://github.com/wailuen/a2a-sdk/issues/253

## G2 — A2A / AG-UI / MCP routes and runner

- [ ] `GH-257` runtime still enables A2UI when the card does not advertise it ‖ group:G2
  - Creates: (modifies `agent_sdk/routes/a2a.py`, `agent_sdk/agent/runner.py`, `agent_sdk/console/static/chat.js` (sendA2a opt-in only), `tests/test_gh249_a2ui_gating.py`, `docs/protocols.md` (A2UI section only), `CHANGELOG.md`)
  - Reads: `agent_sdk/a2ui/catalog.py`, `agent_sdk/routes/agent_card.py`, `agent_sdk/routes/ag_ui.py`
  - Severity: medium
  - Depends: GH-254
  - Root cause: GH-249 gated only the card; the request opt-in, the accepted modes and artifact building still assume A2UI is always on.
  - AC: one helper (e.g. `a2ui_enabled(app)`, computed from `supported_catalogs(allowed_components, emits)` once at build) drives `_capabilities`, `_SUPPORTED_MODES` and both `runner.py` artifact paths (:419 and :1097-1105). With A2UI off, a header opt-in gets no A2UI DataPart, `acceptedOutputModes: ["application/a2ui+json"]` alone gets -32005, and results use the TextPart/JSON fallback. The console sends the A2UI header and client capabilities only when the fetched card declares the extension. Tests over `build_app()` for an agent with no emitting tools and one with emitting tools. Breaking entry with migration.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/257#issuecomment-6393088260
  - GH: https://github.com/wailuen/a2a-sdk/issues/257

- [ ] `GH-259` TaskStatus.error spec message, acceptedOutputModes shaping, pageToken docs/tests ‖ group:G2
  - Creates: (modifies `agent_sdk/routes/a2a.py`, `agent_sdk/agent/runner.py`, `agent_sdk/models/a2a.py`, `docs/protocols.md` (A2A section only), `tests/test_rt001_oauth_capped_body.py`, new `tests/test_gh259_a2a_route.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/tasks/store.py`, `agent_sdk/tasks/memory.py`
  - Severity: medium
  - Depends: GH-257
  - Root cause: the failed status relies on the extension field alone; acceptedOutputModes is only checked, never applied; the pageToken docs predate the store hook.
  - AC (item 1): every failed task has `status.message` (role agent, one TextPart holding the same safe text as `status.error.message`). `error` is kept and documented as an SDK extension. Test over `build_app()`.
  - AC (item 2): when a client sends `acceptedOutputModes`, artifact parts are filtered to the accepted types. If none remain and `text/plain` is accepted, one TextPart fallback is kept; otherwise -32005. Tests for `["text/plain"]`, `["application/json"]`, and both.
  - AC (item 3): docs/protocols.md describes the store hook. The hook test moves to `tests/test_gh259_a2a_route.py` with a custom-store route test.
  - AC (item 4): docs say an over-cap A2A body gets 400 invalid params. The `a2a.py:167-168` layout is fixed.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/259#issuecomment-6393088522
  - GH: https://github.com/wailuen/a2a-sdk/issues/259

- [ ] `GH-251` unify JSON Content-Type check, test body caps, strict JSON + format-char gaps ‖ group:G2
  - Creates: (modifies `agent_sdk/common/body.py`, `agent_sdk/routes/ag_ui.py`, `agent_sdk/routes/a2a.py`, `agent_sdk/routes/mcp.py`, `agent_sdk/common/redact.py`, `agent_sdk/credentials/forwarding.py`, new `tests/test_gh251_ingress.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/common/json_strict.py`, `tests/test_gh246_mcp_route.py`
  - Severity: medium
  - Depends: GH-259
  - Root cause: three hand-copied media-type checks, one of them case-sensitive; cap and fallback paths with no tests; two text/JSON helpers outside the strict rules.
  - AC (item 1): `is_json_content_type(ct)` in `common/body.py` (case-insensitive, exact `application/json` or `+json` suffix after stripping params) is used by all three routes. Tests: `Application/JSON` is accepted, `application/json-seq` gets 415, on each route.
  - AC (item 2): an over-cap body test on `/v1/message:send` and `/ag-ui/run`, plus `read_capped_body` tests for a non-numeric and a lying Content-Length.
  - AC (item 3): `_tool_json` catches `Exception`, logs the type only once per fallback, and a NaN in tool args is replaced per value (not the whole dict). Tests.
  - AC (item 4): `safe_block_text` calls `drop_format_chars`, keeping newlines. Test.
  - AC (item 5): X-Agent-Credentials is parsed with `loads_strict`, and a NaN or duplicate key is rejected with the existing fixed error. Test.
  - AC (item 6): the stale comments are fixed.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/251#issuecomment-6393088850
  - GH: https://github.com/wailuen/a2a-sdk/issues/251

## G3 — A2UI catalog

- [ ] `GH-258` catalog prompt required-ness; TimeSeriesChart x_key/y_key ‖ group:G3
  - Creates: (modifies `agent_sdk/a2ui/catalog.py`, `agent_sdk/models/content_types.py`, `DESIGN.md` (A2UI catalog section only), new `tests/test_gh258_catalog.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/a2ui/translator.py`, `tests/test_gh225_multi_type_emits.py`
  - Severity: medium
  - Root cause: required-ness comes from the serialization schema, which omits defaulted fields; the TimeSeriesChart key fields are free strings the data points cannot satisfy.
  - AC (item 1): a field is shown as required when `wire()` always writes it (no default, or a non-None default). Docstrings are updated, nested expansion respects the 250-char budget, and tests use a model without `json_schema_serialization_defaults_required`.
  - AC (item 2): the compact schema shows `"x_key":"date","y_key":"value"`, and `TimeSeriesChart` rejects any other value with a fixed message. Breaking entry.
  - AC (item 3, lows): `dict[K,V]` renders as `{key: V}`, enum/Literal fields list their values, `supported_catalogs(emits=None)` adds CATALOG_ID only when a Standard type passes the filter, and `emits` is a `Sequence` (or is listed once). EntityList `title?`/`showing?` are recorded in DESIGN.md as SDK extensions that receivers ignore.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/258#issuecomment-6393088394
  - GH: https://github.com/wailuen/a2a-sdk/issues/258

## G4 — testing clients and acceptance docs

- [ ] `GH-256` A2A test clients not spec-conformant ‖ group:G4
  - Creates: (modifies `agent_sdk/testing/turns.py`, `agent_sdk/testing/chat.py`, `agent_sdk/testing/mcp.py`, `tests/test_gh237_testing_clients.py`, `harness/skills/acceptance/SKILL.md`, `.claude/skills/acceptance/SKILL.md`, `template/.claude/skills/acceptance/SKILL.md`, `docs/testing.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/a2a.py`, `agent_sdk/routes/agent_card.py`
  - Severity: medium
  - Root cause: turns.py treats taskId and contextId as either/or, takes a bool for A2UI support, and does not finish stream handling; one test still uses a MockTransport card.
  - AC (item 1): a resume sends both taskId and contextId. Test.
  - AC (item 2): turns.py passes the card's supportedCatalogIds into `ChatDriver(extra_catalogs=...)`. `_a2ui_advertised` survives a non-object card and logs card-fetch failures (type only).
  - AC (item 3): docstring + docs/testing.md state the additionalInterfaces non-goal. turns.py handles `kind=="message"` and stops at `final`. ChatDriver sends the A2UI header only when the card advertises the extension.
  - AC (item 4): item 5 of test_gh237 uses `build_app()` over ASGI.
  - AC (item 5): all three acceptance SKILL.md copies list `[--skills-tool]` and the structuredContent gate stop. The two harness/.claude copies stay byte-identical, and the template copy gets the same edit (commit + push to wailuen/a2a-agent-template, staging only that path). The testing/mcp.py docstring is updated.
  - AC (item 6, lows): `McpClient` rejects a negotiated version not in `SUPPORTED_PROTOCOL_VERSIONS`, and the gate reports an unresolvable `$ref` as a failure, not a crash. Tests.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/256#issuecomment-6393088084
  - GH: https://github.com/wailuen/a2a-sdk/issues/256

## G5 — docs and build records

- [ ] `GH-252` status-shorthand docs, resume rules, stale uv.lock, w065 records ‖ group:G5
  - Creates: (modifies `agent_sdk/contrib/action_gate/__init__.py`, `agent_sdk/contrib/action_gate/gate.py`, `docs/protocols.md` (resume section only), `DESIGN.md` (§5.3 and the :subscribe/ChildList sentences only), `agent_sdk/common/admission.py` (docstring only), `tests/test_gh235_nested_json_and_resume.py` (resume-status tests only), `pyproject.toml` (dev extras only), `uv.lock`, `workspace/todos/completed/w065-gh-issues.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/ag_ui.py`
  - Severity: medium
  - Depends: GH-253
  - Root cause: docs written before GH-247 removed the shorthand; jsonschema was promoted without relocking.
  - AC (items 1–3): no doc or docstring teaches `status="approved"`. DESIGN.md §5.3 states the resume rules. The resume test covers `"status": null` and asserts the published payload and `content == _RESULT_FALLBACK`.
  - AC (item 4): jsonschema appears once (core) in pyproject.toml, and `uv lock --check` passes.
  - AC (item 5): the w065 completed file and the GH-245 CHANGELOG bullet record the template SKILL.md edit.
  - AC (item 6): the :subscribe docs name GET and POST, and the ChildList claim is corrected.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/252#issuecomment-6393087904
  - GH: https://github.com/wailuen/a2a-sdk/issues/252

## G6 — auth rate limiting

- [ ] `GH-260` shared per-IP limiter can 429 the 401 challenge and the OAuth chain ‖ group:G6
  - Creates: (modifies `agent_sdk/auth/middleware.py`, `agent_sdk/routes/oauth.py`, `docs/protocols.md` (auth section only), new `tests/test_gh260_rate_limit.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/config.py`, `agent_sdk/common/ratelimit.py`
  - Severity: medium
  - Root cause: the bearer-less 401 path shares the unauth bucket with the OAuth endpoints, and OAuth 429s use FastAPI's `{detail}`.
  - AC (a): 31 bearer-less requests to `/mcp` inside a minute all get 401 with the PRM challenge, never 429.
  - AC (b): the OAuth endpoints still 429 past `unauth_rate_limit_per_minute`.
  - AC (c): an OAuth 429 body is `{"error":"temporarily_unavailable","error_description":"rate limit exceeded"}` with `Retry-After`. Non-OAuth 429s are unchanged. Tests over `build_app()`.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/260#issuecomment-6393088715
  - GH: https://github.com/wailuen/a2a-sdk/issues/260
