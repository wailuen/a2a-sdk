# w068 — protocol audit mediums and lows

Wave: w068. Date: 2026-10-26. Source: the wave's final protocol audit.

### P-001 (medium) — AG-UI — proto:agui
- Rule: Trap 15 / CUSTOM spec: advertised customEvents valueSchema must match the emitted value
- Description: The agent card says AGENT_ARTIFACT carries data of type object (agent_sdk/routes/agent_card.py, _CUSTOM_EVENT_SCHEMAS, AGENT_ARTIFACT entry: data: {type: object}). The route in agent_sdk/routes/ag_ui.py (ArtifactEvent branch, about lines 443-460) puts payload.wire() into data. For the prose content type, wire() returns a bare markdown string (agent_sdk/models/content_types.py, def wire at about line 1147, GH-179). Any non-model payload also passes through unchanged. So a consumer that validates against the card will reject valid prose artifacts. Names match the routing table, so nothing is dropped. Only the value shape is wrong. docs/protocols.md also lists data without a type.
- Fix: Change the card's data schema to accept object or string, for example {"type": ["object", "string"]}, or drop the type constraint. Keep it in step with what ArtifactEvent can carry. Add a test that checks each emitted CUSTOM value against its advertised valueSchema.

### P-002 (low) — AG-UI — proto:agui
- Rule: Resume schema: ResumeEntry.status is required (resolved | cancelled)
- Description: agent_sdk/routes/ag_ui.py in _resume_interrupt_id (about line 585) and the resume branch in _run() (about lines 791-796) accept a resume entry with no status (only an invalid status is rejected). status=None is then passed into the ResumeEnvelope. The spec requires status on every resume entry. The leniency is not harmful on the wire, but it is a gap against the schema, and the downstream consumer must handle None.
- Fix: Reject a resume entry with a missing or non-string status as an invalid resume entry. If the leniency is deliberate, record it as a ruling in DESIGN.md section 5.3.

### P-003 (low) — AG-UI — proto:agui
- Rule: RunAgentInput.tools and context are accepted but ignored (static GenUI via frontend tools unsupported)
- Description: The route reads only threadId, runId, state, messages, resume and forwardedProps. tools[], context[] and parentRunId are silently dropped. A client that registers frontend tools for Static GenUI (tool-call-bound components) will never see its tools offered to the model, and no error says so. This is a feature gap, not a wire violation. The card's customEvents and A2UI_UPDATE path is the supported GenUI mode.
- Fix: State in docs/protocols.md that only declarative GenUI (A2UI_UPDATE) is supported and that tools[] and context[] are ignored. Optionally log or flag when a client sends a non-empty tools[].

### P-004 (low) — AG-UI — proto:agui
- Rule: Tool-call lifecycle completeness on a mid-batch serialization failure
- Description: In the _emit() helper (agent_sdk/routes/ag_ui.py, about lines 705-735), a serialization failure closes an open TEXT_MESSAGE (added in the current working-tree diff) and then emits RUN_ERROR. It does not close an open tool call. A ToolCallEvent batch is START, ARGS, END. ARGS goes through _tool_json, which replaces unserializable values with a fallback, so this is very unlikely. If a frame inside a tool batch ever did fail, the client would see a dangling TOOL_CALL_START before RUN_ERROR. A related minor point: the resume path injects a synthetic TOOL_CALL_ARGS of "{}" and a step named turn-1, so original arguments are lost and the step name can repeat the first run's.
- Fix: Track an open tool call in _emit the same way as open_message, or document it as unreachable. Optionally name the synthetic resume step with the run id.

### P-005 (low) — AG-UI — proto:agui
- Rule: Heartbeat uses an SSE comment frame, not a data: frame
- Description: agent_sdk/common/sse.py defines HEARTBEAT = b": ping\n\n" and the route yields it on idle (agent_sdk/routes/ag_ui.py, about line 866). This is valid SSE (comments are ignored by EventSource and by standard fetch-stream parsers), so it is not a violation. A hand-written client parser that treats every non-empty line as data: could mishandle it. Note for the record only. Everything else is bare data: frames with no event: or id: lines, which matches the default encoder.
- Fix: None required. Optionally document that comment lines starting with a colon must be ignored by clients.

