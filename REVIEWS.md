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
| 11 | MINOR | MCP-Protocol-Version header validation (400 invalid; absent→2025-03-26) | §5.5 |
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
| LOW | "required on all post-init requests" vs absent→default contradiction | "validated when present" §5.5 |
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
