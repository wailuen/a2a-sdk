# w068 — phase redteam medium/low findings

- Wave: w068
- Scope: phase
- Date: 2026-10-25

Non-blocking — these did not block w068's archive. Address opportunistically or fold into a future wave.

## Medium

### RT-001 — agent_sdk/routes/mcp.py:1213 [SDK candidate]
`if isinstance(version, str) and version != live_version:`
GH-273 mismatch 400 echoes SUPPORTED_PROTOCOL_VERSIONS[0] (2025-11-25) instead of the owned session's negotiated version; in the ruled case it echoes back the client's own value, giving no recovery hint. Runs after the owner-checked lookup, so echoing live_version is SI-5 safe. tests/test_gh273_mcp_session_version.py::test_mismatched_header_is_400 pins the unhelpful value.
- Fix: use `headers={_PROTOCOL_VERSION_HEADER: live_version}`; test asserts `== "2025-06-18"`.
- Codify: a version-mismatch rejection on an owned session must echo the session's negotiated version, never the server default.

### RT-002 — agent_sdk/testing/turns.py:146 [SDK candidate]
`except (httpx.HTTPError, ValueError) as exc:`
GH-268 item 3: card driver must be cached only after a successful fetch. _card_driver re-raises only 429/5xx; a transport error or non-JSON body is swallowed, returns ChatDriver(card={}), and run_turn caches it for all retries — one connection reset disables A2UI and catalogs for the whole turn.
- Fix: re-raise httpx.TransportError; in _a2a_attempt, _agui_attempt and run_turn._run_attempt map it to reason='transport-error' without setting card_driver. Keep only 4xx-other and non-object cards as "does not advertise A2UI". Test: ConnectError on attempt 1, good card on attempt 2 → real catalogs.
- Codify: memoize a fetched resource only after a successful fetch; transient failures (transport, 429, 5xx) leave the memo empty.

### RT-003 — agent_sdk/models/content_types.py:375 [SDK candidate]
`populate_by_name=True, hide_input_in_errors=True, ser_json_inf_nan="constants"`
GH-270 refactor claims byte-identical output but changes it for non-finite floats set after validation: model_dump_json() now writes NaN/Infinity (invalid JSON; v0.24.0 wrote null); TimeSeriesChart.wire() keeps inf in data[].value (v0.24.0 wrote None). _assert_finite docstring (line 278) and CHANGELOG GH-270 item 3 are now wrong. Pin test uses only validated instances.
- Fix: either drop ser_json_inf_nan='constants' and have _wire_rule refuse non-finite floats, or record the change (CHANGELOG line, docstring fix, pin case for a mutated non-finite value).
- Codify: a "byte-identical" refactor must pin edge-case output (mutated/invalid state); a config flag added for one path can change another serializer.

### RT-004 — tests/test_gh258_catalog.py:410 [SDK candidate]
`pytest.skip("summary truncated by the 250-character budget")`
GH-270 item 4 two-way round-trip: reverse test test_summary_declares_every_emitted_key skips FundPerformance, MultiCategoryChart, UserProfile (truncated) and MarketBriefing (prose). For depth-0 fallback summaries nested models render as bare names treated as free-form, so nested recursion is a no-op where shapes are deepest. Removing MarketBriefing from the exclusion list is nominal since both tests skip it.
- Fix: build the reverse check from an untruncated summary (`_summary_at_depth(cls, 1)` without the budget, or add a budget parameter); remove the truncation skip; assert undeclared_paths descends into at least one nested object (e.g. CalendarEvents.events[].organizer).
- Codify: a conformance test that skips the hardest cases does not satisfy a "recurses into nested shapes" AC; run against the untruncated source of truth.

### RT-005 — tests/test_gh234_agui_chat_driver.py:792 [SDK candidate]
`f({"type": "TOOL_CALL_START", "toolCallName": 5}),`
GH-268 AC needs one test per bad shape per transport, incl. non-string text. On AG-UI that is a non-string TEXT_MESSAGE_CONTENT/CHUNK delta; _bad_shape_frames lacks it. The isinstance(delta, str) guard in agent_sdk/testing/chat.py::_run_agui could be deleted with no failure; without it a dict delta raises TypeError in ''.join and escapes run_turn.
- Fix: add `f({"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": {"x": MARKER}})` and the TEXT_MESSAGE_CHUNK variant; assert reason == 'malformed-stream' and marker absent.
- Codify: every new shape guard needs a test that fails when the guard is removed (LRN-544); list AC shapes per transport and check each has a case.