### P-006 (low) — AG-UI — proto:agui
- Rule: Scope note: auth/middleware.py and routes/oauth.py
- Description: No AG-UI conformance issues found in these two files. In agent_sdk/auth/middleware.py, require_identity runs as a dependency, so all auth rejections (401 with a WWW-Authenticate pointing at the bare PRM, 429 with Retry-After) are plain HTTP responses returned before any SSE stream starts. This keeps the rule that RUN_STARTED is the first frame once a stream exists. agent_sdk/routes/oauth.py has no AG-UI emission, only a comment (about line 195) saying the bare PRM serves the /ag-ui/ surface. Conformance PASS for the AG-UI-relevant parts: RUN_STARTED is first and STATE_SNAPSHOT second. Exactly one terminal RUN_FINISHED or RUN_ERROR is emitted on every path (parse error, validation, unknown interrupt, exception, stream end, serialization failure). All fields are camelCase. Only 17 of the 34 event types are emitted, which is allowed. Interrupt outcome, expiresAt as ISO-8601, TEXT_MESSAGE ordering with one messageId, TOOL_CALL START/ARGS/END then RESULT with a fresh messageId, and non-empty deltas are all correct. The card advertises x-agui with an explicit absolute endpoint and customEvents whose names match the emitted literals (traps 13, 14 and 15 name-match pass).
- Fix: None.

### P-007 (low) — SEAM — proto:seam
- Rule: MCP version echo consistency (GH-273 early-exit echo rule)
- Description: agent_sdk/routes/mcp.py mcp_post: the new GH-273 mismatch 400 (after the owner-checked _session_alive at ~L1204-1218) returns headers={MCP-Protocol-Version: SUPPORTED_PROTOCOL_VERSIONS[0]}. In the same handler, every early exit now echoes the owned session's negotiated version (early_headers). At this point the caller's ownership is already proven, so there is no oracle concern. Result: a client that negotiated 2025-06-18 and sends 2025-11-25 gets 400 with MCP-Protocol-Version: 2025-11-25. That header echoes the wrong value back and points the client away from the version its session actually holds. Repro: initialize at 2025-06-18, then tools/list with header 2025-11-25. You get a 400 whose response header says 2025-11-25, not 2025-06-18.
- Fix: In the mismatch branch, use headers={_PROTOCOL_VERSION_HEADER: live_version}. live_version is owned and in SUPPORTED_PROTOCOL_VERSIONS, the same as early_headers. Add an assertion on the response header to tests/test_gh273_mcp_session_version.py::test_mismatched_header_is_400.

### P-008 (low) — SEAM — proto:seam
- Rule: Auth failure signalling uniform across surfaces (GH-272 failed-bearer 429 challenge)
- Description: GH-272 adds WWW-Authenticate: Bearer error="invalid_token" to the 429 sent when a failed-bearer limit is hit on /v1, /ag-ui and /mcp (middleware._bearer_rate_limited). POST /oauth/revoke charges the same bearer_limiter (agent_sdk/routes/oauth.py ~L1202) but raises plain _rate_limited(). The app.py OAuth 429 handler then turns that into JSON temporarily_unavailable with no challenge header. So the same bad-bearer condition reaches its limit with two different signals, depending on the surface. CHANGELOG scopes the challenge to /v1, /ag-ui and /mcp, which matches the code. But the new docs/protocols.md text puts 'POST /oauth/revoke with a bad bearer also counts in the failed-bearer window' directly before 'When that window is spent, the 429 carries Retry-After and the same Bearer error="invalid_token" ... challenge'. Readers will take that to cover revoke too, and it does not.
- Fix: Choose one of two fixes. (a) Raise _bearer_rate_limited(request, runtime) in oauth_revoke so the challenge is kept, and pass it through the app.py JSON 429 handler (it already merges exc.headers). (b) Keep the current behaviour and rewrite the docs/protocols.md sentence so it says the revoke 429 is the OAuth JSON 429 with no challenge.

