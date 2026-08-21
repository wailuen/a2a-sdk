# Red-team review log

Standing process: every step is red-teamed by the relevant specialist agent(s) before the next step begins. This file records each round and the disposition of every finding.

## Round 1 — DESIGN.md v1 → v2 (2026-06-10)

Reviewers (parallel): `a2a-advisor`, `ag-ui-advisor`, `a2ui-advisor`, `mcp-advisor`, architecture/security generalist. Verdict on v1: **not ready** — 12 blockers, ~30 majors. All findings below are **accepted and applied in DESIGN.md v2** unless marked otherwise.

### A2A advisor

| # | Sev | Finding | Disposition (v2 §) |
|---|---|---|---|
| 1 | BLOCKER | Error table missing -32003/-32007; -32004 misnamed | full 7-code table §5.1 |
| 2 | BLOCKER | message:send returns HTTP 200, not 202 (v1 doc was wrong; references + spec agree) | §5.1 |
| 3 | BLOCKER | message/send result is `Task \| Message`, not always Task | §5.1 |
| 4 | MAJOR | `supportedInterfaces` is v1.0-only; use `additionalInterfaces` (transport+url pairs) | §4.5; listed as reference defect §1 |
| 5 | MAJOR | AgentSkill must carry spec fields only; SDK extras → `x-sdk.*` | §4.5 |
| 6 | MAJOR | Phantom "enhanced-content-types" extension URI with no negotiation path | dropped; x-sdk fields instead §4.5 |
| 7 | MAJOR | `MessageSendConfiguration` untyped; pushNotificationConfig must map to -32003 | typed model §5.1 |
| 8 | MAJOR | input-required/auth-required resume flow undesigned (action_gate depends on it) | resume-by-taskId flow §5.1 |
| 9 | MAJOR | Card must include `url` in prod; never `preferredTransport` without `url` | §4.5 |
| 10 | MAJOR | TaskStatus wire = {state, message?, timestamp?} only — internal fields must be stripped | whitelist rule §5.1 |
| 11 | MINOR | Bare SSE frames (no JSON-RPC envelope) should be documented as transport-specific | §1 non-goals |
| 12 | MINOR | tasks/list → 501 + -32004 | §5.1 |
| 13 | MINOR | Server contextId always non-empty UUID | §5.1 |

### AG-UI advisor

| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | BLOCKER | RunAgentInput state/tools/context/forwardedProps are REQUIRED per spec | required-in-schema, lenient-default §5.3 |
| 2 | BLOCKER | Console must route ALL declared CUSTOM names (investment_analyst console drops AGENT_ARTIFACT) | card↔routing-table parity unit test §5.3, §7 |
| 3 | BLOCKER | CUSTOM payload shapes diverge across references; must freeze | frozen table §5.3 (AGENT_NOTE={note}, pitchbook shape) |
| 4 | BLOCKER | Validation must run inside the SSE generator so RUN_STARTED is always first + Content-Type always text/event-stream | m365 pattern adopted §5.3 |
| 5 | MAJOR | STEP pair per Bedrock turn, step_name=turn-{n}, guaranteed close | §5.3 |
| 6 | MAJOR | Emit STATE_SNAPSHOT baseline after RUN_STARTED | snapshot=input.state ?? {} §5.3 |
| 7 | MAJOR | Truncate oversized history, don't reject; skip blank assistant turns | §5.3 |
| 8 | MAJOR | x-agui card block is non-normative — document as deliberate; detector accepts both conventions | §4.5 |
| 9 | MINOR | ToolCallResultEvent.message_id = fresh UUID (m365/inv-analyst fabricate from tool_call_id) | §5.3; reference defect §1 |
| 10 | MINOR | A2UI_UPDATE value = {messages:[...]} wrapper | §5.3, §5.4 |
| 11 | MINOR | action_gate AG-UI path = RUN_FINISHED interrupt outcome + RunAgentInput.resume, not custom events | §5.3 |
| 12 | MINOR | No THINKING_* (deprecated); REASONING_* reserved | §5.3 |

### A2UI advisor

| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | BLOCKER | Wire name is TimeSeriesChart; class/wire mapping must be exact | class name == wire name policy §4.3 |
| 2 | BLOCKER | Doc listed 9/18 Standard Profile types | all 14 FROZEN + 4 RESERVED enumerated §4.3 |
| 3 | BLOCKER | createSurface catalogId must be urn:a2ui-profile:standard:v1; pitchbook's private-market ID was a defect; v1 §4.3 example collided | §5.4; defect listed §1 |
| 4 | MAJOR | deleteSurface = 4th message in EACH artifact's array, not at task completion | §5.4 |
| 5 | MAJOR | Extended tier gate set must be the full 8-type list | enumerated §5.4 |
| 6 | MAJOR | KpiCard/TimeSeriesChart wire contracts ≠ v1 doc's internal models | models made wire-isomorphic §4.3 (also kills the drift class) |
| 7 | MAJOR | MarketBriefing wire data = markdown string via to_plain_text/to_markdown; prose rendering | §4.3, §7.1 |
| 8 | MAJOR | Console Path-A renderer underspecified (registry, atomic fold-then-paint, RFC 6901, delete ordering) | §7.1 |
| 9 | MINOR | Capability paths per transport; routes extract tier, translators never read transport metadata | §5.4 |
| 10 | MINOR | MIME application/a2ui+json emit-only; legacy accepted inbound | §5.4 |
| 11 | MINOR | Domain negotiation via capabilities.catalogs; card supportedCatalogIds lists both | §5.4, §4.5 |

### MCP advisor

| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | BLOCKER | PRM `resource` must be absolute canonical URI {PUBLIC_URL}/mcp | §5.5 |
| 2 | BLOCKER | Version negotiation: echo client's if supported, else server's highest; client decides | §5.5 |
| 3 | MAJOR | @tool(emits=) must derive outputSchema for tools/list | §5.5, §4.1 |
| 4 | MAJOR | Full CORS table incl. Expose-Headers WWW-Authenticate; OPTIONS→204 (Starlette patch) | §5.5 |
| 5 | MAJOR | RFC 8707 resource param at authorize+token, persisted, audience-checked | §5.5 |
| 6 | MAJOR | Path-suffixed PRM /.well-known/oauth-protected-resource/mcp (Claude probes first) | §5.5 |
| 7 | MAJOR | Audience enforcement = hard 401, never log-and-allow | §5.5 |
| 8 | MAJOR | Identity kind tagging; admin surfaces reject oauth kind; consent needs real API key | §5.5, §6 |
| 9 | MINOR | GET /mcp → text/event-stream, not 405 (Claude.ai Desktop) | §5.5 |
| 10 | MINOR | DELETE /mcp → 204 idempotent | §5.5 |
| 11 | MINOR | MCP-Protocol-Version header validation (400 invalid; absent behavior transport-split — Streamable HTTP non-init→400, Legacy SSE→assume 2025-03-26; GH-77) | §5.5 |
| 12 | MINOR | CI: curl OAuth-chain probes + live port + `claude mcp add` release gate | §12 |
| 13 | MINOR | Omit empty scope from token response; code_challenge_methods_supported ["S256"] | §5.5 |

### Architecture / security