### RT-006 — docs/testing.md:95 [SDK candidate]
"`turns` fetches the card once, inside the same slot wait and time budget as the turn, ..."
Documented behaviour changed: turns refetches the card after 429/5xx; card_catalog_ids drops empty IDs and IDs over 512 chars, caps at 32, standard catalog first; new 'malformed-stream' failure reason. Doc still says "fetches the card once" with an unbounded merge.
- Fix: rewrite: card fetched until one fetch succeeds (429/5xx fails the attempt with http-429/http-error and is retried); supportedCatalogIds filtered (non-empty, ≤512 chars) and capped at 32, standard first; bad stream frame fails the attempt with reason malformed-stream.
- Codify: when a doc edit is conditional on a behaviour change, grep the doc for the old wording before deciding no edit is needed.

### RT-007 — workspace/learning/LRN-509-testing-client-real-app.md:17 [SDK candidate]
Check clause allow-list of MockTransport tests.
The wave edited LRN-509's Check clause to allow-list its own three new MockTransport tests; file is outside every group's Creates list (as is tests/test_gh71_acceptance_api_stream.py, also modified). Loosening the gate the wave is judged by defeats LRN-496/LRN-509. The edit dropped the comma before `test_mcp_client_rejects_unsupported_negotiated_version`. In test_card_retry_builds_no_new_client the `# MockTransport:` comment talks about a 429 card while the test serves a 503.
- Fix: revert the LRN-509 edit and route the allow-list change through /codify as a recorded ruling, or add LRN-509 and test_gh71 to the todo's Creates with justification. Fix the comma and the 503 comment.
- Codify: a wave must never edit an LRN Check clause to whitelist its own new code; Check changes go through /codify with a recorded rationale.

## Low

### RT-008 — agent_sdk/auth/middleware.py:54 [SDK candidate]
`# never in the OAuth-endpoint bucket (unauth_limiter).`
Comment says a bad bearer on /oauth/revoke counts only in bearer_limiter, but the route has `dependencies=[Depends(unauth_rate_limit)]` so it counts in both (DESIGN.md:447 is correct). docs/protocols.md implies the revoke 429 carries the Bearer invalid_token challenge; it is raised via _rate_limited() with no WWW-Authenticate.
- Fix: reword the comment; in docs/protocols.md say the challenge is on /v1, /ag-ui and /mcp 429s only, and revoke's 429 is the plain OAuth JSON 429.

### RT-009 — agent_sdk/a2ui/catalog.py:74 [SDK candidate]
`return "|".join(json.dumps(v) for v in values)`
_values_str json.dumps raises TypeError for non-JSON-native enum/Literal values (Decimal, date, custom); old code used str(). _field_summary's broad except replaces the whole summary with '{...}', silently wiping that card's catalog summary.
- Fix: `json.dumps(v, default=str)` or per-value str(v) fallback; test with an Enum of non-JSON-native values.

### RT-010 — agent_sdk/models/content_types.py:431 [SDK candidate]
`if not info.by_alias:`
_wire_rule picks alias vs name from info.by_alias only. With ConfigDict(serialize_by_alias=True), model_dump() without by_alias writes alias keys while key() returns names. Probe: `{'asOf': None, 'hiddenKey': 'x', 'as_of': None}` — duplicate null key, and the wire_omitted alias is not popped.
- Fix: choose the key by what the handler wrote: `alias = f.serialization_alias or f.alias; k = alias if alias and alias in data else name` (for keeps_null, use alias when by_alias or serialize_by_alias is set).

### RT-011 — agent_sdk/common/media.py:7 [SDK candidate]
`_A2UI_MEDIA_TYPE = "application/a2ui+json"`
accepts_a2ui_mode (C-097) hard-codes its own copy instead of reusing content_types.A2UI_MIME_TYPE; nothing pins equality, so a later bump could split build/echo decision from artifact mimeType.
- Fix: test `media._A2UI_MEDIA_TYPE == content_types.A2UI_MIME_TYPE`, or move the constant to agent_sdk/common and import it from content_types.

### RT-012 — agent_sdk/routes/a2a.py:453 [SDK candidate]
`modes = config.accepted_output_modes if config is not None else None`
C-006/C-097: echo must read the same per-request decision the build used. _a2ui_decision recomputes from params.configuration while the runner builds from record.accepted_output_modes; they agree only because _create_task_record copies non-empty modes. Also the G5 SI-2 AC (token absent from logs and HTML 429 page) has no caplog assertion in tests/test_gh260_rate_limit.py.
- Fix: _a2ui_decision reads record.accepted_output_modes; add caplog checks that the bad bearer never appears in logs on /v1, /ag-ui/run, /mcp and /oauth/revoke 429 paths.

---

Autoloop cycle 4 (2026-10-26): critical/high-only filter. The 4 high candidates (sdk-candidates 2/4/5, G3 migration line) were re-verified at v0.25.0: all fixed or low. Nothing filed; loop finished.