### P-009 (medium) — A2A — proto:a2a
- Rule: D6/D3 extension negotiation: extension fields only when activated (ref reference s6, D7.11)
- Description: TaskStatus.error (WireError) is a non-spec field emitted un-namespaced on every failed Task, status-update frame and tasks/list entry (agent_sdk/models/a2a.py TaskStatus.error; routes/a2a.py _unserializable_tail builds it too). The card declares it as the extension https://agent-sdk.dev/extensions/task-error/v1 (routes/agent_card.py task_error_extension), but no route in routes/a2a.py reads that URI from X-A2A-Extensions, and it is not in _ECHO_EXTENSION_URIS. The field is emitted whether or not the client activated it, which breaks the activate-then-rely rule. Strict clients that validate TaskStatus against a2a.json may also reject the unknown property.
- Fix: Gate TaskStatus.error on the task-error URI appearing in X-A2A-Extensions and echo it when used. Or move the data into TaskStatus.message.parts (a DataPart with metadata) or into status metadata, so no new field is needed.

### P-010 (low) — A2A — proto:a2a
- Rule: D2 error to HTTP mapping: -32004 returned as 400 for a message to a terminal or non-interrupted task
- Description: routes/a2a.py _resume_or_error (lines 620-628) and message_stream (lines 1066-1070) return -32004 UnsupportedOperation with HTTP 400 (GH-266). The kit digest table, models/errors.py A2A_HTTP_STATUS, and the code's own comments all say 501 (tasks_get with a colon in the id still returns 501), so one error code maps to two statuses depending on the call site. The live v0.3.0 spec (sections 3.2.3, 7, 8.2) only requires status codes that correspond to the error type and gives no normative per-code table. So 400 is not a spec violation. The inconsistency is internal, and the comments wrongly say 'A2A v0.3.0 says 501'. The terminal re-message rule itself is satisfied: the error is returned and no new task starts.
- Fix: Fix the comments so they do not claim the spec says 501, and record the GH-266 ruling in DESIGN.md section 5.1. Either use one status for -32004 everywhere or document the split (wrong-state 400 vs unsupported-method 501).

### P-011 (low) — A2A — proto:a2a
- Rule: D3 server-emitted Message.contextId
- Description: The fixed failure Message in _unserializable_tail (routes/a2a.py lines 979-984) is built without contextId or taskId. The kit digest treats server-emitted Message.contextId as required. The schema marks it optional, so this is only a hardening gap. The sync_reply bare Message path does set contextId.
- Fix: Pass contextId=record.task.context_id and taskId=record.task.id when building that Message.

### P-012 (low) — A2A — proto:a2a
- Rule: D2 tasks/list parameter handling
- Description: GET /v1/tasks (routes/a2a.py lines 1115-1137) accepts only pageSize and pageToken. It silently clamps pageSize outside 1-100 instead of returning -32602, and it ignores the contextId and status filters that clients commonly send, so a filtered request returns unfiltered tasks without any error. The response shape (tasks, totalSize, pageSize, nextPageToken) is fine.
- Fix: Reject pageSize outside 1-100 with -32602. Support, or explicitly reject with -32602, the contextId and status filters.

### P-013 (low) — A2A — proto:a2a
- Rule: D3 Message object fields / D2 oversized body code
- Description: (a) The Message model (models/a2a.py) has no referenceTaskIds, so the field is silently dropped on inbound messages. (b) An oversized request body returns -32602 with HTTP 400 (_parse_send, line 511). -32600 Invalid Request, or a 413, fits better.
- Fix: Add referenceTaskIds: list[str] | None to Message. Return -32600 for an oversized body.

### P-014 (low) — A2A — proto:a2a
- Rule: D1 transport declaration clarity
- Description: The card (routes/agent_card.py build_agent_card) sets preferredTransport to HTTP+JSON through the model default and url to the base URL, and the /v1/message:send, /v1/message:stream, /v1/tasks, /v1/tasks/{id}, :cancel and :subscribe routes exist, so declared matches served. It emits no additionalInterfaces entry, so a consumer must infer that /v1 is appended to url. The code comment documents this. The card is served at /.well-known/agent-card.json (plus the agent.json alias), with an ETag and no auth. securitySchemes use the correct http-bearer and oauth2 (flows plus oauth2MetadataUrl) variants, and security is an OR-of-ANDs array. PUBLIC_URL and https are enforced in prod (config.py lines 345-354).
- Fix: Optional: add additionalInterfaces=[{transport:'HTTP+JSON', url:<base_url>}] so the binding is explicit.

