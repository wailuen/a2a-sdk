# w067 — GitHub issues 261–267

Sourced from open issues on wailuen/a2a-sdk, filed 2026-10-25 by /sdk-autoloop cycle 2 from the verified w066 deferred lists (each re-checked at v0.23.0, 006ac7e). Rulings were posted on every issue before this wave (links per todo). GH-186 and GH-224 are labelled `deferred`.
Groups run in parallel unless a todo names a `Depends:` on another group's item. Items inside one group share files and run in order.
Target: 0.24.0. A2UI is chosen per request against acceptedOutputModes (GH-261). TimeSeriesChart keys become Literal types (GH-262). Invalid bearers get `error="invalid_token"`, and failed-bearer traffic gets its own bucket (GH-265). Wrong-state A2A messages get HTTP 400 instead of 501 (GH-266).

Each issue body lists file:line and the fix for every numbered item. Implement every numbered item in the issue body exactly as described there; where the ruling comment differs from the body, the ruling wins. Do NOT edit `template/`. Shared files edited by more than one group (`CHANGELOG.md`, `DESIGN.md`, `docs/protocols.md`, `workspace/components/README.md`) are edited with in-place Edit, each item touching only its own row or section, never a whole-file rewrite. Each item adds its own entry to `CHANGELOG.md` `[Unreleased]`, naming every changed `agent_sdk/` file by repo path (LRN-491), and keeps exactly one `## [Unreleased]` heading (LRN-494). Breaking items go under `### 🔴 Breaking changes` with a Migration line. Tests run against `build_app()` over the ASGI transport, not hand-written fake clients (LRN-496). Every new client-facing error string is fixed text that never echoes input (SI-2).

---

## G1 — console

