# w067 — protocol audit mediums and lows

Wave: w067. Date: 2026-10-25. Source: the wave's final protocol audit (no critical/high).

### P-001 (medium) — AG-UI — proto:agui
- Rule: TEXT_MESSAGE_START/CONTENT/END must be a closed triple; no open message at a terminal event
- Description: agent_sdk/routes/ag_ui.py:344-353 builds START, CONTENT and END as one batch. TextEvent.text is not passed through scrub_unencodable (the tool-result string path at line 380 is). If the text holds a lone surrogate, _emit (line 701-724) serializes START fine, fails on CONTENT, drops the rest of the batch, and appends RUN_ERROR. The client sees a TEXT_MESSAGE_START with no END before RUN_ERROR, which is a dangling message. Everything else about ordering and terminal coverage is clean.
- Fix: Scrub TextEvent.text with scrub_unencodable before building the triple. Optionally, in _emit's failure branch, close any message opened earlier in the same batch before RUN_ERROR.

### P-002 (low) — AG-UI — proto:agui
- Rule: Card customEvents valueSchema must match the real CUSTOM payload
- Description: agent_sdk/routes/agent_card.py declares AGENT_ARTIFACT valueSchema data as type object. agent_sdk/routes/ag_ui.py:445-446 sends data = payload.wire(), and for the prose ContentModel (models/content_types.py:1047) wire() returns a bare markdown string (GH-179). A consumer that validates against the advertised schema rejects prose artifacts. The names themselves all match the mapper literals, so there is no routing mismatch.
- Fix: Declare data as oneOf object or string in _CUSTOM_EVENT_SCHEMAS.

### P-003 (low) — AG-UI — proto:agui
- Rule: Run must be cancelled when the stream ends with a synthesized RUN_ERROR
- Description: agent_sdk/routes/ag_ui.py:728-737 skips cancellation whenever mapper.terminal_sent is true. That is correct for an interrupt RUN_FINISHED. But the serialization-failure branch in _emit (line 721-722) and the catch-all at line 880-881 also set terminal_sent through run_error. In both cases the worker task keeps running, with possible tool side effects, after the client has been told the run failed.
- Fix: Track whether the terminal frame was a parked interrupt. Cancel the task for every RUN_ERROR that the worker did not itself report.

### P-004 (low) — AG-UI — proto:agui
- Rule: RunAgentInput: required fields and tools/context handling
- Description: Lenient parsing: threadId and runId are silently replaced when missing, empty or non-string (lines 694-697). state, tools, context and forwardedProps are not validated. tools (frontend tool definitions) and context are ignored, so Static GenUI through client-defined tools cannot work. Messages with role tool, system or developer, and assistant toolCalls in history, are dropped by _fold_history. Resume entries with no status are accepted. These are deliberate leniencies (GH-97), but they depart from the schema. Resume reads accept both interruptId and interrupt_id (line 583), while the wire emits camelCase only, which is fine.
- Fix: Document in docs/protocols.md that tools and context are ignored. Optionally log a warning when a non-empty tools list is received.

### P-005 (low) — AG-UI — proto:agui
- Rule: AG-UI advertisement form (traps 13 and 14)
- Description: The card emits both forms. The extension uses the URI https://agent-sdk.dev/extensions/ag-ui-run/v1 rather than urn:agui:run:v1 (agent_card.py:174), and the top-level x-agui block carries transport, endpoint and customEvents (line 225). The endpoint is explicit in both, so trap 14 is clear. A consumer that detects only urn:agui:run:v1 would miss the extension, though x-agui still works.
- Fix: Document in docs/protocols.md which form consumers should trust. Optionally add a second extension entry with the urn:agui:run:v1 URI.

### P-006 (low) — AG-UI — proto:agui
- Rule: SSE response headers
- Description: agent_sdk/common/sse.py sets Connection: keep-alive in SSE_HEADERS. This hop-by-hop header is forbidden on HTTP/2 responses (RFC 9113 8.2.2). Behind an HTTP/2-terminating proxy it can cause stream resets. The wire framing itself is correct: bare data: lines only, no event: or id: lines, and a : ping comment as the heartbeat.
- Fix: Drop Connection: keep-alive from SSE_HEADERS. HTTP/1.1 keeps the connection alive by default.