| # | Sev | Finding | Disposition |
|---|---|---|---|
| 1 | BLOCKER | Global @tool registry via import side effects (test pollution, silent zero-tool boot) | explicit ToolSet collector + agent.register_catalog; dup/unresolved raise at build_app §4.1 |
| 2 | BLOCKER | git+ssh dependency fails inside Docker builds | BuildKit --mount=type=ssh template + SHA pinning + HTTPS-token variant + wheel graduation path §10.1 |
| 3 | MAJOR | Single-process invariant implicit | explicit §2; WEB_CONCURRENCY refused §4.4 |
| 4 | MAJOR | Bootstrap TOFU race (open key-minting window) | one-time bootstrap token §6 |
| 5 | MAJOR | No rate limit on unauthenticated paths; unbounded DCR | per-IP windows + DCR cap §6, §5.5 |
| 6 | MAJOR | MASTER_KEY rules weak; KDF unpinned; no rotation | ≥32 generated chars, PBKDF2≥600k+salt, rotation CLI §6 |
| 7 | MAJOR | Console auth/CSP/sanitization unstated | header-bearer-only invariant, strict CSP, frame-ancestors none, sanitization as tested invariant §7 |
| 8 | MAJOR | SSRF guards were CLAUDE.md prose, not library code | allowed_hosts, url CredentialField validation, path_param enforcement §4.2 |
| 9 | MAJOR | Adapter injection resolution timing/semantics undefined | resolved at build_app; annotation-driven; CredentialField model §4.1–4.2 |
| 10 | MAJOR | No API stability tiers; env namespace collisions | stable/provisional tiers + AGENT_SDK_ prefix §4.0 |
| 11 | MAJOR | No escape hatches | §10.3 (mount-after-build, lifespan_extras, root_path, asset shadowing, lower-bound deps) |
| 12 | MAJOR | Contrib modules unvalidated by the chosen port | experimental status §9 + m365 port gate §13 |
| 13 | MINOR | Settings at import time; SettingsConfigDict inheritance | make_settings() factory §4.1, §4.4 |
| 14 | MINOR | DEV_MODE + public PUBLIC_URL footgun | hard fail + enumerated relaxations §4.4 |
| 15 | MINOR | Credential namespace isolation (incl. Bedrock) | {source}/{field} + reserved namespace §6 |
| 16 | MINOR | Wheel asset packaging risk | importlib.resources + installed-wheel CI smoke §12 |
| 17 | MINOR | skills_dir cwd-relative footgun | anchored to caller file §4.1 |
| 18 | MINOR | Model calls starve to_thread pool; no cost guard | bounded executor + per-task deadline/token budget §8 |
| 19 | MINOR | Playwright mandatory leg too brittle; MASTER_KEY human-invented | optional leg §11; generated key §6/§10.2 |
| 20 | MINOR | CI model fidelity (hand-written fakes drift) | recorded Converse fixtures §12 |

External research: none required — every disputed point was resolved against reference-agent source or is internal to the frozen in-house profiles.

**Round 1 confirmation pass:** v2 sent back to all five reviewers — see Round 1b below.

## Round 1b — confirmation pass on v2 → v3 (2026-06-10)

Verdicts on v2: a2a APPROVE_WITH_MINORS · ag-ui APPROVE_WITH_MINORS · a2ui APPROVE_WITH_MINORS · mcp APPROVE_WITH_MINORS · arch/security **REJECT**. All Round-1 dispositions were confirmed correct; the items below are residuals and new issues. All are **applied in DESIGN.md v3** unless marked.

### A2A (new minors)

| Sev | Finding | Disposition (v3) |
|---|---|---|
| MED | `tasks/cancel` success return (`Task` in canceled state) undocumented | §5.1 |
| MED | Dev card omitted REQUIRED `url` → schema-invalid card, weakened CI | `url` never omitted; localhost fallback §4.5; CI boots with PUBLIC_URL §12 |
| LOW | cancel error paths ambiguous (404+-32001 vs 409+-32002) | both spelled out §5.1 |
| LOW | `blocking`→-32004 not spec-mandated | documented as local convention §5.1 |
| LOW | A2UI extension URI never named | exact string in §4.5 |
| LOW | AgentError read like a wire shape | marked internal-only, wire shape stated §5.1 |
| LOW | inbound `messageId` validation unstated; `supportsAuthenticatedExtendedCard` unstated | §5.1, §4.5 |

### AG-UI (new minors)

| Sev | Finding | Disposition (v3) |
|---|---|---|
| MINOR | `x-agui.endpoint` undefined when PUBLIC_URL unset | derives from same resolved base as `url` (localhost fallback) §4.5 |
| MINOR | STEP boundary detection relied on pitchbook's ProgressEvent regex | typed `TurnStartedEvent` added to loop catalog §2, §5.3 |
| LOW | interrupt shape missing `tool_call_id` (action_gate needs it) | added §5.3 |
| LOW | RUN_STARTED→STATE_SNAPSHOT→STEP_STARTED ordering implicit | explicit §5.3 |

### A2UI (residual + new)

| Sev | Finding | Disposition (v3) |
|---|---|---|
| MINOR | Renderer scope (ChildList, two-way binding, action dispatch) unstated | ChildList in; two-way binding + action dispatch explicitly out of scope v1 (no FROZEN type is interactive) §7.1 |
| MINOR | deleteSurface vs atomic-fold contradiction (fold-all would paint nothing) | defined as documented deviation: fold create/update atomically, paint once, apply delete post-paint (show-then-close); DOM persists as transcript snapshot §7.1, §5.4 |
| MINOR | `id:"root"` first-updateComponents requirement unstated | §5.4 |
| LOW | `to_plain_text()` required on all models but uncontracted | base-model ABC requirement §4.3 |

### MCP (residual + new)