### P-015 (low) — A2UI — proto:a2ui
- Rule: Frozen field contract / DocumentList (Profile v1.1 DocumentItem)
- Description: agent_sdk/models/content_types.py:1574-1585 DocumentItem emits `modified_by` on the wire. It is not in the frozen DocumentItem contract (id, name, type?, modified?, link?, size?). Verified: DocumentItem(modified_by='bob').wire() contains 'modified_by'. The other SDK extensions (EntityList title/showing, ComparisonTable sort_by/unit/highlight/is_id, CalendarEvent.is_online) are documented in docstrings as GH-179 extensions. This one is not documented there, and not in the DocumentList compact schema (catalog.py:329) either. A strict v1 renderer that rejects unlisted fields would drop the card.
- Fix: Either add `modified_by` to wire_omitted and keep it model-side (text fallback only), or document it as an SDK extension in a DocumentItem docstring and in the compact schema comment, as GH-179 did for the other extensions.

### P-016 (low) — A2UI — proto:a2ui
- Rule: Compact schema accuracy: optional Profile fields missing from the teaching string
- Description: agent_sdk/a2ui/catalog.py:301-330 _COMPACT_SCHEMAS omit Profile-listed optional fields. Every '?' mark is correct and no required field is wrong or missing (checked programmatically: wire-required paths of the 13 object-shaped types equal the compact required paths). Omitted optional fields: TimeSeriesChart x_label/y_label/summary, EmailList messages[].conversation_id, MultiCategoryChart chart_config and CategoryValue.metadata, UserProfile presence.status_message and the out_of_office date/message fields, UserList presence.status_message. The UserProfile comment (line 325) admits it is partial.
- Fix: Optional: add the omitted optional keys with '?' where the 250-char budget allows. Otherwise state in the section header that optional Profile fields may be omitted.

### P-017 (low) — A2UI — proto:a2ui
- Rule: Compact schema type fidelity
- Description: agent_sdk/a2ui/catalog.py:326 UserProfile `business_phones:list` is an untyped list (the Profile and model say [string]). Line 303 uses `num|null` where every other schema uses `float`. Cosmetic: the '?' marks are unaffected and these strings are read by the model, not by a validator.
- Fix: Use `business_phones:[str]` and `value:float|null`.

### P-018 (low) — A2UI — proto:a2ui
- Rule: Model-derived fallback summary teaches shapes that never reach the wire
- Description: agent_sdk/a2ui/catalog.py:77-128, 168-178 _annotation_str and _nested_fields describe the Python annotation, not the serialised wire shape. Verified output: KpiCard's model-derived summary shows `trend?: "up|down|flat"|KpiTrend|null` although MetricItem._serialize_trend collapses KpiTrend to a direction string on the wire. DocumentItem's summary lists `web_url?` and `last_modified?` (wire_omitted or reshaped away) and ColumnDef lists `is_id?`. Only reached for domain cards, since all 14 built-ins have a hand-written compact schema (the registered MarketBriefing case also has a compact entry). A domain card that embeds MetricItem or DocumentItem is taught a non-wire shape.
- Fix: In _nested_fields and _summary_at_depth, skip names in the model's wire_omitted set and render a field that has a field_serializer by its serialised type. Alternatively, document the annotation-based limit in the docstring.

### P-019 (low) — A2UI — proto:a2ui
- Rule: Profile v1.1 cross-cutting `metadata` vs MarketBriefing prose exception
- Description: agent_sdk/models/content_types.py:1147-1150 MarketBriefing.wire() returns the bare markdown string, so `metadata` cannot reach the A2UI data model (verified: MarketBriefing(metadata={'a':1}).wire() has no metadata). The module docstring (lines 28-31) records this as a deliberate carve-out. Profile v1.1 says every FROZEN type MAY carry metadata, but also freezes MarketBriefing's data as a scalar string. The spec itself is ambiguous here; this is not an SDK defect. Disclosure annotations reach only the text fallback and AG-UI frame for this type.
- Fix: No code change. Raise the ambiguity with the Profile maintainers, and keep the docstring note.