- [ ] `GH-263` chat.js CHUNK role on minted id, unclipped diagnostics, DESIGN §7.2 drift ‖ group:G1
  - Creates: (modifies `agent_sdk/console/static/chat.js`, `agent_sdk/console/static/a2ui.js`, `agent_sdk/console/static/retry.js`, `DESIGN.md` (§7.2 only), `workspace/components/README.md` (C-081 row only), `tests/test_gh234_agui_chat_driver.py`, `tests/test_gh239_console_caps.py`, `tests/test_gh191_console_retry_policy.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/testing/chat.py`
  - Severity: medium
  - Root cause: the role check reads the minted chunk id; diagnostics and inline slices skip `clip()`; docs were not updated after GH-254.
  - AC: every numbered item in the issue (1–5), each with a node test where the item is behavioural. Item 4: a counter-based onFrame flip after the 2nd frame. The retry back-off wait takes the abort signal and rejects on abort, with a test of the abort → 499 → no-retry chain.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/263#issuecomment-6395232277
  - GH: https://github.com/wailuen/a2a-sdk/issues/263

## G2 — A2A / AG-UI routes

- [ ] `GH-261` A2UI decision ignores acceptedOutputModes, fails open, skips resume ‖ group:G2
  - Creates: (modifies `agent_sdk/routes/a2a.py`, `agent_sdk/routes/ag_ui.py` (`_capabilities` only), `agent_sdk/agent/runner.py`, `agent_sdk/routes/agent_card.py` (helper/parameter naming only), `tests/test_gh257_single_a2ui_gate.py`, `tests/test_gh259_a2a_route.py`, `docs/protocols.md` (A2UI/A2A output-mode paragraphs only), `CHANGELOG.md`)
  - Reads: `agent_sdk/common/media.py`, `agent_sdk/a2ui/translator.py`
  - Severity: medium
  - Root cause: the A2UI choice is made from the app gate and the header only, then output-mode filtering runs after translation; the gate parameters default to True.
  - AC (items 1–3): one per-request decision `a2ui_enabled ∧ opt-in ∧ (acceptedOutputModes absent or accepts application/a2ui+json)`, made before `build_artifact`. All `a2ui_enabled` parameters are keyword-only and default False. A resume with `acceptedOutputModes` replaces the stored value. Tests over `build_app()`: header opt-in + `["application/json"]` gets a JSON DataPart (not -32005); header opt-in + `["application/a2ui+json"]` gets an A2UI part; a resume with new modes is honoured.
  - AC (item 4): `metadata.mimeType` matches the kept parts after filtering.
  - AC (item 5): the A2UI-off tests use an emitting ContentModel tool on an app whose `allowed_components` removes every type (or an equivalent setup where `a2ui_enabled` is False while the tool returns a ContentModel), so they fail if the gate is removed.
  - AC (items 6–7): CHANGELOG fixes, and the lows as listed.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/261#issuecomment-6395231865
  - GH: https://github.com/wailuen/a2a-sdk/issues/261
  - Reuses: C-006  # A2uiCapabilities.gated keeps the single decision point; update the C-006 row in GH-267, not here.

- [ ] `GH-266` MCP void-result deviation docs; A2A wrong-state message HTTP 400 ‖ group:G2
  - Creates: (modifies `agent_sdk/routes/a2a.py`, `agent_sdk/models/errors.py`, `agent_sdk/common/wire_errors.py`, `docs/protocols.md` (MCP heading/version paragraph and A2A error table only), new `tests/test_gh266_protocol.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/mcp.py`
  - Severity: medium
  - Depends: GH-261
  - Root cause: -32004 is mapped to 501 for every call site; `wire_errors` maps only two client codes; the MCP docs predate version negotiation.
  - AC (item 1): docs/protocols.md records the void-result deviation with its parity reason. No code change in mcp.py.
  - AC (item 2): a message to a terminal task, or to a non-interrupted working task, returns -32004 with HTTP 400 on the REST binding (both the `/v1/message:*` and the colon-id paths). Genuinely unsupported operations keep 501. Tests over `build_app()`.
  - AC (item 3): -32600 maps to 400 and -32601 to 404. Tests. The MCP docs list 2025-11-25, 2025-06-18 and 2025-03-26, the newest-version fallback and the title gate.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/266#issuecomment-6395232882
  - GH: https://github.com/wailuen/a2a-sdk/issues/266

## G3 — A2UI catalog / content types

- [ ] `GH-262` catalog wire-required ignores serializer omissions; DocumentItem.modified_by ‖ group:G3
  - Creates: (modifies `agent_sdk/a2ui/catalog.py`, `agent_sdk/models/content_types.py`, `DESIGN.md` (A2UI catalog / SDK-extension fields section only), `tests/test_gh258_catalog.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/a2ui/translator.py`, `tests/test_gh225_multi_type_emits.py`
  - Severity: medium
  - Root cause: required-ness is inferred from defaults only, while `wire()` drops None values and serializers pop keys.
  - AC (item 1): a `wire_omitted: ClassVar[frozenset[str]]` on ContentModel is used by both the serializers and `_wire_required`, and a nullable field is never shown as required. A parametrized test over every registered Standard type compares the summary with a `wire()` round-trip.
  - AC (item 2): DESIGN.md records `modified_by` (and the EntityList `title`/`showing` extras) as SDK extensions. No wire change.
  - AC (item 4): `x_key: Literal["date"] = "date"` and `y_key: Literal["value"] = "value"`, and the error names the allowed value. CHANGELOG Breaking entry updated.
  - AC (lows): as listed in the issue.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/262#issuecomment-6395232063
  - GH: https://github.com/wailuen/a2a-sdk/issues/262

## G4 — testing clients

- [ ] `GH-264` turns.py stale state, probe-based catalogs, unbounded card fetch, MCP version fallback ‖ group:G4
  - Creates: (modifies `agent_sdk/testing/turns.py`, `agent_sdk/testing/chat.py`, `agent_sdk/testing/mcp.py`, `tests/test_gh237_testing_clients.py`, `docs/testing.md`, `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/agent_card.py`
  - Severity: medium
  - Root cause: turns.py builds a probe driver and reaches into its private card; the message branch never clears state; the card fetch sits outside the budget.
  - AC: every numbered item as ruled. The card is fetched once and its catalog IDs go in through a public ChatDriver constructor parameter, merged with the standard catalog and de-duplicated. The AG-UI path gets the same catalogs. Tests over `build_app()` where possible.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/264#issuecomment-6395232473
  - GH: https://github.com/wailuen/a2a-sdk/issues/264

## G5 — auth rate limiting

- [ ] `GH-265` failed-bearer traffic shares the OAuth refresh bucket; rate-limit docs/tests stale ‖ group:G5
  - Creates: (modifies `agent_sdk/auth/middleware.py`, `agent_sdk/routes/oauth.py`, `agent_sdk/app.py` (OAuth 429 handler only), `DESIGN.md` (§6 rate-limit sentence only), `docs/protocols.md` (auth section only), `tests/test_gh260_rate_limit.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/common/limits.py`, `agent_sdk/config.py`
  - Severity: medium
  - Root cause: one limiter object serves both failed-bearer 401s and the OAuth endpoints.
  - AC: a separate per-IP failed-bearer limiter (same setting). A test drains it and then succeeds on `/oauth/register`. 429 body tests per OAuth API endpoint. `Cache-Control: no-store` on API 429s. Browser OAuth pages render the branded HTML error page with 429. An invalid or expired bearer gets `Bearer error="invalid_token", resource_metadata="..."`, a missing bearer keeps the bare challenge (assert both), and token responses add `Pragma: no-cache`. Breaking entry for the challenge change.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/265#issuecomment-6395232689
  - GH: https://github.com/wailuen/a2a-sdk/issues/265

## G6 — ingress cleanup and records

- [ ] `GH-267` credentials double parse, registry/record drift, weak resume tests ‖ group:G6
  - Creates: (modifies `agent_sdk/common/json_strict.py`, `agent_sdk/credentials/forwarding.py`, `agent_sdk/routes/mcp.py` (`_is_json_content_type` wrapper only), `agent_sdk/routes/ag_ui.py` (body-cap comment only), `agent_sdk/contrib/action_gate/gate.py` (docstring only), `agent_sdk/example/agent.py`, `workspace/components/README.md` (C-006 and C-079 rows only), `workspace/todos/completed/w066-gh-issues.md` (Creates lines only), `tests/test_gh235_nested_json_and_resume.py`, `tests/test_gh251_ingress.py`, `CHANGELOG.md`)
  - Reads: `agent_sdk/routes/a2a.py`
  - Severity: medium
  - Depends: GH-266
  - Root cause: cleanup and record drift left over from w066.
  - AC: every numbered item as ruled. `loads_strict(..., reject_duplicate_keys=True)` parses the header once. The deep-metadata test sends an otherwise valid message and asserts the nesting error code. The resume test parametrizes `"approved"` and `"rejected"`.
  - Ruling: https://github.com/wailuen/a2a-sdk/issues/267#issuecomment-6395233057
  - GH: https://github.com/wailuen/a2a-sdk/issues/267