| Sev | Finding | Disposition (v3) |
|---|---|---|
| HIGH | v2 claimed strict single-URI audience enforcement; pitchbook (and live Claude.ai, which sends bare origin) use two-value equivalence — v2 was internally inconsistent | explicit accepted set {origin, origin/mcp}, hard 401 outside it, documented RFC 8707 deviation + rationale §5.5 |
| MED | "resource required at token" would break Claude.ai (it doesn't send it there) | resource carried from code metadata; not re-required at token; authorize defaults it §5.5 |
| LOW | "required on all post-init requests" vs absent→default contradiction | transport-split (GH-77): Streamable HTTP non-init POST — absent→400 (effectively required); GET/DELETE — absent→allowed; Legacy SSE — absent→assume 2025-03-26 §5.5 |
| LOW | oauth-kind route policy ambiguous (revoke? token?) | routes enumerated; revoke = self-only; token unauthenticated §5.5 |
| LOW | CI missing unknown-session 404 probe | §12 |
| INFO | pitchbook structuredContent-without-outputSchema not in §1 defect list | added §1 |

### Architecture / security (REJECT drivers + residuals)

| Sev | Finding | Disposition (v3) |
|---|---|---|
| MAJOR | Task deadline keeps ticking during input-required pause → action_gate confirmations >10min fail by default | deadline suspends during interrupt states; token budget cumulative across resumes §8 |
| MAJOR | TTL/LRU eviction of paused task: worker leak, resume channel fate undefined | interrupted-task TTL (default 30min, own setting), excluded from LRU pressure, eviction cancels worker + closes channels §5.2 |
| MAJOR | No identity binding on task read/cancel/resume → cross-identity confirmation forgery | tasks record creating identity; read/subscribe/cancel/resume same-identity (admin override); mismatch → 404+-32001 §5.1 |
| MAJOR | HTTPS git-token variant leaks token (userinfo slot persists in PEP 610 direct_url.json; ARG lands in layers) | secret-mount only, password-slot URL form, --no-cache-dir, CI image token-leak assertion §10.1 |
| MAJOR | "root_path supported" factually wrong — well-known URIs are origin-rooted; mounted apps can't serve them | supported topology = one origin per agent; path-prefix needs documented proxy rewrites §10.3 |
| MAJOR | Adapter injection incomplete (instantiation, duplicates, match rule, source= redundancy) | SDK instantiates at lifespan with (settings, credential_resolver); once-per-class; exact-class match; `source=` kwarg dropped — annotations are the single source of truth §4.1 |
| MAJOR | Bootstrap token lifecycle (TTL, restart, lockout recovery) unspecified | 15-min TTL, restart regenerates, re-arms at zero keys, last-key protection (LRN-049) §6 |
| MAJOR | Unauth rate limiting: IP derivation behind LB unspecified; unbounded per-IP map | AGENT_SDK_TRUSTED_PROXIES + rightmost-untrusted XFF §4.4; bounded LRU §6 |
| MINOR | SSE queue overflow could silently drop final:true | overflow terminates that subscriber's stream (re-subscribe engages) §5.2 |
| MINOR | Auth-state persistence location unstated (restart killing connector registrations) | keys/clients/refresh tokens in encrypted store reserved namespaces; auth codes memory-only §6 |
| MINOR | ToolSet gaps (name derivation, no-input tools, reuse across Agents) | §4.1 |
| MINOR | WEB_CONCURRENCY check bypassable; rotate-master-key vs running server; httpx redirect SSRF bypass; DNS-rebinding TOCTOU | best-effort note §4.4; offline-only §6; redirects pinned off + per-hop recheck, TOCTOU documented-accepted §4.2 |

External research: none required (disagreements settled against reference code / live-connector behavior documented in pitchbook).

**Round 1b → v3 applied.**

## Round 1c — focused arch/security re-check of v3 (2026-06-10)

Verdict: **APPROVE** — all 12 Round-1b REJECT-driver rows verified resolved with implementable semantics; composition checks (deadline↔interrupt-TTL↔resume, identity binding vs console flows, bootstrap re-arm vs last-key protection) pass. Four residuals, three patched into v3 immediately:

| Sev | Residual | Disposition |
|---|---|---|
| MED-LOW | LRU exclusion for interrupted tasks was uncapped (interrupt flood pins unbounded workers) | `AGENT_SDK_MAX_INTERRUPTED` cap (default 100); at cap, new interrupt → typed task failure §5.2 |
| LOW | "re-arm doubles as disaster recovery" over-broad (store never reaches zero via revocation) | claim corrected; lost-plaintext recovery = documented out-of-band wipe with stated consequences §6 |
| LOW | AG-UI resume path not explicitly identity-bound | §5.1 binding applied to `RunAgentInput.resume` §5.3 |
| INFO | post-resume general-TTL clock behavior | left as implementation detail |

**Design phase sign-off: complete (v3). Next red-team checkpoint: after SDK core implementation — check skills + live curl probes per §12, before the investment_analysts_v2 port.**

## Round 2 — Conformance audit (2026-06-16, pre-v0.5.6)

Four-advisor /agent-stack-check static audit. All Critical/High findings fixed across three fix rounds. Verdict: **COMPLIANT** (zero Critical, zero High). Punch-list below — deferred items acknowledged per /sdk-test policy.

### Findings fixed in this round

| Protocol | Sev | Finding | Fix |
|---|---|---|---|
| A2A | HIGH | `GET /v1/tasks` was -32004 stub | Implemented `list_tasks_for_identity` in InMemoryTaskStore; `tasks_list` route |
| A2A | MED | `tasks/list` response used `totalCount`/`pageSize` missing | Corrected to `ListTasksResponse` shape: `totalSize`, `pageSize`, `nextPageToken` |
| A2A | MED | `preferred_transport`/`transport` were unconstrained `str` | Changed to `Literal["JSONRPC","GRPC","HTTP+JSON"]` |
| A2A | MED | HTTPS not enforced for public deployment | Added `_deployment_invariants()` check in `config.py`; loopback exempt |
| AG-UI | HIGH | `parentMessageId` absent on first tool call | Always emit (as null) in `ag_ui.py` |
| AG-UI | HIGH | Interrupt `expiresAt` not wired to wire | Three-file chain: `events.py` field → `runner.py` mutation → `ag_ui.py` wire |
| AG-UI | MED | Assistant history `content` was plain string | Changed to `[{type:"text", text:...}]` array in `chat.js`'s AG-UI assistant-turn fold-in (the `state.aguiMessages.push({ ... role: "assistant" ... })` block) |
| AG-UI | LOW | `if event.expires_at:` truthy guard | Changed to `if event.expires_at is not None:` in `ag_ui.py`'s interrupt-expiry guard (the `event.expires_at is not None` block) |
| AG-UI | LOW | Test resume entries used `status:"approved"` | Updated to `status:"resolved"` + `payload:{decision:"approved"}` in 3 test files |
| A2UI | CRITICAL | a2ui.js validation guard `!msg.type` always true | Removed `\|\| !msg.type \|\| typeof msg.type !== "string"` — A2UI messages have no `type` field |
| A2UI | HIGH | `updateComponents` ignored `id` — full replace instead of upsert | `_componentMap = new Map()` keyed by `component.id`; upsert semantics |
| A2UI | HIGH | Duplicate `createSurface` for open surface silently accepted | Added `else if (existing && !existing.closed)` guard with `console.warn` |
| A2UI | MED | `updateDataModel` null vs absent conflated | `MISSING` sentinel + `apply_data_model_update()` in `translator.py` |
| A2UI | MED | System prompt catalog missing compact schemas + examples | `_COMPACT_SCHEMAS` + `_FEW_SHOT_EXAMPLES` in `catalog.py` |
| A2UI | LOW | `catalog.py` docstring said "120 characters" | Corrected to "250 characters" |
| A2UI | LOW | `a2ui.js paintSurface` fell back to `components[0]` | Changed to visible `fallbackNode` with message |
| A2UI | LOW | `chat.js` MIME dispatch included `Array.isArray(part.data)` heuristic | Removed; dispatch on `mime` string only |
| MCP | HIGH | Tool name 64-char limit enforced only at `build_app()` | Also checked at `@tool` decoration time in `registry.py` |

### Deferred findings (acknowledged, non-blocking)

| Protocol | Sev | Finding | Rationale |
|---|---|---|---|
| MCP | MED | Bare PRM `resource` points to agent root (issuer), not canonical `{issuer}/mcp` | Intentional: A2A and AG-UI surfaces use the bare resource; MCP surface uses path-suffixed PRM. Two-value audience set handles both. Documented deviation from RFC 8707 single-URI strict reading; ADR 0001 §5.5. |
| MCP | LOW | Unknown tool returns `-32602` (InvalidParams) instead of `-32601` (MethodNotFound) | Minor: both codes are permissible for "tool not found"; -32602 is what Claude.ai connectors expect in practice. |
| MCP | LOW | `notifications/initialized` 202 via OR gate | Code quality only; no interop impact. Defer to refactor wave. |
| MCP | LOW | Tool name 64-char limit is Directory constraint (spec allows 128) | SDK applies it as a hard policy for Directory compatibility; applies to all tools, not just Directory-registered ones. Intentional safety margin. |
| A2A | LOW | Auth errors use `-32000` (non-enumerated code) | HTTP 401 status is authoritative; JSON-RPC code is informational. TCK does not enforce a specific code for auth failures. |
| A2UI | LOW | ChildList template expansion not implemented | By design: display-only renderer (Path A). Interactive ChildList requires two-way binding (out of scope v1 per DESIGN.md §7.1). |
| A2UI | INFO | `apply_data_model_update` server-side lacks delete path | Translator never emits `deleteSurface` mid-stream; the code path is not reached. |

**Round 2 sign-off: COMPLIANT. All Critical/High fixed. Deferred items acknowledged with rationale.**

---

## Round 3 — v0.5.12 release gate (2026-06-17)

`/agent-stack-check . --static-only` four-protocol fan-out. All seams S1–S6 PASS.

### Fixed in v0.5.12

| Protocol | Sev | Finding | Fix |
|---|---|---|---|
| MCP | — | `serverInfo.title` emitted under all protocol versions | Gated behind `2025-11-25` via the `_TITLE_MIN_VERSION` check in `mcp.py`'s `_handle_initialize()` |
| MCP | — | Abrupt SSE session cap (500) lacked queue bound | `_MAX_SSE_SESSIONS = 500` constant in `mcp.py`; bounded LRU |
| A2A | — | `DocumentList.to_plain_text()` ignored `type` and `last_modified` | Fixed in `content_types.py` |
| A2A | — | `Agent.__init__` missing `lifespan_extras` docstring | Added in `app.py` |
| Wave | — | Harness archive phase had no commit-intent guard | `ARCHIVE_INTENT_SCHEMA` + pre-archive check added to `harness/workflows/wave-cycle.js` |

### Deferred findings (acknowledged, non-blocking for v0.5.12)

| Protocol | Sev | Finding | File:line | Rationale |
|---|---|---|---|---|
| A2A | HIGH | `403 Forbidden` maps to `-32000` (spec has no dedicated authZ code) | `app.py`'s `_A2A_CODE` status→JSON-RPC map (the `403: -32000` entry) | Extends the existing Round 2 auth-error deferral (see above). HTTP 403 status is authoritative for authZ denial; JSON-RPC code is supplementary. The A2A v0.3.0 spec defines no named code for authZ failure — `-32000` is the only option in the implementation-defined slot. TCK does not enforce a specific code for authZ failures. A comment will be added in the follow-up hardening wave. |
| A2A | MED | `TaskStatus.error` non-spec field on wire without `AgentExtension` URI | `models/a2a.py`'s `TaskStatus.error` field | Field only emits when set (`exclude_none=True`); spec-compliant consumers ignore unknown fields. Registering a formal extension URI is hygiene, not interop-blocking. Track as GH issue. |
| A2A | MED | Tasks resubscribe route path is `:subscribe`, spec says `:resubscribe` | `routes/a2a.py`: the `tasks_resubscribe` route handler (`@router.post("/v1/tasks/{task_id}:subscribe")`) | Low real-world impact (`capabilities.stateTransitionHistory=false` means consumers rarely call resubscribe). Path rename is safe; file as GH issue with path alias for zero-downtime migration. |
| A2A | MED | Authenticated extended card at `/v1/card` (spec: `/v1/agent/authenticatedExtendedCard`) | `routes/agent_card.py`'s `extended_card()` handler (`@router.get("/v1/card")`) | `supportsAuthenticatedExtendedCard=false` — no spec-compliant consumer will call this path today. Path rename is safe; file as GH issue. |
| MCP | MED | OAuth-kind token → admin route rejection not fully verifiable statically | `auth/middleware.py`'s `require_api_key_identity()` guard | `require_api_key_identity` guard exists; enforcement is structural via FastAPI dependency injection. Gap is test coverage, not missing guard. Add integration test in follow-up. |
| A2UI | MED | `SurfaceRegistry.open()` warns on duplicate instead of raising | `a2ui/translator.py`'s `SurfaceRegistry.open()` | Affects opt-in streaming API only; stateless `translate()` (primary path) always generates a fresh `surfaceId` — unreachable. Make it a hard error in the streaming API hardening wave. |
| MCP | LOW | Batch request rejection uses `-32600` without an explicit `"batch not supported"` message | `routes/mcp.py`: `_INVALID_REQUEST` batch-rejection branch | Functionally correct; cosmetic only. Two-line fix; deferred to cleanup pass. |
| A2A | LOW | `TaskStatusUpdateEvent.final` has Python default `False` (spec marks REQUIRED) | `models/a2a.py`'s `TaskStatusUpdateEvent.final` field | Wire always emits the field (not `None`); conformant in practice. Default matches non-terminal semantics. API-breaking change to remove default; defer. |
| A2A | LOW | `blocking: bool \| None = None` accepts `null` (not a valid spec value) | `models/a2a.py`'s `MessageSendConfiguration.blocking` field | Internal SDK; callers do not send `null`. Tighten with validator in cleanup pass. |
| AG-UI | LOW | Dead `THINKING_*` case labels in console consumer (deprecated event types) | `chat.js`'s `THINKING_*` case labels in the AG-UI event switch | Server never emits these types; dead code only. Remove in console cleanup wave. |

**Round 3 sign-off: DEFERRED. No Critical/High blockers that are not acknowledged. All Medium/Low items recorded with rationale. Proceeding to tag v0.5.12.**

---

## Round 4 — v0.5.13 release gate (2026-06-17)

`/agent-stack-check . --static-only` four-protocol fan-out (MCP, A2A, AG-UI, A2UI). All seams S1–S6 PASS.

### Fixed in v0.5.13 (w016)

| Protocol | Sev | Finding | Fix |
|---|---|---|---|
| A2A | — | JSON parse error returned -32602 instead of -32700 | `wire_errors.py` + `a2a.py`: `a2a_parse_error()` added; `JSONDecodeError` → -32700 (GH-45) |
| A2A/SDK | — | Tool `ValidationError` swallowed into generic "tool failed" | `loop.py`: targeted `except ValidationError` before bare `except Exception`; extracts `loc`/`type` only (SI-2) (GH-48) |
| A2A/A2UI | — | A2UI DataParts emitted without `X-A2A-Extensions` opt-in | `a2a.py` + `translator.py`: `_capabilities()` gates on header; `tier='none'` blocks all emission (GH-50) |
| MCP | — | `openWorldHint` missing for tier-1 read-only tools | `registry.py`: `openWorldHint=False` for tier-1 and read_only (GH-52) |
| Harness | — | Acceptance-api.js: THREAD_ID bleed, missing failureClass, followUpTurns ignored | `acceptance-api.js`: UUID suffix, /tmp scoping, enum update, deterministic follow-ups (GH-53+55) |
| Workspace | — | LRN-028 ID collision + wrong Check clause + README gap | LRN-028 → LRN-038; new LRN-040; README indexed to LRN-041 (GH-54) |
| Harness | — | wave-cycle.js A2UI auditor prompt stated wrong type counts (Core 7+11) | Both wave-cycle.js copies updated to Core 6+Extended 8/14 FROZEN; LRN-012 Check clause added (RT-001 from redteam) |

### Deferred findings (acknowledged, non-blocking for v0.5.13)

| Protocol | Sev | Finding | File:line | Rationale |
|---|---|---|---|---|
| MCP | CRITICAL* | `_TITLE_MIN_VERSION` (module-level constant, `routes/mcp.py`) is a conservative gate — spec says title was introduced in 2025-06-18 | `routes/mcp.py`: `_TITLE_MIN_VERSION`, `tests/test_mcp_initialize_version_title.py` | *Spec annotation error, not a behavioral error. Omitting an optional field is spec-valid. GH-43 observed Claude.ai rejecting handshakes with title present; we cannot safely lower the gate without a live re-test. Comment updated to document the conservative intent. Behavioral impact: title absent for 2025-06-18 clients (safe). |
| MCP | HIGH | Tool-level `title` emitted in `tools/list` without version-gating for 2025-03-26 clients | `routes/mcp.py`: `_handle_tools_list()`'s `tool["title"] = entry.title` block | MCP `additionalProperties` is not `false` — strict clients tolerate unknown fields. Claude.ai always negotiates 2025-06-18+; no connectivity impact. Fix: remove 2025-03-26 from SUPPORTED_PROTOCOL_VERSIONS in a follow-up wave (requires test updates). |
| A2A | HIGH | `ChatDriver.a2a_turn()` uses hardcoded relative URL `/v1/message:send` instead of card `url` | `testing/chat.py`'s `ChatDriver.a2a_turn()` | Testing harness only — not part of the SDK public API. The underlying httpx client is always pre-pointed at the correct base URL in test contexts. File as GH issue; fix before promoting ChatDriver to a general-purpose client guide. |
| A2A | MED | `ChatDriver.extract_reply()` silently drops FilePart and DataPart | `testing/chat.py`'s `ChatDriver.extract_reply()` | Testing harness only; SDK server never puts file content in history messages. Document text-only scope or add fallback in a follow-up. |
| A2A | MED | `TaskState.REJECTED` and `TaskState.UNKNOWN` defined but never emitted | `agent/runner.py`'s `run_task_worker()` terminal-state emission (the `publish(...)` helpers) | Design limitation — `FAILED` is valid for all current error paths. Add `REJECTED` path for pre-execution policy failures in a follow-up wave. |
| AG-UI | MED | SSE reconnect starts a new task rather than re-attaching to in-flight run (potential double-worker) | `chat.js`'s SSE reconnect/backoff block | Console UI only; production agents use A2A transport. Architectural fix requires `find_task_for_thread()` on TaskStore. Deferred to console hardening wave. |
| AG-UI | MED | Stale `textBuffers` not reset before recursive reconnect (UI state corruption) | `chat.js`'s SSE reconnect/backoff block | Same reconnect path as above; same wave. |
| A2UI | LOW | AG-UI `ArtifactEvent` path in `ag_ui.py` skips `_validate_a2ui_wire()` pre-flight | `routes/ag_ui.py`: the `ArtifactEvent` `.wire()` emission path | Standard Profile types are Pydantic-guaranteed safe; risk is domain-card authors only. Add pre-flight call in follow-up wave. |
| A2UI | LOW | `_validate_a2ui_wire()` does not assert `component` string type | `agent/runner.py`: `_validate_a2ui_wire()`'s component assertion | Defense-in-depth only; Pydantic enforces `ClassVar[str]` at class-definition time for all registered types. |
| A2A (Round 3 carry) | HIGH | `403 Forbidden` maps to `-32000` | `app.py`'s `_A2A_CODE` status→JSON-RPC map (the `403: -32000` entry) | See Round 3 rationale. |
| A2A (Round 3 carry) | MED | `TaskStatus.error` non-spec field on wire | `models/a2a.py`'s `TaskStatus.error` field | See Round 3 rationale. |
| MCP (Round 3 carry) | MED | OAuth-kind token admin route rejection not fully verifiable statically | `auth/middleware.py`'s `require_api_key_identity()` guard | See Round 3 rationale. |

**Round 4 sign-off: DEFERRED. The two MCP findings (CRITICAL/HIGH) are pre-existing: F1 is a spec annotation + conservative gate (behavior is spec-valid), F2 has no connectivity impact. Comments updated to accurately document conservative intent. All other findings are non-blocking Medium/Low. Proceeding to tag v0.5.13.**

---

## Round 5 — w033 (GH-115) MCP void-result parity gate

`/redteam` on the async-generator dispatch fix (commit 73ab60d) surfaced the MCP void-result behaviour for explicit sign-off.

### Owned decision (not deferred): MCP §4 void-result parity deviation

| Protocol | Sev | Finding | File:line | Decision |
|---|---|---|---|---|
| MCP | MED | A Tier-1 tool that declares `emits` (so `tools/list` advertises `outputSchema`) but returns/yields `None` folds to `isError: false` with empty `text` and **no** `structuredContent` — a deviation from MCP 2025-06-18 §4's "advertised `outputSchema` MUST return conforming `structuredContent`". | `routes/mcp.py`'s `_handle_tools_call()` `if artifact is None:` branch (skips SC-C1 coercion; the `structuredContent` guard requires `isinstance(artifact, BaseModel)`); DESIGN.md §5.5 | **KEEP — signed off.** §5.6 requires a Tier-1 tool to reach the same success/failure verdict on every surface. `loop.py`'s `_fold_result_content(None)` folds the identical void result to a **success** `toolResult` on A2A/AG-UI; making MCP `isError: true` here would make the same void call succeed over A2A/AG-UI yet fail over MCP. The deviation is scoped strictly to the emits-declared void case (a no-`emits` `None` advertises no `outputSchema`, so it is not a §4 deviation at all). Tested by `tests/test_rt002_mcp_empty_result.py` (4 cases, all green). |

**mcp-check impact:** none. mcp-check audits the Claude.ai-connector conformance surface — OAuth discovery chain, token flow, CORS, Streamable HTTP transport, `initialize` handshake, `tools/list` shape, and the `tools/call` result **envelope** shape. An `isError: false` result carrying a well-formed `text` content block is a valid `tools/call` result; mcp-check does not drive a live void-returning tool and assert per-tool `outputSchema`↔`structuredContent` runtime conformance, so this ruling does not fail any mcp-check probe.

**Provenance-drift fix (RT-002):** DESIGN.md §5.5 previously mis-cited this ruling as `GH-113/LRN-118`. GH-113 is the `deleteSurfaceSemantics` wire-hint (adjacent paragraph copy-paste); LRN-118 is the version-header staleness rule — neither documents the void-result ruling. Citation corrected to `GH-115 / w033, RT-001/RT-002` (matching `routes/mcp.py`'s module docstring) plus this sign-off. This is exactly the canonical-doc cross-reference drift LRN-118 exists to catch, now closed.

**Resolved (was RT-003):** the dead imports this note previously deferred — `AsyncIterator`/`Optional`/local `LoopEvent` in `agent/registry.py` and `ErrorCategory` in `agent/loop.py`, all present at release 5bcab2b — have since been removed from the working tree (verified: `registry.py`'s `typing` import block no longer names `AsyncIterator` or `Optional` and holds no local `LoopEvent` import; `loop.py` has zero `ErrorCategory` references). The `AsyncIterator`/`LoopEvent` symbols that remain in `loop.py` and the `LoopEvent` mentions in `registry.py` are live uses (type hints / docstrings), not dead imports. No follow-up ruff/pyflakes cleanup is outstanding for these; note closed to end the doc-vs-code drift.

**Round 5 sign-off: SIGNED OFF. The void-result parity deviation is an owned, tested, §5.6-motivated decision with no mcp-check impact. Doc provenance corrected. No code change required — behaviour is correct and green.**

## Round 6 — w038 group G (GH-128) A2UI-over-A2A DataPart wrapper key decision (2026-07-25)

`/wave w038` group G's unit redteam (RT-002, round 5, budget-exhausted) flagged that the
GH-128 base-vs-extension conflict resolution — recorded only as a low-severity LRN
(LRN-134) plus inline comments — is a permanent, contested protocol deviation with a
real third-party-interop cost, and argued the decision belongs at ADR/sign-off level,
not buried in a low LRN. This SDK's own workspace does not keep a per-repo `workspace/adr/`
(that convention is for agent repos generated *from* the SDK, via `template/CLAUDE.md`'s
"Credential ADR discipline" — see `template/workspace/adr/a001-credential-model.md`); the
SDK's own equivalent for a protocol-level, permanently-owned decision is an explicit
sign-off round in this log, as Round 5 above already established. This round promotes the
GH-128 wrapper-key decision to that same level.

### Owned decision (not deferred): A2UI-over-A2A `DataPart.data` wrapper key (`"messages"`)

| Protocol | Sev | Finding | File:line | Decision |
|---|---|---|---|---|
| A2A / A2UI | LOW (interop cost), decision itself is protocol-binding | A2A v0.3.0's `DataPart.data` typing (`{[key: string]: any}`, `types.ts`, pinned tag) requires a JSON object; A2UI v0.9.1's own A2A binding (`a2ui_extension_specification.md`, "Data encoding", pinned `v0_9_1`) independently requires `data` to be a bare array and shows no `messages` wrapper in its own example. The two pinned specs directly conflict for this exact field. This SDK resolves the conflict by wrapping the array as `data: {"messages": [...]}}`, matching its own AG-UI `CUSTOM` `value.messages` convention — a shape neither spec defines as normative. | `agent_sdk/agent/runner.py::build_artifact()` (open/close A2UI `DataPart` construction); `agent_sdk/models/a2a.py` (`DataPart.data: dict[str, Any]`, object-only); `agent_sdk/a2ui/catalog.py::a2ui_extension()` (`dataEncoding` hint); DESIGN.md §5.4 | **KEEP the object wrapper — signed off.** Rejected alternative: revert to a bare array under the reading that A2UI, as an *activated extension*, may refine the base `DataPart.data` shape for its own mimeType — this was considered and rejected because it reintroduces the GH-128 Critical finding (a schema-validating A2A client — TCK, A2A Inspector, any typed SDK generated from the real v0.3.0 spec — rejects a bare-array `DataPart.data` outright, independent of any A2UI-specific reading); the object-typed base contract is treated as unconditionally binding. **Accepted residual cost:** a strictly spec-conformant, non-SDK-aware A2UI v0.9.1 Path-A renderer looks for the message array at `data` and will not find it at `data.messages` — it renders nothing for every A2UI artifact this SDK emits over A2A. Mitigated, not eliminated, by a non-normative `params.dataEncoding: "data.messages"` agent-card hint (mirrors `deleteSurfaceSemantics`/GH-113): a third-party renderer that reads and interprets SDK-specific card params can recover the shape; the spec does not require it to. This SDK's own first-party consumers (`agent_sdk/console/static/chat.js`, `agent_sdk/testing/chat.py`) unwrap `data.messages` correctly and are unaffected. |

**Upstream spec clarification (considered, not filed):** the cleanest long-term resolution
is an A2UI spec clarification (google/A2UI) stating whether an activated A2A extension may
refine `DataPart.data`'s shape for its own declared mimeType, which would let this SDK
either keep the bare array under a documented extension-refinement rule or have the wrapper
become citably canonical rather than SDK-private. Filing that issue was intentionally not
done as part of this round — it is an external, third-party repo this SDK does not own, and
per this project's own filing discipline (confirm before filing even for its own tracker —
see `sdk-issue`/`sdk-issue-scan`), opening a public issue on an unrelated upstream project
warrants an explicit decision by the SDK maintainer, not an automated one. Left as a follow-up
for the maintainer to file (or decline) at their discretion; this sign-off does not depend on it.

**Round 6 sign-off: SIGNED OFF. The `data.messages` wrapper is an owned, tested,
GH-128-motivated decision with a documented rejected alternative and an explicitly accepted
(not silently absorbed) third-party-interop cost. LRN-134 and DESIGN.md §5.4 carry the full
citation trail; this entry is the durable, ADR-equivalent record RT-002 asked for. No code
change required — behaviour is correct and already covered by
`tests/test_rt001_a2ui_data_encoding_hint.py` and the GH-128 wire-shape test updates.**

## Round 7 — w038 group G (GH-128) DESIGN §4.0 wire-shape conformance exemption (2026-07-25)

A later redteam round of the same w038 group-G loop (RT-005, versioning discipline) flagged
that the GH-128 fix ships a breaking `DataPart.data` narrowing under a same-minor patch bump
(0.5.43 → 0.5.44, not 0.6.0). The first resolution cited 0.5.40's `interrupt_ttl_remaining`
as *precedent*; a second pass noted that precedent alone leaves the top-of-file SemVer promise
("SemVer applies to the stable core (DESIGN.md §4.0)") in tension with practice, so it added a
standing **wire-shape conformance exemption** to DESIGN §4.0. That is a change to the SemVer
contract itself — strictly larger in blast radius than the Round-6 wrapper-key decision it sat
beside, yet it landed on CHANGELOG prose from a redteam finding (RT-005) with no owned-decision
record. This round gives it the same ADR-equivalent sign-off Round 6 gave the wrapper key.

### Owned decision (not deferred): DESIGN §4.0 wire-shape conformance exemption

| Scope | Sev | Finding | File:line | Decision |
|---|---|---|---|---|
| SemVer policy (stable core) | LOW (versioning discipline), decision is contract-level | DESIGN §4.0's stable core is under strict SemVer, yet 0.5.44 narrows a stable-core wire type (`DataPart.data`) under a patch bump. Without a stated rule, a consumer pinning `~=0.5.x` has no reason to expect a stable-core wire type to change without a major bump. | DESIGN.md §4.0 ("Wire-shape conformance exemption"); CHANGELOG.md `## [0.5.44]` `🔴 Breaking changes` | **KEEP the exemption — signed off.** A stable-core wire-shape break whose *sole* purpose is conformance to an external protocol spec (A2A/AG-UI/A2UI/MCP), not a voluntary redesign, may ship under a patch/minor bump, **conditional** on a dedicated `🔴 Breaking changes` CHANGELOG heading naming the exact type/field, both directions of impact (emit + parse), and a Migration callout. Rejected alternative: require a **major bump for every stable-core wire break** — rejected because a spec-conformance fix (the pre-fix shape was *already* non-conformant and unusable by schema-validating clients) is a bug fix that restores the documented contract, not a new contract; forcing 0.6.0 for it would both over-signal (implying voluntary API churn) and delay shipping a correctness fix. A **voluntary** stable-core break still requires a major bump and cannot cite this exemption. **Accepted risk:** a consumer pinning `~=0.5.x` who does not read the `🔴 Breaking changes` section may be surprised by a wire-shape change within a minor series; the conditional CHANGELOG discipline (dedicated heading + both-directions + Migration) is the mitigation, not elimination. |

**Round 7 sign-off: SIGNED OFF. The §4.0 wire-shape conformance exemption is an owned,
contract-level decision with a documented rejected alternative (major bump for all stable-core
wire breaks) and an explicitly accepted risk to `~=0.5.x` pinners. DESIGN §4.0 is now the
standing rule; CHANGELOG breaking-change entries cite it directly rather than re-arguing from
0.5.40 precedent release-by-release. No code change required.**

## Round 8 — RT-007 (GH-134/GH-135) Unreleased heading fix + GH-135 version sign-off (2026-08-15)

RT-007 flagged that GH-134 and GH-135 (`CHANGELOG.md` `## [Unreleased]`) were filed under
`### ⚠️ Behavior changes` instead of `### 🔴 Breaking changes`. GH-134 needed the dedicated
heading to even be eligible for the §4.0 wire-shape conformance exemption (no heading meant no
both-directions writeup and no Migration callout — the exemption's stated conditions). GH-135 is
a different case entirely: it is not a `models/` wire shape and not driven by any external
protocol spec, so the exemption is categorically unavailable to it regardless of heading — it had
no recorded decision on whether it instead needs a major/minor-axis version bump. Both entries
are now under `🔴 Breaking changes` in `CHANGELOG.md`, each with an explicit Migration callout;
GH-134 additionally states its emit/parse split. This round gives GH-135's version question the
same ADR-equivalent sign-off Round 6/7 gave the wrapper-key and exemption decisions.

### Owned decision (not deferred): GH-135 requires a version bump, not an exemption

| Scope | Sev | Finding | File:line | Decision |
|---|---|---|---|---|
| SemVer policy (stable core) | HIGH (RT-007) | `ToolEntry.invoke()`/`invoke_gen()` (`agent_sdk/agent/registry.py`) now raise `ToolInputValidationError`, a plain `Exception` that does **not** subclass `pydantic.ValidationError` — any `except pydantic.ValidationError` wrapped around a dispatch call silently stops catching it. `ToolSet`/`@tool` (dispatch) is stable core per DESIGN §4.0. The change is voluntary — an internal discriminator so tool-body `ValidationError`s aren't misreported as bad tool-call arguments (GH-135), sharpened for SI-2 by RT-003 — not required by any external protocol spec, and it is not a `models/` wire shape. §4.0's wire-shape conformance exemption therefore cannot be cited for it on either of its two conditions (wire-shape-in-`models/`; spec-conformance-driven). | CHANGELOG.md `## [Unreleased]` `🔴 Breaking changes` (GH-135) | **NOT exemption-eligible — requires a major/minor-axis bump.** Per DESIGN §4.0's own text ("A voluntary breaking change to the stable core — not required by spec conformance — still requires a major bump; this exemption cannot be cited for those"), GH-135 must ship as `0.6.0`, not folded into the next `0.5.x` patch. Rejected alternative: carve out a narrower exemption for "internal discriminator exceptions" that change caller-visible except-clauses — rejected because Round 7 deliberately scoped the exemption to external-spec-conformance wire shapes only; widening it to cover voluntary Python-API breaks by analogy would let any future voluntary stable-core break cite it, defeating that scope. **Accepted consequence:** this Unreleased batch cannot tag as a `0.5.x` patch while GH-135 is included — it ships as `0.6.0`, or GH-135 is cut from the batch and shipped in its own major/minor release; which of those is chosen is a release-cut decision for `/sdk-release`, not this review. GH-134, by contrast, IS exemption-eligible (an MCP `openWorldHint` conformance correction, not a voluntary redesign) and remains a patch/minor-bump candidate now that it carries its own dedicated heading, both-directions writeup, and Migration callout (done, this pass). |

**Round 8 sign-off: SIGNED OFF. GH-135 is confirmed outside the §4.0 wire-shape conformance
exemption on two independent grounds (not a `models/` wire shape; not spec-conformance-driven)
and requires a major/minor-axis bump (`0.6.0`) to ship, per DESIGN §4.0's existing text as
written — no change to §4.0 itself was needed or made. GH-134 is confirmed exemption-eligible and
now carries the heading, both-directions writeup, and Migration callout the exemption requires.
`CHANGELOG.md` `## [Unreleased]` updated accordingly; no other code change required.**

## Round 9 — RT-004 (GH-134 exemption mis-citation) GH-134 version sign-off (2026-08-15)

RT-004 flagged that GH-134's Round 8 clearance rested on a false locational claim: the CHANGELOG
parenthetical cited `ToolDecl.annotations`, `models/` per DESIGN.md §4.0`, but `class ToolDecl` is
defined at `agent_sdk/agent/registry.py:161` — there is no `models/` type for MCP tool
declarations at all; `agent_sdk/routes/mcp.py` builds the `tools/list` `annotations` dict ad hoc
from `ToolDecl.annotations` (`routes/mcp.py:342-343`). Round 8 itself established, and applied to
GH-135, a two-condition **AND** test for the §4.0 exemption — wire-shape-in-`models/` **and**
spec-conformance-driven — but cleared GH-134 on the spec-conformance condition alone, without
checking the `models/` condition it had just used to disqualify GH-135. Applying Round 8's own
test honestly to GH-134 closes that gap.

### Owned decision (not deferred): GH-134 also requires a version bump, not an exemption

| Scope | Sev | Finding | File:line | Decision |
|---|---|---|---|---|
| SemVer policy (stable core) | HIGH (RT-004) | GH-134's changed wire shape is the MCP `tools/list` `annotations` dict, sourced from `ToolDecl.annotations` (`agent_sdk/agent/registry.py:161`) and serialized in `agent_sdk/routes/mcp.py:342-343`. Neither file is under `agent_sdk/models/`, and `agent_sdk/models/` (`a2a.py`, `content_types.py`, `errors.py`) contains no MCP tool-declaration wire type at all — this shape has no `models/` home to satisfy the exemption's first condition, regardless of file path cited. The change IS spec-conformance-driven (correcting `openWorldHint` to MCP's 2025-06-18 semantics, not a voluntary redesign), satisfying the exemption's second condition — but DESIGN §4.0's exemption is conjunctive: both conditions are required, not either. | CHANGELOG.md `## [Unreleased]` `🔴 Breaking changes` (GH-134) | **NOT exemption-eligible — requires a major/minor-axis bump.** Failing one of the exemption's two required conditions is disqualifying regardless of the other, per the identical logic Round 8 already applied to GH-135 (which failed both). GH-134 therefore ships as `0.6.0`, not the next `0.5.x` patch, alongside GH-135. Rejected alternative: widen DESIGN §4.0's exemption text to cover any stable-core surface whose output is protocol wire content, not only `models/` types — rejected because that would retroactively legitimize the mis-citation this round exists to correct, and Round 7 already deliberately scoped the exemption narrowly with a documented rejected alternative; loosening it now, on the strength of a single convenient case, would undermine that prior sign-off rather than build on it. **Accepted consequence:** this Unreleased batch requires `0.6.0` for GH-134 independent of the GH-135 decision already reached in Round 8 — cutting GH-135 from the batch (an option Round 8 named) no longer keeps GH-134 patch/minor-eligible either; both entries need the major/minor bump, or both need to be cut. Which is chosen remains a release-cut decision for `/sdk-release`, not this review. |

**Round 9 sign-off: SIGNED OFF. GH-134 is confirmed outside the §4.0 wire-shape conformance
exemption on the `models/` condition (it is spec-conformance-driven but has no `models/` wire
type to qualify under) and requires a major/minor-axis bump (`0.6.0`) to ship, on the same
conjunctive reading of DESIGN §4.0 Round 8 already applied to GH-135 — no change to §4.0 itself
was needed or made. `CHANGELOG.md` `## [Unreleased]` corrected: the false `models/` location
claim is removed, the exemption claim is withdrawn, and a `0.6.0` **Version** line matching
GH-135's is added. No other code change required.**

## Round 10 — Pre-release `/agent-stack-check` full-stack audit (0.6.0 gate) (2026-08-18)

`/sdk-release 0.6.0`'s `/sdk-test` Leg 3 ran the full four-protocol conformance audit
(`mcp-advisor`, `a2a-advisor`, `ag-ui-advisor`, `a2ui-advisor`, dispatched in parallel per
`/agent-stack-check`'s Phase 1) against the merged `main` (post-#140/#141/#142) ahead of tagging.
All four protocols verdicted **COMPLIANT** (zero Critical/High). The S1–S6 cross-protocol seam
audit found no disagreement between layers: card↔impl (S1) matches on MCP tools/A2A
skills/A2UI/AG-UI extension advertisement; the A2A `DataPart.data` object-wrapper vs. A2UI
v0.9.1's bare-array binding (S2) is an internal agreement between this SDK's own emit and
A2A-typing layers, already disclosed via the `dataEncoding` card hint and independently rated
informational by both the A2A and A2UI advisors; A2UI-over-AG-UI (S3), MCP↔A2A auth/tool-source
coherence (S4), version/capability alignment (S5 — including the already-documented,
already-accepted AG-UI-CUSTOM-skips-tier-gating asymmetry, LRN-049/GH-124), and catalog
coherence (S6) all passed. Two **Medium** findings were surfaced, both pre-existing (not
introduced by #140/#141/#142) and neither gating the COMPLIANT verdict, but requiring disposition
per `/sdk-test`'s Leg 3 rule ("MEDIUM/LOW findings must be acknowledged... fixed or recorded as
deferred with a rationale").

### Deferred (not fixed in this release): two pre-existing Medium findings

| # | Protocol | Sev | Finding | File:line | Decision |
|---|---|---|---|---|---|
| 1 | MCP (D7 Security) | MEDIUM | `GET /mcp` opens an authenticated, indefinitely-held SSE heartbeat stream with no cap on concurrent connections — per-identity or global. `identity_limiter` only throttles the request that establishes the stream, not how many stay open. Legacy SSE transport IS capped (`_MAX_SSE_SESSIONS=500`); Streamable HTTP's GET channel is not. Single-process/single-worker deployment means exhausting this channel degrades the whole process for every tenant. | `agent_sdk/routes/mcp.py:688-724` | **RESOLVED in `0.7.0`** (GH-143, `workspace/todos/archive/w040-gh-issues.md`): global + per-identity admission cap landed on both `GET /mcp` and `GET /mcp/sse` (`_get_streams()`/`_MAX_GET_STREAMS`, `agent_sdk/routes/mcp.py`). A follow-up redteam pass (RT-001 round 2) found the per-identity half of that fix collapsed an entire org onto one quota under this SDK's own org-wide OAuth-client / shared-API-key modes — also fixed in `0.7.0` via a raised default and `AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY`. See CHANGELOG.md `[0.7.0]` for full detail. |
| 2 | A2A (D2 Transports & Methods) | MEDIUM | Same logical condition — sending to a terminal task by `taskId` — returns `-32004 UnsupportedOperation` (HTTP 501) via `message/send`'s `_resume_or_error`, but `-32001 TaskNotFound` (HTTP 404) via `message/stream`'s inline short-circuit, which bypasses `_resume_or_error` entirely. `-32001` is a semantic misuse (the task exists; it just can't accept new input) — an internal cross-method inconsistency, not a hard-MUST breach (both codes are valid A2A error codes; only one transport/pairing is implemented, so the multi-transport-equivalence MUST doesn't apply). | `agent_sdk/routes/a2a.py:200-204` vs `:330-335` | **RESOLVED in `0.7.0`** (GH-144, `workspace/todos/archive/w040-gh-issues.md`): `message/stream`'s terminal-task-with-`taskId` case now routes through the same `-32004`/501 check `message/send`'s `_resume_or_error` uses. Shipped as a voluntary stable-core break under a major-equivalent version bump per DESIGN.md:141 (see CHANGELOG.md `[0.7.0]`'s 🔴 Breaking changes entry and its RT-002 correction), not folded into a patch. A follow-up redteam pass (RT-002) also found the A2A SSE surface this fix touches had no concurrency admission cap at all — fixed in the same release; see CHANGELOG.md `[0.7.0]` for full detail. |

**Round 10 sign-off: SIGNED OFF FOR RELEASE. Both Medium findings are genuine and worth fixing,
but neither is a Critical/High conformance breach, neither was introduced by the code shipping in
0.6.0, and neither blocks `0.6.0` from tagging under `/sdk-test`'s stated gate (Critical/High
only are hard blockers; Medium/Low require acknowledgement, which this round provides). Both are
deferred to the next `/gh-review` cycle as new GitHub issues rather than fixed ad hoc inside the
release gate. No code change required by this round. Full per-protocol audit reports (dimension
tables, protocol facts, remediation lists) are preserved in the `/sdk-release 0.6.0` session
transcript; this entry is the durable summary and disposition record.**

## Round 11 — Pre-release `/agent-stack-check` full-stack audit (0.7.0 gate) (2026-08-21)

`/sdk-release 0.7.0`'s `/sdk-test` Leg 3 ran the full four-protocol conformance audit
(`mcp-advisor`, `a2a-advisor`, `ag-ui-advisor`, `a2ui-advisor`) against the working tree carrying
the GH-143/GH-144 fixes (`workspace/todos/archive/w040-gh-issues.md`). MCP, A2A (both server and
D7 consumer roles), and A2UI (emitter role) all verdicted **COMPLIANT** (zero Critical/High).
AG-UI did not: `ag-ui-advisor` found one **HIGH** cross-cutting regression.

### Fixed in this round (release blocker): AG-UI-surfaced TTL/interrupt-expiry eviction gap

| # | Protocol | Sev | Finding | File:line | Disposition |
|---|---|---|---|---|---|
| 1 | AG-UI (C2 Event ordering / cross-cutting store lifecycle) | HIGH | RT-001 round 5 (Round 9 above, GH-143/GH-144 wave) fixed `InMemoryTaskStore._evict_over_capacity()` so it never evicts a record with live subscribers — but that guard was scoped to the capacity-overflow eviction path only. `get()`'s TTL/interrupt-deadline expiry check, and the periodic background `sweep()`, both still called `evict()` unconditionally with no such guard. `get()`'s path is reachable from `find_interrupt()` (AG-UI's `_resume_target_task_id` resume lookup, `agent_sdk/routes/ag_ui.py`), so a resume attempt for one interrupt walks every record in the store and could silently evict an unrelated, still-live-streamed task purely because it hadn't been touched within its TTL — severing that stream with no `final:true` frame, the exact harm class round 5 already fixed once at a different layer. | `agent_sdk/tasks/memory.py::get` (was `:49-60`), `::sweep` (was `:232-234`) | **FIXED.** Both `get()` and `sweep()` now apply the identical reap-then-skip-if-still-subscribed guard `_evict_over_capacity` already had (`agent_sdk/tasks/memory.py`). Regression test added: `tests/test_rt001_r6_expiry_never_severs_live_streams.py` (5 cases — TTL expiry, cross-task `find_interrupt()` lookup, `sweep()`, no-subscriber-still-evictable, leaked-subscription-still-evictable). Captured as [[LRN-213-eviction-guard-fixed-one-call-site-not-the-invariant]] (the same lesson as [[LRN-198-uncapped-sibling-stream-route]] one layer down: a guard fixed for one call site of a shared destructive method, and left off its siblings, is bypassable through a different door). `CHANGELOG.md` `[0.7.0]`'s `⚠️ Behavior changes` entry and `DESIGN.md` §5.2 updated to describe the full guard (not just the capacity-overflow half). |

### Two Medium doc-drift findings (also from `ag-ui-advisor`), fixed inline

- `docs/protocols.md`'s CUSTOM-events table omitted `TOOL_PROGRESS` (present on the card's
  machine-readable `x-agui.customEvents` and in `chat.js`'s routing table — only the human
  narrative doc had drifted). Added.
- `docs/protocols.md` stated control characters trigger `RUN_ERROR`; the code has stripped, never
  rejected, them since RT-001 (pre-existing drift, not introduced by this wave, but live in the
  audited tree). Corrected to match actual behavior.

### Re-verification after the fix

Full `/sdk-test` Leg 1 (`.venv/bin/pytest -q tests/`): **2144 passed, 2 skipped, 0 failed** (was
2139 before this round's 5 new tests). Leg 2 (`mypy agent_sdk/ --ignore-missing-imports`):
**Success: no issues found in 97 source files.** Leg 3 re-scoped to the AG-UI finding only (not a
full advisor re-dispatch): the specific regression is closed at the code level and pinned by the
new test file; no new Critical/High surfaced by the fix itself.

**Round 11 sign-off: SIGNED OFF FOR RELEASE. The one HIGH finding is fixed and tested (not
deferred — Critical/High findings are hard blockers per `/sdk-test`'s Leg 3 rule and cannot ship
under an acknowledged-and-deferred disposition the way Medium/Low can). The two Medium doc-drift
findings are fixed inline. MCP, A2A (both roles), and A2UI remain COMPLIANT from Round 10's
findings plus this round's independent full re-audit. `0.7.0` is clear to tag.**