### P-020 (low) — A2UI — proto:a2ui
- Rule: Frozen field contract / TimeSeriesChart x_key y_key
- Description: agent_sdk/models/content_types.py:892-909 pins x_key to 'date' and y_key to 'value' (validator rejects anything else, verified). The Profile defines them as free field-name strings. This is conformant for an emitter, since every payload the SDK produces satisfies the contract. It would reject a Profile-valid inbound payload (for example x_key='month') if these models are ever used to parse third-party time_series data.
- Fix: No change needed for emission. If inbound parsing is ever added, relax the Literal to str and keep the fixed default.

### P-021 (medium) — MCP — proto:mcp
- Rule: mcp-protocol §11 / RFC 8707: token aud must equal this server's canonical URI, checked at use
- Description: Audience is only checked as set membership. OAuthTokenStore.verify (auth/oauth_tokens.py:566-585) accepts a token if its audience is either the bare origin or {origin}/mcp. The identity that comes back carries no audience (auth/identity.py), and auth/middleware.py:_resolve_identity (lines 140-158) never compares it to the route being called. So a token minted for the bare origin (the A2A/AG-UI resource, see _bare_prm_payload at routes/oauth.py:193) is accepted by POST /mcp. A token minted for {origin}/mcp is accepted on /v1/* and /ag-ui/*. The PRM at routes/oauth.py:184 says /mcp is its own resource. The code documents this as a deviation, but PRM and token handling disagree on what the /mcp audience is. Everything else in the chain is sound: audience is validated at authorize (oauth.py:615), kept with the code and refresh metadata, and re-checked in verify.
- Fix: Carry the token's audience on Identity, or return it from verify. In require_identity, check that the audience matches the surface: MCP routes accept {origin}/mcp, plus the bare origin only if Claude.ai really needs it for MCP. A2A and AG-UI routes accept the bare origin. Add a test that a /mcp-audience token gets 401 on /v1/*.

### P-022 (medium) — MCP — proto:mcp
- Rule: mcp-protocol §4 / hard MUST 5: if outputSchema is advertised, a successful result must carry conforming structuredContent
- Description: routes/mcp.py:999-1004 and 1054-1083: a tool that declares emits (so tools/list advertises outputSchema at line 778-780) but returns or yields None gets back isError:false, an empty text block and NO structuredContent. The code comment calls this spec-consistent, but spec 2025-06-18 says servers MUST return structured results that conform to the advertised schema. Spec-following clients (for example the TypeScript SDK's Client.callTool) throw when a tool has an outputSchema, isError is false and structuredContent is missing. The same tool call would succeed on A2A/AG-UI but fail on a validating MCP client.
- Fix: Pick one. (a) Treat a None result from a tool that declares emits as an isError:true result with a fixed message such as 'tool produced no output'. (b) Omit outputSchema for tools whose emits type is optional. (c) If None is a valid outcome, declare the schema so an empty object conforms and emit {}. Update the parity note in DESIGN §5.6 to match.

### P-023 (low) — MCP — proto:mcp
- Rule: mcp-protocol §14: gate fields by negotiated version (P9.1 pattern)
- Description: The serverInfo.title rule is implemented as asked. Only 2025-11-25 sessions get title; 2025-06-18 and 2025-03-26 do not (mcp.py:587-591, index comparison on a newest-first tuple guarded by the assert at line 151; SUPPORTED_PROTOCOL_VERSIONS = 2025-11-25, 2025-06-18, 2025-03-26; initialize echoes a supported client version, else the newest). The spec digest says title is valid from 2025-06-18, so this is a safe over-gate. The gap is that the gate exists only on initialize. tools/list (mcp.py:771-783) is deliberately version-independent (comment at line 585, GH-246). Tool title, outputSchema and structuredContent, all added in 2025-06-18, are therefore also sent to clients that negotiated 2025-03-26. The initialize trap in P9.1 does not apply to these, but a strict 2025-03-26 validator could reject them.
- Fix: Either drop the 2025-03-26 entry from SUPPORTED_PROTOCOL_VERSIONS if no client needs it, or pass the session's negotiated version into _handle_tools_list and _handle_tools_call and omit title, outputSchema and structuredContent under 2025-03-26. Add a test that asserts serverInfo has no title at 2025-06-18.

### P-024 (low) — MCP — proto:mcp
- Rule: mcp-claude-platforms P9.5: claude.ai origin must not be droppable by config
- Description: config.py:161-162 makes https://claude.ai the default of CORS_ORIGINS, and the validator at config.py:325-330 only rejects '*'. Setting CORS_ORIGINS to any other list silently drops claude.ai. Then common/cors.py stops sending Allow-Origin and Expose-Headers: WWW-Authenticate for that origin, and common/origin.py:guard_origin returns 403 on every MCP route for any request that carries Origin: https://claude.ai. The CORS middleware itself is correct: preflight returns 204, Expose-Headers includes WWW-Authenticate and Mcp-Session-Id, the origin is echoed only from the allowlist, and Vary: Origin is set.
- Fix: Union https://claude.ai into the effective origin list inside a validator or in build_app(), or log a startup warning when it is missing.

### P-025 (low) — MCP — proto:mcp
- Rule: RFC 8707 / mcp-protocol §11: send and validate resource on token requests
- Description: routes/oauth.py:1104-1157: /oauth/token ignores any resource parameter on authorization_code and refresh_token grants. If a client sends resource=X that differs from the audience bound at authorize, the request is accepted and the code's audience wins. This is documented as deliberate because Claude.ai omits resource. The spec says the server SHOULD validate it when present. Absent is fine.
- Fix: When form.get('resource') is present, run store.validate_audience on it and return invalid_target (RFC 8707 §2) if it does not match the audience stored with the code or refresh token. Keep absent as allowed.

### P-026 (low) — MCP — proto:mcp
- Rule: mcp-protocol §4 / P5: tool annotations and title for Directory readiness
- Description: registry.py:532-535 seeds readOnlyHint=true and destructiveHint=false only for read_only tools. Other tools get only openWorldHint, so destructiveHint defaults to true on the wire, which is safe. idempotentHint is never set. Tool title is optional (mcp.py:776, emitted only if entry.title is set). The Directory checklist in P5 needs title plus the applicable read-only or destructive hint on every tool. The ≤64-char tool-name check is present (registry.py:571 and 1158).
- Fix: Require title at registration for Tier-1 tools, and make read_only=False tools state destructiveHint explicitly (true or false) instead of relying on the default.

### P-027 (low) — MCP — proto:mcp
- Rule: mcp-protocol §10 / P8: GET /mcp must be text/event-stream or 405
- Description: routes/mcp.py:1328-1347 returns 429 + Retry-After when the global or per-identity stream cap is full. This is a third outcome beyond the two the spec allows. It is documented as deliberate load-shedding (RT-003) with 200-per-identity defaults, and the P8 checklist lists 429 as a known 'couldn't connect' cause. The same code applies to /mcp/sse. Rated low because it is acknowledged and set up to be raised by config. Everything else on this verb is correct: Origin guard, 400 on a present-but-unknown version, 404 on an unknown or foreign session, and a first chunk padded to flush proxies.
- Fix: No change needed. Optionally log a warning when a stream is rejected at capacity so an operator can tell this from a real outage.

### P-028 (low) — MCP — proto:mcp
- Rule: mcp-protocol §1 / §14: batching rules by version
- Description: routes/mcp.py:1162-1166 answers any JSON array body with -32600 and HTTP 200. That is right for 2025-06-18 and later (no batching). A session that negotiated 2025-03-26 may legally send batches, so those would be refused. Separately, routes/oauth.py:229 advertises scopes_supported: [] (allowed, but an empty array can confuse strict clients), and the AS metadata has no openid-configuration fallback and no RFC 9207 iss response parameter. None of these block Claude.ai.
- Fix: Either state in docs that 2025-03-26 is supported without batching, or drop 2025-03-26. Omit scopes_supported while no scopes exist. Optionally add iss to authorization responses.

---

Autoloop cycle 4 (2026-10-26): critical/high-only filter. The 4 high candidates (sdk-candidates 2/4/5, G3 migration line) were re-verified at v0.25.0: all fixed or low. Nothing filed; loop finished.