### P-007 (medium) — A2UI — proto:a2ui
- Rule: RESERVED types: data_type names are allocated, not only component names (Profile v1.1 Status legend; trap #17)
- Description: agent_sdk/models/content_types.py:1585-1589 (register_content_type) refuses only the four RESERVED component names (and their case variants). The Profile allocates the name, tier AND data_type of each RESERVED type (trade_activity, company_info, deal_list, investor_profile). Nothing refuses those data_type strings. I ran it: a domain card with component 'TradeFeed' and data_type 'trade_activity' registers without error. A later Profile version that freezes TradeActivity would then collide with an already-shipped domain data_type. data_type is also never checked for snake_case (a data_type of 'Bad-Type' registers), although the Profile says internal data_type is snake_case.
- Fix: In register_content_type, add RESERVED_DATA_TYPES = ('trade_activity','company_info','deal_list','investor_profile') and raise ValueError when data_type is in it. Add a re.fullmatch(r'[a-z][a-z0-9]*(_[a-z0-9]+)*', data_type) check. Add tests next to the existing reserved-component tests.

### P-008 (low) — A2UI — proto:a2ui
- Rule: Frozen field contracts: SDK extension fields ride on the wire beyond the contract (trap #16 boundary; v1.1 'receivers ignore unknown fields' assumption)
- Description: The wire carries keys that are not in the frozen v1/v1.1 contracts: EntityList.title and showing (content_types.py:932-933), ComparisonTable.sort_by and sort_order (867-868), ColumnDef.unit, highlight and is_id (835-837), CalendarEvent.is_online (1340), DocumentItem.modified_by (1485; test_gh177 confirms it is emitted). All are documented as SDK extensions except modified_by: the DocumentItem serializer docstring (1491-1493) says the contract keys are id/name/type/modified/link/size and does not mention that modified_by stays on the wire (only docs/content-types.md:362 does). This is safe only while every receiver ignores unknown fields. The Profile v1.1 note says the same: a strict v1 renderer that rejects unlisted fields would break.
- Fix: Add modified_by to the DocumentItem docstring and the GH-177 serializer comment. Keep the extension list in one place (module docstring) so it cannot drift. No wire change needed unless a strict third-party renderer is a target.

### P-009 (low) — A2UI — proto:a2ui
- Rule: Compact schema accuracy: optional fields omitted or under-specified in the teaching string
- Description: I compared every _COMPACT_SCHEMAS entry with the models' wire-required rules (_wire_required) by script. There are zero '?' mismatches: no optional field is marked required, and no required field is marked optional. All 14 entries cover every required field. The compact strings do leave out some optional Profile fields: TimeSeriesChart x_label, y_label, summary (catalog.py:293); MultiCategoryChart chart_config (305); EmailMessage conversation_id (309; it appears only in the code comment on line 308). UserProfile (316) is a deliberate partial schema: presence lists only availability and activity (status_message missing, availability typed as bare str instead of the 13-value enum), out_of_office lists only is_enabled, and business_phones is typed bare 'list' instead of [str]. Nothing here is wrong, only incomplete. The header says 'common optional fields shown', so this is acceptable.
- Fix: Optional: add conversation_id?:str to EmailList, x_label?/y_label?/summary? to TimeSeriesChart, and [str] to business_phones. Keep the 250-char budget in mind for the _field_summary fallback path.

### P-010 (low) — A2UI — proto:a2ui
- Rule: Profile datetime rule: UTC ISO 8601 with trailing Z (CalendarEvents, EmailList)
- Description: The Profile says all datetimes are UTC ISO 8601 with trailing Z. content_types.py only comments this (EmailMessage.received_at line 1272, CalendarEvent.start/end lines 1326-1327) and types the fields as plain str. A tool can emit a local offset or a bare date and it still passes. Structural conformance does not check value semantics, so this is not a violation. It is only a gap between the comment and the code.
- Fix: Optional: add a before-validator that accepts ISO 8601 and normalises offsets to Z, or state in the docs that tools own the UTC normalisation.

### P-011 (low) — A2UI — proto:a2ui
- Rule: Delivery metadata: a2ui_extension can advertise an empty supportedCatalogIds
- Description: catalog.py:476-485 builds the A2UI agent-card extension with params supportedCatalogIds, acceptsInlineCatalogs=false and dataEncoding='data.messages'. These match the Profile guidance for the object-wrapped DataPart form and the v0.9.1 extension URI. I ran a2ui_extension(None, []) and it returns supportedCatalogIds=[]. The caller (routes/agent_card.py:169-170) gates only on a2ui_enabled, even though its docstring says the extension is left off when there is no catalog to advertise (GH-249). If that gate ever disagrees with the emits list, the card advertises A2UI with no catalog.
- Fix: Have a2ui_extension return None, or have the caller skip it, when supported_catalogs() is empty, so the guarantee does not depend on a separate flag.

### P-012 (medium) — A2A — proto:a2a
- Rule: D2 error-code to REST status mapping (-32004 UnsupportedOperation must be 501)
- Description: Role audited: server only (D1-D6); D7 consumer is N/A for these four files. Hard-MUST verdict: server is 0.3.0-compliant (card, message/send, tasks/get, tasks/cancel, Task/TaskState, header auth all present). One deviation from the spec REST table: agent_sdk/routes/a2a.py:605-609, :612 and :1050-1054 return -32004 with HTTP 400 (terminal-task or not-awaiting-input re-message), while the spec table and agent_sdk/models/errors.py A2A_HTTP_STATUS say UnsupportedOperation is 501. The same code is 501 at a2a.py:1209-1213 (colon id on GET) and 405 via app.py _A2A_CODE. So one JSON-RPC code now has three HTTP statuses on this surface. This is the ratified GH-266 ruling (CHANGELOG, uncommitted work in w067), so it is a known, deliberate deviation, not an accident. The MUST (return an error, never silently start a new task) is met.
- Fix: Keep the ruling but record it as an explicit spec deviation in docs/protocols.md and the card or a conformance note. Alternatively revert to 501 and let clients key on error.code == -32004. Clients must key on the code, not the status.

### P-013 (low) — A2A — proto:a2a
- Rule: D3 server-emitted Message.contextId is REQUIRED
- Description: agent_sdk/routes/a2a.py:963-968 (_unserializable_tail) builds the agent status Message with only role, parts and messageId. It has no contextId and no taskId. The same function's own TaskStatusUpdateEvent carries contextId, and agent_sdk/agent/runner.py:106-113 correctly sets both on every other agent Message. Error path only, but the spec says a server-emitted Message must always carry contextId.
- Fix: Add taskId=record.task.id and contextId=record.task.context_id to that Message.

### P-014 (low) — A2A — proto:a2a
- Rule: D3 Message object completeness (referenceTaskIds)
- Description: agent_sdk/models/a2a.py Message has no referenceTaskIds field (a v0.3.0 Message field). Inbound values are silently dropped (pydantic ignores extras), so the history copy made at a2a.py:568 and :633 loses them, and the server cannot emit them.
- Fix: Add referenceTaskIds: list[str] | None (alias referenceTaskIds) to Message.

### P-015 (low) — A2A — proto:a2a
- Rule: D1 optional card fields and interface declaration
- Description: agent_card.py builds the card with preferredTransport HTTP+JSON (default emitted), url from PUBLIC_URL (https enforced in prod by config.py:353), protocolVersion 0.3.0, tags on every skill, oauth2 using flows plus oauth2MetadataUrl, and OR-of-ANDs security. All PASS. Gaps are optional only: no additionalInterfaces entry repeating the HTTP+JSON url (declared and served match, so this is not a finding against the field-trap rule), and AgentCard has no documentationUrl, iconUrl, signatures or provider. Served at both /.well-known/agent-card.json and agent.json, unauthenticated, ETag and 304 handled.
- Fix: Optionally add additionalInterfaces=[{transport:'HTTP+JSON', url:base_url}] and model the optional card fields.

### P-016 (low) — A2A — proto:a2a
- Rule: D1 defaultInputModes vs accepted input
- Description: agent_card.py:204 declares defaultInputModes ['text/plain'] only, but a2a.py:413-428 (_resume_value, GH-193) accepts a single DataPart on resume. A client reading the card would not know a data part is accepted.
- Fix: Add application/json to defaultInputModes, or document that data resumes are an SDK extension.

### P-017 (low) — A2A — proto:a2a
- Rule: D2 tasks/list (REST GET /v1/tasks)
- Description: a2a.py:1099-1121 serves tasks/list and is identity-scoped. It ignores any contextId, status or historyLength query parameters without error, so a client filtering by contextId silently gets every task. The response envelope (tasks, totalSize, pageSize, nextPageToken) goes beyond the digest's 'Task[]'. This is unverified against the exact 0.3.0 schema, so treat it as a caution, not a failure.
- Fix: Either honour contextId and status, or reject unknown filter parameters with -32602. Confirm the list envelope against a2a.json at the v0.3.0 tag.

### P-018 (low) — A2A — proto:a2a
- Rule: D5 auth surface
- Description: PASS overall. require_identity (auth/middleware.py:144) runs on every /v1 data route and the card is unauthenticated. A missing bearer gives 401 with WWW-Authenticate pointing at the bare PRM, a bad bearer adds error="invalid_token", rate limiting gives 429 with Retry-After, and /v1/* HTTPExceptions are wrapped into {error:{code,message}} with headers kept (app.py:921-928). Credentials are header-only. Push config routes answer -32003 with 501 after auth. Only nit: 403 from require_api_key_identity and require_admin (middleware.py:168-177) carries no WWW-Authenticate. That is allowed by the spec. oauth.py is not part of the A2A wire surface. Its metadata is consistent with the card: oauth2MetadataUrl resolves to the AS metadata, authorizationUrl and tokenUrl match, and scopes are empty on both sides.
- Fix: None required.

### P-019 (low) — A2A — proto:a2a
- Rule: D3/D4 shapes, streaming and error codes (verified PASS)
- Description: Verified PASS: Task, Message, Part (kind discriminator), Artifact (artifactId), FilePart bytes-XOR-uri, TaskState values with american 'canceled', camelCase wire. Streaming sends a full Task snapshot first, then status-update and artifact-update events, ends with final:true, and a terminal task gets snapshot plus a closing final status. A severed or unserializable frame closes with a failed final:true event. Error codes: -32001 gives 404, -32002 gives 409, -32003 gives 501, -32005 gives 415, -32006 gives 502, -32007 gives 501 after auth. message/send can return a bare Message through the sync_reply hook (a2a.py:735-747), and it carries contextId. Terminal re-message returns an error (-32004) and never starts a new task. Note: tasks/resubscribe on an already terminal task returns snapshot plus final instead of an error; the spec does not require an error, so this is acceptable.
- Fix: None required.

### P-020 (medium) — MCP — proto:mcp
- Rule: D5 / mcp-protocol.md §11 (RFC 8707): token aud must be checked at use against THIS resource
- Description: Audience is validated at issue and persisted, but at use OAuthTokenStore.verify() (agent_sdk/auth/oauth_tokens.py:566-588, called from agent_sdk/auth/middleware.py:131) only checks that aud is in the two-value set {issuer, issuer/mcp}. It never compares the token's aud with the surface being called. A token minted with resource=<base>/mcp is accepted on /v1/* (A2A) and /ag-ui/*, whose PRM says resource=<base> (agent_sdk/routes/oauth.py:176-190). A token minted with aud=<base> is accepted on /mcp, which advertises resource=<base>/mcp. The set is a documented deviation because Claude.ai sends the bare origin, but audience is not enforced per surface. Same server, so this is not token passthrough. Hard MUST 7 is substantially met; this is a tightening, not a blocker for Claude.ai.
- Fix: Pass the expected audience set per surface into verify(). Require {canonical_resource, issuer} on /mcp if bare-origin equivalence must stay. Require {issuer} on /v1 and /ag-ui, and reject aud=<base>/mcp there. Add a cross-surface rejection test.

### P-021 (medium) — MCP — proto:mcp
- Rule: D5 / P1 / P9.2: an invalid or expired bearer must yield 401 + WWW-Authenticate so the client can refresh or re-discover
- Description: agent_sdk/auth/middleware.py:131-136 checks bearer_limiter (30/min fixed window, keyed by client IP) BEFORE raising the 401. Once the bucket is exhausted, a bad or expired token gets _rate_limited(), a bare 429 with Retry-After and no WWW-Authenticate (middleware.py:99-102). Claude.ai connects from shared server-side egress IPs, and OAuth access tokens are memory-only (oauth_tokens.py header). After a restart every connector presents a dead token at once, and 30+ failures in one minute from a shared IP turn the 401 into a 429. Clients may treat the 429 as transient and not start the refresh or re-auth flow. The same shared-IP concern applies to unauth_limiter on /oauth/token (30/min), which is how those clients would recover.
- Fix: Always emit the 401 + WWW-Authenticate for a bad bearer. Apply the limiter only as a secondary throttle, for example a much higher cap or a key that includes more than the IP, or 429 only after a large threshold. Alternatively persist access tokens, or raise limits when trusted_proxies is unset.

### P-022 (medium) — MCP — proto:mcp
- Rule: D1 / D6 / P9.1: gate every version-future field on the negotiated version; honour batching at 2025-03-26
- Description: SUPPORTED_PROTOCOL_VERSIONS = (2025-11-25, 2025-06-18, 2025-03-26) (agent_sdk/routes/mcp.py:148) advertises 2025-03-26, but only serverInfo.title is version-gated (mcp.py:575-584, correct per the stated policy). tools/list emits tool.title (mcp.py:770) and outputSchema (mcp.py:773-775), and tools/call emits structuredContent (mcp.py ~1085), in every negotiated version. All of these were introduced in 2025-06-18. A session negotiated at 2025-03-26 with a strict-schema client sees version-future fields (the P9.1 failure class). Conversely, 2025-03-26 defines JSON-RPC batching, and the server answers an array body with -32600 (mcp.py:1148-1152). That is correct for 2025-06-18+ but not for sessions that negotiated 2025-03-26. Claude.ai negotiates 2025-06-18 or later, so there is no connect risk for the target surface.
- Fix: Either drop 2025-03-26 from SUPPORTED_PROTOCOL_VERSIONS (simplest, since the baseline is 2025-06-18) or carry the session's negotiated version into tools/list and tools/call and strip title/outputSchema/structuredContent at 2025-03-26. Also decide explicitly on batching at that version.

### P-023 (low) — MCP — proto:mcp
- Rule: D2 / P5: tool annotations and titles
- Description: agent_sdk/agent/registry.py:531-536 and :618-645 seed annotations only when read_only=True (readOnlyHint + destructiveHint:false). Otherwise only openWorldHint is set. A non-read-only tool therefore advertises neither readOnlyHint nor destructiveHint, and the spec default destructiveHint=true applies. That is safe but imprecise. tools/list omits title when entry.title is empty (mcp.py:769-770), and the Directory requires title plus the applicable hint. The built-in load_skill tool is fine (mcp.py:684-698).
- Fix: Make non-read-only tools declare destructiveHint and idempotentHint explicitly, and require or default title (for example from the name) so Directory submission passes.

### P-024 (low) — MCP — proto:mcp
- Rule: D1: serverInfo.title version gate (policy check)
- Description: PASS against the requested policy. _handle_initialize emits serverInfo.title only when index(version) <= index('2025-11-25'), which is 2025-11-25 only (mcp.py:575-584). It is absent at 2025-06-18 and 2025-03-26, and serverInfo.icons is never emitted. This is stricter than the spec, because mcp-protocol.md §2 says title is valid from 2025-06-18. The code documents this as a GH-43 conservative choice. The newest-first invariant is guarded with a bare assert (mcp.py:151-153), which is stripped under python -O and depends on index order.
- Fix: Optional: replace the assert with an explicit check or a version-date comparison (dates sort lexicographically), and re-test live to see whether the gate can drop to 2025-06-18.

### P-025 (low) — MCP — proto:mcp
- Rule: D4 / mcp-protocol.md §10: unknown or invalid session id handling
- Description: An Mcp-Session-Id longer than 64 chars returns 400 (mcp.py:1176-1182, :1272-1279, :1355-1364). The spec says an unknown, expired or invalid session gets 404, which lets the client re-initialize. A real client never sends a >64 char id, so this is only an edge case. Otherwise the transport is PASS: single endpoint with POST/GET/DELETE, 202 for notifications and responses, GET returns text/event-stream, an absent MCP-Protocol-Version is accepted (GH-200), an unsupported one is 400, Origin is validated with 403, and session ids are owner-bound uuid4. initialize echoes a supported client protocolVersion and otherwise returns the newest. Unknown tool is -32602, and tool failures are isError:true results.
- Fix: Return 404 for an oversized id (still without echoing it).

### P-026 (low) — MCP — proto:mcp
- Rule: D5 / P1: discovery for path-prefixed PUBLIC_URL and newer discovery paths
- Description: AS metadata is served only at the root path /.well-known/oauth-authorization-server (agent_sdk/routes/oauth.py:193-215). The PRM resource_metadata URL is passed explicitly in WWW-Authenticate, so that is fine. If PUBLIC_URL carries a path prefix (a gateway deployment, app.py:708-719), the issuer has a path. RFC 8414 clients then look at /.well-known/oauth-authorization-server/<path>, and the 2025-11-25 spec also expects an OIDC-discovery fallback. Neither route exists. client_id_metadata_document_supported (CIMD) is not advertised, which is optional because DCR is offered. For the root-origin Claude.ai topology the chain is PASS: real 401, path-suffixed and bare PRM, code_challenge_methods_supported [S256], DCR, exact redirect_uri match, S256-only PKCE with a constant-time compare, single-use codes, refresh rotation with reuse detection, and scope omitted when empty.
- Fix: For path-prefixed deployments add the path-inserted AS metadata route. Optionally add /.well-known/openid-configuration and CIMD advertisement for 2025-11-25 clients.

### P-027 (low) — MCP — proto:mcp
- Rule: D8 / P1: portability of redirect URIs and CORS exposure
- Description: _valid_redirect_uri accepts only https, or http on localhost/127.0.0.1 (oauth.py:322-335 and :432). Native-app custom schemes used by some MCP hosts (vscode://, cursor://) are rejected at DCR. This is a deliberate security choice, and Claude.ai (https://claude.ai/api/mcp/auth_callback), Claude Code and Desktop loopback callbacks all pass. CorsMiddleware (agent_sdk/common/cors.py:25-30) correctly exposes WWW-Authenticate and Mcp-Session-Id and answers preflight with 204, but it does not expose MCP-Protocol-Version or Retry-After to browser clients. That is harmless for Claude.ai.
- Fix: Optional: add MCP-Protocol-Version and Retry-After to Access-Control-Expose-Headers. Document the redirect-scheme limit for third-party hosts.

### P-028 (medium) — SEAM — proto:seam
- Rule: MCP version negotiation: per-session version binding
- Description: agent_sdk/routes/mcp.py mcp_post (around lines 1150-1196): when a request carries a valid MCP-Protocol-Version header, the code accepts it even if it differs from the version recorded for that Mcp-Session-Id at initialize. A session negotiated at 2025-06-18 can send 'MCP-Protocol-Version: 2025-11-25' (or 2025-03-26) and the server echoes that header back. The session record (last_seen, owner, version) is only read when the header is absent (GH-200 path). So the server-side record of the negotiated version is not authoritative, and the response header can disagree with what initialize returned.
- Fix: When a presented session exists and the header is present, compare it to rec[2]; on mismatch return 400 'unsupported MCP-Protocol-Version' (or at least echo rec[2], not the header value). Add a test: initialize at 2025-06-18, then tools/list with header 2025-11-25 on the same session.

### P-029 (low) — SEAM — proto:seam
- Rule: Version strings consistent across routes (MCP response header)
- Description: agent_sdk/routes/mcp.py mcp_post early-exit responses (415 bad Content-Type ~line 1120, 413 body too large ~1131, parse error ~1138, invalid request ~1143, unsupported-version 400 ~1159) always send 'MCP-Protocol-Version: 2025-11-25' (SUPPORTED_PROTOCOL_VERSIONS[0]), even for a live session that negotiated 2025-06-18 or 2025-03-26. The success path sends the session's version. So one session can see two different version headers depending on whether the request failed early.
- Fix: Resolve the effective version (header if valid, else session record, else newest) before the early returns, or omit the header on transport-level errors rather than claiming the newest version.

### P-030 (low) — SEAM — proto:seam
- Rule: Auth mode enforced uniformly: per-surface resource/audience
- Description: agent_sdk/auth/middleware.py _unauthorized sends /mcp callers to the path-suffixed PRM (resource = {base}/mcp) and /v1, /ag-ui callers to the bare PRM (resource = {base}). But OAuthTokenStore.verify (agent_sdk/auth/oauth_tokens.py ~line 577) accepts BOTH audiences on every surface, and require_identity does not check which audience the token carries. A token minted for {base}/mcp works on A2A and AG-UI, and a token minted for the bare origin works on /mcp. The per-surface PRM split therefore advertises a resource boundary that is not enforced. This is consistent with the documented two-value equivalence set (Claude.ai sends the bare origin), so it is a documentation/expectation gap more than a bug.
- Fix: Either document in DESIGN.md §5.5/§10.3 and docs/protocols.md that both PRM resources are interchangeable audiences accepted on all three surfaces, or bind audience to surface in require_identity (MCP accepts both; /v1 and /ag-ui accept the bare origin) if a real boundary is wanted.

### P-031 (low) — SEAM — proto:seam
- Rule: Version strings consistent: console A2UI extension URI
- Description: agent_sdk/console/static/chat.js line 362 detects the A2UI extension on the card by substring ('a2ui.org/a2a-extension/a2ui/', any version), but line 413 then sends a hard-coded 'X-A2A-Extensions: https://a2ui.org/a2a-extension/a2ui/v0.9.1' and lines 407/601/616 send a hard-coded version 'v0.9.1'. The server constants live in agent_sdk/models/content_types.py (A2UI_EXTENSION_URI, A2UI_VERSION). If the server URI changes, the console will still see A2UI as advertised but send a URI the A2A route (_a2ui_header, exact match) does not recognise, so A2UI silently turns off on the A2A path while the AG-UI path keeps working.
- Fix: In chat.js, keep the matched card entry and send ext.uri as the X-A2A-Extensions value; derive the version token from that URI (or from an x-sdk field on the card) instead of a literal.

### P-032 (low) — SEAM — proto:seam
- Rule: Version strings consistent across docs
- Description: DESIGN.md §1 table (line 33) says MCP 2025-11-25 is the primary version with 2025-06-18 and 2025-03-26 also accepted, and docs/protocols.md line 163 lists all three, but the DESIGN.md §5.5 heading (line 374) still reads 'MCP (2025-06-18) + OAuth 2.1'. DESIGN.md line 383 also says 'only serverInfo.title/icons in initialize are gated', but routes/mcp.py _handle_initialize never emits icons for any version (the docstring says icons are left out entirely because Claude.ai rejects them).
- Fix: Retitle DESIGN.md §5.5 to name the supported version set (2025-11-25 / 2025-06-18 / 2025-03-26), and change 'serverInfo.title/icons' to 'serverInfo.title (icons are never sent)'.

### P-033 (low) — SEAM — proto:seam
- Rule: Auth/origin enforced uniformly across A2A surface
- Description: agent_sdk/routes/agent_card.py GET /v1/card (extended_card) requires identity but, unlike every other /v1/* handler in routes/a2a.py and every /mcp and /ag-ui handler, does not call guard_origin(request). A browser request from a non-allow-listed Origin gets the -32007 reply instead of the 403 'origin not allowed' that every other authenticated route returns. Impact is small (constant reply, no data), but it breaks the 'every browser-reachable authenticated route is origin-guarded' invariant stated in agent_sdk/common/origin.py.
- Fix: Add request: Request and guard_origin(request) to extended_card, and add it to the origin-guard coverage test.

---

Autoloop cycle 3 (2026-10-25): mediums verified at v0.24.0; still-present ones filed as #268–#274 (testing #268, AG-UI/console #269, A2UI #270, A2A #271, auth #272, MCP #273, example/tests/registry #274). P-022 not filed (conflicts with #246 ruling). Lows not filed.
