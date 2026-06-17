# agent-sdk — Design Document

**Status:** v3 — revised after Round-1 specialist red-team and Round-1b confirmation pass (see REVIEWS.md)
**Date:** 2026-06-10
**Repo:** `a2a-sdk` (library name: `agent-sdk`, import name: `agent_sdk`)

---

## 1. Goals and non-goals

### Goals

1. Let a new team stand up a production-grade, protocol-conformant agent by writing **only** domain code: tools, source adapters, SKILL.md files, a persona, and config (~10 files).
2. Own, in one versioned library, everything the three reference agents (m365, investment_analyst, pitchbook) currently copy-paste: A2A, AG-UI, A2UI, OAuth-protected MCP, Bedrock loop, credential store, auth, admin/test console, observability, packaging.
3. Guarantee protocol conformance at the library level: an agent built on the SDK passes `agent-stack-check` without the team thinking about protocols.
4. Ship a Claude Code harness (plugin) so new-agent development is guided end-to-end: scaffold → implement → verify.

### Non-goals (v1)

- Multi-LLM-backend support (Bedrock only, behind a seam — §8).
- Persistent task store (in-memory, behind an interface — §5.2).
- gRPC or JSON-RPC transports for A2A (HTTP+JSON only). SSE frames are therefore **bare event objects** — a future JSON-RPC binding would wrap each in `SendStreamingMessageResponse{jsonrpc, id, result}`; not applicable to v1.
- A2A *client* features (the SDK builds providers).
- Multi-tenancy within one deployment.
- Push notifications (`capabilities.pushNotifications: false`; see §5.1 for the required error behavior this implies).

### Pinned conformance baseline

| Protocol | Version | Audited by |
|---|---|---|
| A2A | v0.3.0 (HTTP+JSON transport) | `a2a-check` |
| A2UI | v0.9.1 + Standard Profile v1 (18 types: 14 FROZEN + 4 RESERVED) | `a2ui-check` |
| MCP | 2025-11-25 (Streamable HTTP; 2025-06-18 and 2025-03-26 also accepted) | `mcp-check` |
| AG-UI | event catalog per `ag-ui-protocol>=0.1.18` | `ag-ui-check` |
| OAuth | 2.1 semantics via RFC 8414, 7591, 6749+PKCE, 8707, 9728, 7009 | `mcp-check` (connector flow) |

Protocol version upgrades are **SDK major releases**. CI runs `agent-stack-check` plus live HTTP probes (§12) against the built-in example agent on every change; a red check blocks release.

**Where the references disagree with the spec, the SDK follows the spec, not the references.** Known reference defects the SDK corrects (do NOT port these): m365's ungated Extended A2UI types and `AGENT_NOTE={"message":…}` shape; investment_analyst/pitchbook's pre-stream validation raises (breaks `RUN_STARTED`-first); pitchbook's `urn:a2ui-catalog:private-market:v1` as `createSurface` catalogId for Standard Profile components; pitchbook's MCP `structuredContent` emitted without a corresponding `outputSchema` in `tools/list`; investment_analyst's `supportedInterfaces` card field (v1.0-only shape) and console dropping `AGENT_ARTIFACT` CUSTOM events; m365/investment_analyst's fabricated `ToolCallResultEvent.message_id`.

---

## 2. Architecture overview

One FastAPI server, one port, five protocol surfaces, one agent loop.

```
                        ┌────────────────────────────────────────────┐
                        │              agent_sdk app                 │
 Claude.ai (MCP) ──────▶│  /mcp (Streamable HTTP: POST+GET+DELETE)   │
                        │  /mcp/sse + /mcp/messages (legacy)         │
 OAuth connector ──────▶│  /oauth/* + /.well-known/oauth-*           │
 A2A consumers   ──────▶│  /v1/message:send|stream, /v1/tasks/*      │
                        │  /.well-known/agent-card.json              │
 AG-UI frontends ──────▶│  /ag-ui/run (SSE)                          │
 Operators       ──────▶│  /admin (console)  /health                 │
                        ├────────────────────────────────────────────┤
                        │  per-surface event translators             │
                        │            ▲                               │
                        │      agent loop (async generator,          │
                        │      typed events) ── ModelClient(Bedrock) │
                        │            ▲                               │
                        │      ToolRegistry ── SourceAdapters        │
                        │      SkillsRegistry (SKILL.md)             │
                        │      CredentialStore (AES SQLite)          │
                        └────────────────────────────────────────────┘
```

Core invariant: **the loop yields typed domain events** (`TurnStartedEvent, ToolCallEvent, ToolResultEvent, ProgressEvent, ArtifactEvent, UsageEvent, DoneEvent`); each protocol route owns a translator from those events to its wire format. `TurnStartedEvent(n)` is a first-class event — the AG-UI STEP translator keys on it; translators never regex-parse `ProgressEvent` text to find turn boundaries (pitchbook does; the SDK does not inherit that). Protocol code never reaches into the loop; the loop knows nothing about protocols.

**Deployment invariant: exactly one process per deployment.** The task store, SSE subscriber queues, and rate limiter are process-local. The template Dockerfile hard-codes `--workers 1`; `BaseAgentSettings` refuses `WEB_CONCURRENCY > 1` with an explanatory error. Multi-replica support arrives only with a shared `TaskStore` backend (post-v1).

---

## 3. Package layout

```
agent_sdk/
├── app.py                  # Agent builder → FastAPI app factory, lifespan wiring
├── config.py               # BaseAgentSettings (pydantic-settings; teams subclass)
├── models/
│   ├── a2a.py              # A2A v0.3.0 wire shapes (Task, TaskStatus, Message,
│   │                       #   MessageSendConfiguration, TextPart, DataPart, FilePart,
│   │                       #   Artifact, AgentCard, AgentSkill, AgentInterface, …)
│   ├── content_types.py    # Standard Profile v1 models — ALL 14 FROZEN types,
│   │                       #   Profile-isomorphic (see §4.3); 4 RESERVED acknowledged
│   └── errors.py           # AgentError(category, message, source, a2a_code, detail)
├── agent/
│   ├── loop.py             # tool-use loop: async generator of typed events
│   ├── model_client.py     # ModelClient protocol (seam) + types
│   ├── bedrock.py          # BedrockModelClient (boto3 Converse, bounded executor)
│   ├── registry.py         # ToolRegistry, ToolSet, ToolEntry
│   ├── skills.py           # SkillsRegistry: SKILL.md scan, catalog, load_skill tool
│   └── events.py           # typed loop events
├── routes/
│   ├── a2a.py              # message:send/stream, tasks/{id}, :cancel, :subscribe
│   ├── agent_card.py       # /.well-known/agent-card.json (+ legacy agent.json), ETag
│   ├── ag_ui.py            # POST /ag-ui/run (SSE)
│   ├── mcp.py              # /mcp Streamable HTTP (POST+GET+DELETE) + legacy SSE pair
│   ├── oauth.py            # 8414/7591/6749+PKCE/8707/9728/7009 + consent page
│   ├── admin.py            # console API (credentials, keys, usage, samples)
│   └── health.py
├── a2ui/
│   ├── translator.py       # content model → message-envelope sequences (§5.4)
│   └── catalog.py          # Standard Profile v1 registry + domain-catalog extension API
├── auth/
│   ├── middleware.py        # identity resolution (kind-tagged), rate limiters
│   ├── api_keys.py
│   ├── oauth_tokens.py      # token/code/refresh lifecycle, rotation, revocation, audience
│   └── usage.py             # token usage → USD
├── credentials/
│   ├── store.py             # CredentialStore ABC (namespaced: {source}/{field})
│   ├── encrypted_sqlite.py  # AES-256-GCM + KDF (§6)
│   └── fields.py            # CredentialField model incl. type="url" SSRF validation
├── tasks/
│   ├── store.py             # TaskStore interface
│   └── memory.py            # InMemoryTaskStore (LRU + TTL, bounded SSE queues)
├── common/                  # sse.py, wire_errors.py, etag.py, redact.py, limits.py
├── observability/           # logging.py, tracing.py
├── validation/              # shared validators (control chars, ids, url-interpolation guard)
├── console/                 # admin console static assets + Jinja2 templates
│   ├── templates/           #   loaded via importlib.resources (never __file__ paths)
│   └── static/              #   vanilla JS, no build step, strict-CSP-compatible
├── contrib/                 # v1 status: EXPERIMENTAL (§9, §12)
│   ├── action_gate/ obo/ commitments/ webhooks/
├── testing/                 # FakeModelClient, ChatDriver, recorded Converse fixtures,
│                            #   SSE test client — fixtures construct isolated Agent instances
└── example/                 # built-in example agent ("echo-analyst") used by CI gate
```

Repo-level (not in the wheel): `template/`, `harness/`, `docs/` (+ CHANGELOG.md).

---

## 4. Public API (the developer contract)

### 4.0 API stability tiers

- **Stable core (strict SemVer):** `Agent`, `ToolSet`/`@tool`, `SourceAdapter`, `BaseAgentSettings`, wire shapes in `models/`, Standard Profile contracts, the template contract.
- **Provisional (may change in minors, with CHANGELOG notice):** `agent_sdk.testing`, console internals, everything under `contrib/`.

New SDK settings always use the reserved `AGENT_SDK_` env prefix so they can never collide with team-defined settings.

### 4.1 Agent assembly — explicit registration, no import side effects

Registration is collected explicitly (FastAPI `APIRouter` style). Nothing registers via module import; a forgotten wire-up fails loudly at `build_app()`, not silently at runtime.

```python
# src/tools/prices.py
from agent_sdk import ToolSet
from agent_sdk.models.content_types import TimeSeriesChart   # class name == wire name

tools = ToolSet()

@tools.tool(
    tier=1,                        # 1 = query (A2A + MCP), 2 = composite (A2A only)
    emits=TimeSeriesChart,         # → x-sdk render hints + MCP outputSchema
    sample={"symbol": "AAPL"},     # console "Try" sample (optional)
)
async def get_price_history(inp: PriceHistoryInput, *, adapter: EodhdAdapter) -> TimeSeriesChart:
    """Fetch OHLCV history for a symbol."""   # docstring = tool description
    ...
```

There is no `source=` kwarg — the adapter annotations are the single source of truth for a tool's dependencies (one declaration, no conflict rule needed). Tool name = function `__name__` (overridable via `name=`); a no-input tool simply omits the input model. `ToolSet` is a stateless declaration list, reusable across `Agent` instances — `agent_sdk.testing` fixtures rely on this.

```python
# src/main.py — the whole file
from agent_sdk import Agent
from .config import make_settings
from .persona import PERSONA
from .sources import EodhdAdapter
from .tools import prices, fundamentals

agent = Agent(
    settings=make_settings(),               # factory, not import-time instantiation
    persona=PERSONA,
    skills_dir=Path(__file__).parent / "skills",   # anchored, never cwd-relative
    toolsets=[prices.tools, fundamentals.tools],
)
agent.register_source(EodhdAdapter, credentials=[
    CredentialField(name="api_token", label="EODHD API token", secret=True),
])
app = agent.build_app()
```

`build_app()` validation (all failures raise at boot, never at call time): every adapter annotation resolves to a registered adapter class; duplicate tool names raise; duplicate `source_name` or repeated `register_source` of the same class raises (registration is once-per-class); every `emits` type is a known Profile/domain type; declared CUSTOM event names match the console routing table (§5.3).

**Adapter injection and lifecycle:** the keyword-only parameter annotated with a `SourceAdapter` subclass receives the instance; a tool may declare multiple adapter parameters, each resolved by annotation using **exact-class match** (never `isinstance` — subclass relationships between registered adapters stay unambiguous). The SDK owns instantiation: one instance per registered class, constructed at **lifespan startup** with `(settings, credential_resolver)`; extra constructor kwargs pass through `register_source(EodhdAdapter, credentials=[…], init_kwargs={…})`. `source_name` is read from the adapter class — declared once.

### 4.2 Source adapters

```python
class EodhdAdapter(SourceAdapter):
    source_name = "eodhd"
    allowed_hosts = ["eodhd.com"]          # base-class HTTP client refuses other hosts
    async def health_check(self) -> bool: ...
    # self.credential("api_token") — resolved ONLY from this source's namespace
```

Base class provides: lazy `httpx.AsyncClient` (**redirect-following disabled and pinned** — an allowed host redirecting elsewhere is the classic SSRF bypass; if an adapter opts into redirects, every hop is re-checked against `allowed_hosts`), credential resolution (store → env fallback), per-bucket rate limiting, 429/503 retry-once, health wiring, and **host allow-listing** (SSRF guard — requests outside `allowed_hosts` raise). Known residual: url-typed credential values are validated at save time, not at each DNS resolution (rebinding TOCTOU) — documented, accepted for v1 since targets are operator-entered, not model-controlled. Tools never use `httpx` directly. `CredentialField(type="url")` values are validated SDK-side: https-only, public-IP-only (no RFC 1918 / link-local / metadata endpoints). Path-interpolated tool inputs go through `validation.url_segment()` (identifiers through `safe_id()`) **inside the source-adapter method** — the `@tool` decorator does not inspect or sanitize path params (there is no `path_param` flag), so the adapter is the sole enforcement point: never f-string raw input into a URL path.

### 4.3 Content types and domain A2UI catalogs

The SDK ships **all 14 FROZEN** Standard Profile v1 types as Pydantic models whose field shapes are **wire-isomorphic with the Profile contracts** (no adapter remapping layer to drift): Core — `KpiCard` (`metrics: [{label, value, …}]`), `TimeSeriesChart` (`x_key, y_key, data, total_count`), `ComparisonTable`, `BarChart`, `EntityList`, `MarketBriefing`; Extended — `WaterfallChart`, `MultiCategoryChart`, `FundPerformance`, `EmailList`, `CalendarEvents`, `UserProfile`, `UserList`, `DocumentList`. The 4 RESERVED types (`TradeActivity`, `CompanyInfo`, `DealList`, `InvestorProfile`) are name-allocated only — no field contract, no translator. Class names equal wire component names exactly (case-sensitive renderer lookup).

Three non-obvious contracts: `MarketBriefing` is the only type whose wire `data` is a **markdown string** — the translator emits `model.to_markdown()`, never `model_dump()`; `model_dump()` of any content model is **never** placed on the wire directly — the translator (§5.4) is the sole emission path (it adds envelopes, computes nothing); and **every content model (FROZEN and domain) implements `to_plain_text() -> str`** — it is the required interface backing the A2A dual-part TextPart fallback (§5.1, §5.4), enforced by the base-model ABC.

Domain cards live in the agent repo: subclass `ContentModel`, declare `data_type` (snake_case) / `component` (PascalCase wire name) / a non-Profile `catalog_id`, implement `to_plain_text()`, and register the class (import the module so registration runs at boot — no module-level global):

```python
class CompanyProfile(ContentModel):
    data_type: ClassVar[str] = "company_profile"
    component: ClassVar[str] = "CompanyProfile"                      # globally unique wire name
    catalog_id: ClassVar[str] = "urn:a2ui-catalog:acme-finance:v1"  # never the standard-profile URI
    # …instance fields = the wire data shape…
    def to_plain_text(self) -> str: ...

register_content_type(CompanyProfile)
```

`register_content_type` enforces uniqueness of **both** `data_type` **and** the wire `component` name across the whole registry (A2UI resolves components by bare componentType with no catalog qualifier, so a duplicate name — even under a different `catalog_id` — would silently shadow), refuses the four RESERVED names, and rejects any new type that claims the frozen standard `catalog_id`. Negotiation mechanics in §5.4. The console renders registered domain components automatically.

### 4.4 Settings

```python
class Settings(BaseAgentSettings):
    my_domain_flag: str = "default"
# extend config via: model_config = SettingsConfigDict(**BaseAgentSettings.model_config, …)
```

`BaseAgentSettings` validation: `MASTER_KEY` per §6; `PUBLIC_URL` required in production; CORS explicit list, never wildcard; `WEB_CONCURRENCY > 1` refused (best-effort — `uvicorn --workers N` bypasses the env var; the template's hard-coded `--workers 1` is the real control); **`DEV_MODE=true` with a non-localhost `PUBLIC_URL` is a hard failure.** DEV_MODE relaxes exactly: MASTER_KEY strength check, PUBLIC_URL requirement, secure-transport checks on OAuth endpoints — enumerated in docs, nothing else. `AGENT_SDK_TRUSTED_PROXIES` configures client-IP derivation for rate limiting (§6): with trusted proxies set, the rightmost untrusted hop of `X-Forwarded-For` is the client; with none set, the socket peer is — `X-Forwarded-For` is never trusted blindly.

### 4.5 Agent card

Assembled by the SDK; teams never hand-write card JSON. Spec-conformance rules:

- `protocolVersion: "0.3.0"`, `preferredTransport: "HTTP+JSON"`, `url = PUBLIC_URL`. `url` is REQUIRED by the card schema and is **never omitted**: when `PUBLIC_URL` is unset (dev), it falls back to `http://localhost:{PORT}` so dev-mode cards still pass schema validation and the CI gate stays meaningful. `additionalInterfaces` (the v0.3.0 field; each entry requires `transport` AND `url`) is emitted empty/omitted for single-transport agents. The v1.0-only `supportedInterfaces` field is never emitted. `supportsAuthenticatedExtendedCard` is explicitly `false`; the extended-card method is served defensively and returns `-32007`.
- `AgentSkill` entries carry only spec fields (`id, name, description, tags, examples?, inputModes?, outputModes?, security?`). SDK extras — input/output schemas, tier, emits — live under the `x-sdk` namespace, never bare.
- `capabilities.extensions[]` lists **only URIs with a real negotiation path**: the A2UI extension URI `https://a2ui.org/a2a-extension/a2ui/v0.9.1` (exact string; activated via `X-A2A-Extensions` echo). The previous "enhanced-content-types" pseudo-extension is dropped; content-type metadata rides in `x-sdk` fields.
- `capabilities.pushNotifications: false`, `capabilities.streaming: true`.
- AG-UI surface advertised via the top-level `x-agui` block (deliberate choice over a `urn:agui:run:v1` extension; AG-UI has no normative card form): `{transport, endpoint, customEvents: [...]}` — `endpoint` is absolute, derived from the same resolved base URL as `url` (so the dev localhost fallback applies here too; it is never null or malformed).
- A2UI catalogs advertised under the A2UI extension params: `supportedCatalogIds = ["urn:a2ui-profile:standard:v1", …registered domain catalog ids]`.
- ETag/conditional GET; `/.well-known/agent.json` byte-identical legacy alias.

---

## 5. Protocol surfaces

### 5.1 A2A v0.3.0 (HTTP+JSON + SSE)

Endpoints:

- `POST /v1/message:send` → **HTTP 200**, result is **`Task | Message`**: a `Message` when the agent completes synchronously without creating a task (supported by the SDK for trivial/echo flows), a `Task` snapshot otherwise.
- `POST /v1/message:stream` → SSE: first frame full Task, then `TaskStatusUpdateEvent` / `TaskArtifactUpdateEvent`, last frame carries `final: true`.
- `GET /v1/tasks/{id}`; `POST /v1/tasks/{id}:cancel` — success returns **HTTP 200 with the full `Task` in `canceled` state** (spec-required result, not an empty body); unknown id → 404 + `-32001`; terminal state → 409 + `-32002`; `POST /v1/tasks/{id}:subscribe` (unknown id → 404 + `-32001`).
- `GET /v1/tasks` → 200, identity-scoped paginated list. Query params: `pageSize` (default 50, clamped 1–100), `pageToken` (opaque cursor). Response: `{tasks, totalSize, pageSize, nextPageToken}`. Identity binding same as `GET /v1/tasks/{id}`.

Inbound `Message` validation: `messageId` is required (spec REQ); missing → 400 invalid params.

`MessageSendParams.configuration` is a typed **`MessageSendConfiguration`** model (`acceptedOutputModes?, historyLength?, pushNotificationConfig?, blocking?`) — never a raw dict. The SDK honors `acceptedOutputModes` and `historyLength`; `pushNotificationConfig` present → `-32003 PushNotificationNotSupported` (capability is false); `blocking: true` the server can't honor → `-32004` (the spec leaves this code unspecified; -32004 is the documented local convention).

**Task identity binding (security):** every task records its creating identity (`kind` + id, §6). `GET`, `:subscribe`, `:cancel`, and resume require the same identity (admin `api_key` identities may override); mismatch → 404 + `-32001` — existence is not leaked. Without this, anyone who learns a taskId from a log or trace could read it or, worse, confirm another identity's pending action_gate proposal.

**Interrupt / resume flow** (required by `contrib.action_gate` and spec lifecycle): `input-required` and `auth-required` are non-terminal interrupt states; the stream MAY close `final: true` while the task is interrupted. A `message/send` (or `:stream`) whose `message.taskId` references an existing task: terminal state → error; `input-required`/`auth-required` → **resume that task** (same `contextId`, same identity, message handed to the paused worker via the task store's resume channel) — never create a new task. While interrupted, the per-task wall-clock deadline is **suspended** (§8) and the interrupted-task TTL (§5.2) governs expiry instead.

Complete A2A error code table (all seven; internal sentinel names match spec names):

| Code | Name | SDK trigger |
|---|---|---|
| -32001 | TaskNotFound | unknown/expired task id |
| -32002 | TaskNotCancelable | cancel on terminal task |
| -32003 | PushNotificationNotSupported | any push-config request (capability false) |
| -32004 | UnsupportedOperation | unsupported blocking, any unimplemented method |
| -32005 | ContentTypeNotSupported | unacceptable `acceptedOutputModes` |
| -32006 | InvalidAgentResponse | internal translator failure |
| -32007 | AuthenticatedExtendedCardNotConfigured | extended-card request (not configured) |

Wire-shape rules baked into `models/a2a.py`:

- Parts discriminate on `kind`, never `type`. `FilePart` = FileWithBytes XOR FileWithUri.
- Structured artifacts are dual-part: TextPart fallback + DataPart payload.
- **`TaskStatus` serializes to `{state, message?, timestamp?}` only** — internal fields (`note`, `error_category`, `source`, `usage`) are whitelist-stripped before the wire.
- Server-emitted `contextId` is always a non-empty UUID and present on every emitted `Task`/`Message`.
- Extension negotiation: `X-A2A-Extensions` request → response echoes the activated subset.
- `AgentError{category, message, source?, a2a_code?, detail?}` is the **internal** error model only — it is never emitted on the wire. Wire errors are the spec error shape (`{code, message, data?}` with the HTTP status mapping above), built from it; no input values, no credentials in either.

### 5.2 Task store

`TaskStore` interface; `InMemoryTaskStore` default (LRU 1000 / TTL 1h, per-subscriber bounded queues maxsize 256, sentinel close), plus the resume channel for interrupted tasks (§5.1). Tasks carry their creating identity (§5.1 binding). Process-local — see the §2 deployment invariant.

Lifecycle rules the implementation must honor:

- **Interrupted tasks** get their own TTL (`AGENT_SDK_INTERRUPT_TTL`, default 30 min — a confirmation window, distinct from the general 1h task TTL) and are excluded from LRU pressure-eviction while waiting — bounded by `AGENT_SDK_MAX_INTERRUPTED` (default 100): at the cap, a new interrupt becomes a typed task failure instead of pinning another worker (each interrupted task holds a paused coroutine; without the cap an interrupt flood bypasses the LRU bound). On interrupt-TTL expiry or any eviction, the store **cancels the paused worker coroutine, closes the resume channel, and sentinel-closes all subscriber queues** — nothing leaks; a later resume gets 404 + -32001.
- **Subscriber queue overflow** (slow consumer hits maxsize 256): that subscriber's stream is terminated without a `final` frame — never silent frame-dropping, which could swallow `final: true` and hang the consumer forever. Termination engages the documented re-subscribe path.

Documented consumer contract: a stream severed without a `final` frame → re-`:subscribe`; 404 → task expired (restart, TTL, or confirmation window elapsed).

### 5.3 AG-UI

`POST /ag-ui/run`, SSE: `data: <camelCase JSON>\n\n`, no `event:` line, `Content-Type: text/event-stream` on **every** code path.

**Request:** `RunAgentInput` — `threadId`, `runId`, `messages`, and (required per spec, defaulted leniently to empty values when absent for client interop) `state`, `tools`, `context`, `forwardedProps`. The SDK's OpenAPI schema documents all of them as required; the console always sends all of them.

**Event stream contract:**

- `RUN_STARTED` is always the first frame. **All validation runs inside the generator**: any failure — message caps, control chars, missing registry — emits `RUN_STARTED` then `RUN_ERROR`; the route handler never raises before the `StreamingResponse` exists (m365 pattern; the other two references get this wrong).
- `STATE_SNAPSHOT(snapshot=input.state ?? {})` immediately after `RUN_STARTED` — explicit ordering: `RUN_STARTED` → `STATE_SNAPSHOT` → `STEP_STARTED(turn-1)` (stateless baseline; loop may inject further `STATE_SNAPSHOT`/`STATE_DELTA`). The SDK never emits `MESSAGES_SNAPSHOT` (client owns history).
- One `STEP_STARTED`/`STEP_FINISHED` pair **per model turn**, `step_name="turn-{n}"`, keyed on the typed `TurnStartedEvent` (§2) — never on ProgressEvent text; every open step is closed on all paths including errors (pitchbook's guaranteed-close pattern).
- Text message triplets; tool-call families with pairing preserved; `ToolCallResultEvent.message_id` is a **fresh UUID**, never derived from `tool_call_id`.
- Terminal: `RUN_FINISHED` or `RUN_ERROR`, exactly one.
- No `THINKING_*` events (deprecated). `REASONING_*` family reserved for a future extended-thinking minor.

**History processing (not rejection):** truncate to most-recent 50 messages (oldest dropped); >4000-char messages truncated with a logged warning; blank assistant turns silently skipped during the Bedrock fold. `RUN_ERROR` is reserved for agent-side failures, not large-but-valid client history.

**CUSTOM events — frozen payload contracts** (consumers read exactly these):

| name | value shape |
|---|---|
| `AGENT_ARTIFACT` | `{dataType, toolName, data}` |
| `A2UI_UPDATE` | `{messages: [<a2ui message>, …]}` (translator list wrapped under `messages`) |
| `AGENT_PROGRESS` | `{message: str}` |
| `AGENT_NOTE` | `{note: str}` |

The card's `x-agui.customEvents` list and the console's routing table are asserted equal by a unit test; adding a name to one side without the other fails the build.

**Interrupts (action_gate path):** `RUN_FINISHED` with `outcome={type:"interrupt", interrupts:[{id, reason, message, response_schema, tool_call_id}]}` — `tool_call_id` links the interrupt to the pending tool call (action_gate requires it; the spec field is optional); resume via new `RunAgentInput` with `resume=[{interrupt_id, status, payload}]`. The §5.1 identity binding applies to this path identically: an AG-UI resume must come from the identity that started the interrupted run. Custom events are not used for interrupts.

### 5.4 A2UI v0.9.1

- **Delivery:** over A2A — DataPart artifacts, `metadata.mimeType = "application/a2ui+json"` (the legacy `application/json+a2ui` is accepted inbound, never emitted); over AG-UI — `A2UI_UPDATE` CUSTOM events (§5.3 shape). One translator feeds both.
- **Sequence per artifact — one `list[dict]`, never a bare dict:** `createSurface` → `updateComponents` → `updateDataModel` → `deleteSurface`, all four in the same array (per-artifact self-cleaning surfaces; `deleteSurface` is NOT deferred to task completion). The first `updateComponents` for a surface establishes exactly one component with `id: "root"` (spec MUST — a conforming client buffers forever otherwise). Every message carries `version`. `deleteSurface` semantics are defined in §7.1 — it closes the surface's update lifecycle; the rendered output persists in the transcript.
- **Catalog ids:** Standard Profile surfaces always emit `catalogId: "urn:a2ui-profile:standard:v1"`. Domain components get **their own surface** with the domain `catalogId` — surfaceId+catalogId are immutable once set; the two catalogs never share a surface.
- **Capability extraction (transport-specific, resolved by the route, never by tools/translators):** A2A → `message.metadata.a2uiClientCapabilities`; AG-UI → `forwardedProps.a2uiClientCapabilities`. Absent → `tier="core"`, `catalogs=[standard]`.
- **Tier gating:** Extended types emitted only on `tier="core+extended"`. The full Extended gate set: `waterfall_chart, multi_category_chart, fund_performance, email_list, calendar_events, user_profile, user_list, document_list`. (m365 currently doesn't gate its three — SDK corrects this.)
- **Domain gating:** a domain component is emitted only when the client's `a2uiClientCapabilities.catalogs` includes that domain `catalog_id`. Tier alone never unlocks domain types.
- Fallback: when a type is gated off, the artifact still ships its TextPart (`to_plain_text()`); nothing is silently dropped.

### 5.5 MCP (2025-06-18) + OAuth 2.1

**Streamable HTTP at `/mcp` — three verbs:**

- `POST /mcp` — JSON-RPC; always responds with `application/json` regardless of `Accept` header (MCP 2025-06-18 §3.2 permits a JSON response to SSE-accepting clients — SSE is reserved for `GET /mcp` streaming only). Session id allocated on `initialize`, returned via `Mcp-Session-Id` header; unknown/expired session → 404 (except `initialize` itself, the recovery path).
- `GET /mcp` — server→client SSE channel: returns `text/event-stream` with heartbeats (returning 405 breaks Claude.ai Desktop — LRN-053).
- `DELETE /mcp` — session termination: honors `Mcp-Session-Id`, idempotent, 204.
- `MCP-Protocol-Version` header **validated when present** on post-init requests (the spec says SHOULD-send, not MUST): present-but-unrecognized → 400; absent → assume `2025-03-26`; version-future fields gated on the negotiated version.

Legacy SSE pair (`GET /mcp/sse` + `POST /mcp/messages?session_id=`) retained for older clients.

**Methods:** `initialize` — echo the client's `protocolVersion` if we support it; otherwise return our highest supported version and let the client decide whether to continue. `ping`; `tools/list` — Tier 1 only, each tool with `inputSchema` **and `outputSchema`** (derived from the `emits` model — `structuredContent` is never emitted unclaimed); `tools/call` — validate → execute → result with `structuredContent` + serialized `text` block; tool failures are `isError: true` results, never JSON-RPC errors. Capabilities declare `listChanged: false` (no notifications we don't send). `notifications/*` acknowledged with 202, never answered.

**OAuth chain (Claude.ai connector compatible):**

- `/.well-known/oauth-protected-resource` **and the path-suffixed `/.well-known/oauth-protected-resource/mcp`** (Claude probes the suffixed form first). `resource` is the **absolute canonical URI** `{PUBLIC_URL}/mcp` — the same exact string used in `authorization_servers` checks, the `resource` parameter, and token audience.
- `/.well-known/oauth-authorization-server` (RFC 8414) — includes `code_challenge_methods_supported: ["S256"]` (load-bearing for Claude.ai's PKCE probe), `grant_types_supported`, `response_types_supported`, `token_endpoint_auth_methods_supported`.
- `POST /oauth/register` (RFC 7591, unauthenticated DCR — rate-limited per §6, registration cap with LRU eviction of never-consented clients).
- `GET/POST /oauth/authorize` — consent gated on a real admin API key (header-borne; OAuth-kind tokens rejected here). **RFC 8707 `resource` parameter: accepted and validated at authorize (omitted → defaults to the canonical MCP URI), persisted into the auth code, carried from code metadata into minted tokens and through refresh rotation. It is NOT re-required as a parameter at the token request** — Claude.ai does not send it there; requiring it would break the live connector.
- `POST /oauth/token` — PKCE S256 exchange + single-use refresh rotation; `scope` omitted from the response when empty (never `"scope": ""`).
- `POST /oauth/revoke` (RFC 7009).
- 401 responses carry `WWW-Authenticate` pointing at the PRM (degrading header-less on malformed Host, never 503).

**Auth on `/mcp`:** API key or OAuth token; resolved identities are **`kind`-tagged** (`"api_key"` | `"oauth"`). **Token audience enforcement — explicit two-value equivalence:** the accepted audience set is exactly `{PUBLIC_URL origin, {PUBLIC_URL}/mcp}`; anything else → hard 401, never log-and-allow. (Deliberate, documented deviation from strict RFC 8707 single-URI matching: Claude.ai sends the bare origin as `resource` in some flows — pitchbook's live-connector behavior, kept. The real privilege boundary is kind-based surface assertion, below.) Surface assertions: `/admin/*`, `/oauth/authorize`, and key-management endpoints reject `kind="oauth"`; `/mcp` accepts both kinds; `/oauth/revoke` accepts oauth-kind callers **for their own tokens only** (self-revocation); `/oauth/token` is unauthenticated by design (public client + PKCE).

**CORS (exact shape required by Claude.ai):**

```
Access-Control-Allow-Origin: https://claude.ai (+ configured origins; never *)
Access-Control-Allow-Methods: GET, POST, DELETE, OPTIONS
Access-Control-Allow-Headers: Authorization, Content-Type, Mcp-Session-Id,
                              Accept, Last-Event-ID, MCP-Protocol-Version,
                              X-A2A-Extensions, X-Agent-Credentials
Access-Control-Expose-Headers: WWW-Authenticate, Mcp-Session-Id, X-A2A-Extensions
```

`Expose-Headers: WWW-Authenticate` is load-bearing (without it the browser cannot read the 401 challenge and discovery never starts). OPTIONS preflight returns **204** (Starlette returns 200 — the SDK ships the rewrite middleware).

### 5.6 Surface parity rule

Tier 1 tools appear on A2A + MCP; Tier 2 on A2A only. Card, `tools/list`, and console all render from the single ToolRegistry.

---

## 6. Auth and credentials

- **Persistence:** API keys (sha256-hashed), OAuth client registrations, and refresh tokens persist in **reserved namespaces of the encrypted SQLite store** — restarts never wipe Claude.ai connector registrations. Auth codes are memory-only (short-lived, single-process).
- **API keys:** bearer, sha256-hashed at rest, constant-time comparison, prefix-only display. **Last-key protection:** revoking the final admin key is refused (pitchbook LRN-049) — lockout is impossible by that path.
- **Bootstrap (no TOFU race):** whenever the key store holds **zero keys** at startup, a single-use bootstrap token is generated in memory and printed to stdout; the first `POST /admin/api/keys` requires it (atomic consumption). It expires after 15 minutes (it lands in log aggregation — the TTL bounds that exposure); a restart regenerates it and invalidates the old one. There is no window where key-minting is open to the network. The zero-keys re-arm covers fresh deploys and wiped volumes; recovery from a *lost key plaintext* (hash still stored, so the store is never zero) is an out-of-band store wipe — which also destroys stored credentials and connector registrations, stated plainly in the ops docs. Every bootstrap-path request is loudly logged. (Replaces the references' open-until-first-key mode.)
- **Identity kinds:** every resolved identity carries `kind`; per-surface assertions per §5.5.
- **Rate limiting — two layers:** per-identity sliding window after auth (default 100/min); **per-IP windows on all unauthenticated paths** (auth failures, `/oauth/register`, `/oauth/token`, consent) so key brute-force and DCR flooding are throttled. Client IP derived per the `AGENT_SDK_TRUSTED_PROXIES` rule (§4.4) — never blind `X-Forwarded-For`. The per-IP map is a bounded LRU (cardinality cap, no memory-exhaustion vector). Both in-memory (single-process invariant, §2). 429 + Retry-After.
- **MASTER_KEY:** ≥32 chars, generated (the template and `/new-agent` generate it; humans never invent it). KDF pinned: PBKDF2-HMAC-SHA256, ≥600k iterations, per-store random salt stored alongside the DB (argon2id considered post-v1). Rotation: `python -m agent_sdk rotate-master-key` (decrypt-all/re-encrypt-all; **offline-only** — refuses to run while the server holds the DB) ships in v1.
- **Credential namespacing:** store keys are `{source_name}/{field}`; an adapter can only resolve its own namespace; Bedrock credentials live in a reserved namespace no adapter can read.
- **Secrets hygiene:** SecretStr for MASTER_KEY; validation errors strip input values; `redact.key_prefix()` wherever a secret is displayed; no credentials in errors/logs.

---

## 7. Admin / test console

Ships in the wheel; vanilla JS, no build step, **strict CSP (no `unsafe-inline`)** — the no-build design must satisfy this from day one. Console auth is **header-borne bearer only (sessionStorage), never cookies** — stated as an invariant so cookie sessions (and their CSRF surface) cannot creep in. Consent page: `frame-ancestors 'none'` / `X-Frame-Options: DENY`. The chat/A2UI renderer treats all model output as untrusted: text nodes only, sanitized attributes — a tested SDK invariant, since the console origin holds the admin token.

| Screen | Function |
|---|---|
| Overview | health, upstream checks, usage/cost per key, rate-limit status |
| Credentials | forms generated from `CredentialField` schemas (+ Bedrock creds); url-typed fields validated §4.2 |
| API Keys | mint/revoke; bootstrap-token first-run flow |
| Tools | catalog from registry, per-tool "Try" with `sample` inputs |
| Chat | A2A + AG-UI test client: SSE trace, artifacts, A2UI rendering; sends all required RunAgentInput fields; routes ALL declared CUSTOM events |
| MCP | initialize/tools/list/tools/call exerciser + OAuth connector walk-through (DCR → consent → token → authenticated call) |
| Self-check | runtime probes: card shape, A2A endpoints + final-frame, AG-UI first-frame, MCP verbs + version header, OAuth discovery chain incl. suffixed PRM, CORS preflight |

### 7.1 Console A2UI renderer (Path A) — required behaviors

Surface registry keyed by `surfaceId`; fold `createSurface`/`updateComponents`/`updateDataModel` **atomically and paint once** — never repaint mid-array (pitchbook's renderer repaints on `updateDataModel`; the SDK console does not inherit that); JSON Pointer (RFC 6901) resolution for data bindings; ChildList template expansion supported (list-shaped Profile types need it).

**`deleteSurface` semantics (defined, documented deviation from a literal single-fold reading):** `deleteSurface` is applied as a post-paint step — it closes the surface (registry entry removed, further updates for that surfaceId rejected) while the painted DOM persists as a transcript snapshot. Folding it into the atomic pass would render nothing at all for self-cleaning per-artifact surfaces (§5.4); show-then-close is the intended UX and is stated here as the SDK-wide rule for both the console and consumer guidance.

Scope (explicit): the v1 renderer is display-only — two-way input binding and `action` dispatch are out of scope (no FROZEN Standard Profile type is interactive); they arrive with any future interactive type. `MarketBriefing` renders as inline prose — no card chrome (the one Profile type with a rendering rule); unknown component types render the artifact's TextPart fallback.

---

## 8. ModelClient seam

```python
class ModelClient(Protocol):
    async def converse(self, *, system, messages, tools, max_tokens) -> ModelResponse: ...
    # reserved (non-breaking to add): async def converse_stream(...)
```

v1: `BedrockModelClient` — boto3 Converse on a **dedicated bounded executor** (model calls never starve the default `to_thread` pool); credential chain (Bedrock API key → IAM static → default); ARN/region from config only.

Loop policies: max 20 turns; per-tool timeout Tier 1 = 130s / Tier 2 = 180s; **per-task wall-clock deadline (default 10 min) and token budget (default configurable), exceeded → typed failure event** (cost-runaway guard the references lack). The deadline clock **suspends while the task sits in an interrupt state** (`input-required`/`auth-required`) and resumes on resume — otherwise every action_gate confirmation slower than 10 minutes would fail by default; the interrupted-task TTL (§5.2) owns that waiting period. The token budget is **cumulative across resume cycles** (it guards spend, which resumes don't reset). Per-call result cache (task-local); AgentError from a tool → tool result, never a crash.

---

## 9. Contrib modules — v1 status: EXPERIMENTAL

All four ship in v1 as extras (`pip install agent-sdk[obo]`) but are explicitly **provisional** (§4.0): generalized from m365 with no second consumer yet, they are excluded from the SemVer promise until the m365 port (§13) validates them.

- **`action_gate`** — `confirm=True` tools: proposal artifact → A2A `input-required` resume (§5.1) / AG-UI interrupt outcome (§5.3) → confirmed execution.
- **`obo`** — MSAL on-behalf-of: assertion extraction, token exchange (cached, 300s buffer), auth-context threading to adapters. Graph scope helpers included.
- **`commitments`** — durable scheduled actions: SQLite store + lifespan executor, graceful shutdown.
- **`webhooks`** — generic inbound subscriptions: endpoint registration, `clientState` validation, named-handler dispatch; `webhooks.graph` as first implementation.

---

## 10. Distribution and template

### 10.1 Distribution (git dependency — made buildable)

- Pin by **tag + commit SHA**: `agent-sdk @ git+ssh://…@<sha>` (tags are mutable; SHAs aren't). The harness records the tag in a comment.
- **The template Dockerfile ships BuildKit SSH support** — `# syntax=docker/dockerfile:1`, `RUN --mount=type=ssh pip install …`, GitHub's **published host-key fingerprints baked statically** (never build-time `ssh-keyscan` — that's TOFU) — and the README documents `docker build --ssh default` locally and the ssh-agent/deploy-key step for CI runners.
- The HTTPS+token variant is hardened against token persistence: the token enters **only** via `RUN --mount=type=secret` read inside the install step (never a build ARG — ARGs land in layer history), URL form `https://x-access-token:${TOKEN}@…` (password slot — pip's PEP 610 `direct_url.json` redaction covers passwords, not bare userinfo), `pip install --no-cache-dir`, and a **CI assertion that the final image's layers and `direct_url.json` contain no token**.
- `/new-agent` preflights `ssh -T`/token access before rendering, so week one isn't spent on auth plumbing.
- Graduation path documented: publishing wheels (GitHub Releases or a private index) requires no SDK changes; templates switch to version+hash pins.

### 10.2 Template contents

```
{agent-name}/
├── pyproject.toml        # agent-sdk @ git+ssh://…@<sha>  (tag in comment)
├── .env.example          # MASTER_KEY auto-generated by /new-agent; PUBLIC_URL, BEDROCK_*, PORT
├── Dockerfile            # BuildKit ssh mount, multi-stage, non-root, --workers 1, /data, healthcheck
├── CLAUDE.md             # security invariants + SDK conventions (harness-enforced)
├── src/
│   ├── main.py           # §4.1 shape
│   ├── config.py         # Settings + make_settings() factory
│   ├── persona.py
│   ├── sources/{name}.py
│   ├── tools/…           # ToolSet modules
│   └── skills/           # foundational/*.md + jobs/*/SKILL.md
└── tests/                # agent_sdk.testing fixtures (isolated Agent, FakeModelClient)
```

### 10.3 Escape hatches (supported, tested)

`build_app()` returns a plain FastAPI app: mounting team routes/middleware after build is supported and covered by SDK tests. **Auth boundary for team routes:** SDK auth is implemented as per-route dependencies, not global middleware — team-mounted routes are therefore unauthenticated until the team adds `Depends(agent_sdk.auth.require_identity)`; this is stated loudly in docs, and the self-check screen lists mounted routes that carry no SDK auth dependency. Team middleware added post-build wraps outside SDK middleware (Starlette ordering) and must be added before startup. `Agent(lifespan_extras=[…])` for team-owned resources (their DB pools live inside the managed lifespan).

**Deployment topology: one origin (subdomain) per agent is the supported shape.** Path-prefix deployments (`https://host/agents/foo/`) are **not** plainly supported: RFC 8615 well-known URIs are origin-rooted, so the agent card, PRM (including the path-suffixed variant `/.well-known/oauth-protected-resource/agents/foo/mcp`), and AS metadata must be served at the origin root — which a mounted app can never reach. Teams that must use path prefixes get documented reverse-proxy rewrite rules for the well-known namespace; the runtime self-check verifies externally-visible URLs either way. All advertised URLs derive from `PUBLIC_URL`.

Console override: an agent-provided static dir shadows SDK assets file-by-file. Dependency policy: the SDK declares lower-bound-only constraints; the template owns exact pins.

---

## 10.4 Scheduling and background tasks

The SDK does **not** ship an `agent_sdk.scheduler` module.  The correct and only entry point for background tasks and periodic work is `Agent(lifespan_extras=[…])`.  See the `Agent.__init__` docstring for the full contract and a minimal `asyncio.create_task` example.

`lifespan_extras` callables receive the live `FastAPI` app (giving access to `app.state.settings`, `app.state.registry`, `app.state.adapters`, etc.) and are entered as async context managers inside the SDK's own lifespan, after source adapters are initialised.  Teardown (cancellation, store close) happens in reverse order on shutdown.

**Two contrib reference implementations** (both in `agent_sdk/contrib/`):

| Module | Lifespan helper | What it does |
|--------|----------------|--------------|
| `contrib.commitments` | `commitments_lifespan(…)` | Polls a `CommitmentStore` (SQLite or Azure Table) and fires due tool calls; graceful shutdown with at-most-once semantics (DESIGN §9). |
| `contrib.webhooks` | `webhooks_renewal_lifespan(…)` | Periodically renews near-expiry Graph webhook subscriptions; uses the same `SubscriptionBackend` the route adapter writes to. |

Both follow the identical wiring pattern:

```python
from agent_sdk.contrib.commitments import commitments_lifespan
from agent_sdk.contrib.webhooks import webhooks_renewal_lifespan

agent = Agent(
    ...,
    lifespan_extras=[
        commitments_lifespan(poll_interval=30.0),
        webhooks_renewal_lifespan(...),
    ],
)
```

For custom periodic work, copy the minimal pattern from the `Agent.__init__` docstring: create an `asyncio.Task` inside an `@asynccontextmanager`, cancel it in the `finally` block.  Do **not** import `agent_sdk.scheduler`; it does not exist.

---

## 11. Claude Code harness (plugin)

| Component | Type | Function |
|---|---|---|
| `/new-agent` | skill | interview (name, domain, sources, auth model, contrib) → preflight git access → render template → generate MASTER_KEY → first run + console walkthrough |
| `/add-tool` | skill | input model + `@tools.tool` fn + test + console sample; wires `emits` |
| `/add-source` | skill | SourceAdapter subclass + CredentialFields + allowed_hosts + health check + test |
| `sdk-advisor` | agent | knows SDK extension points/conventions |
| `/agent-verify` | skill | run agent → `agent-stack-check` → curl OAuth-chain probes → Playwright console probe (**optional leg** — degrades gracefully on runners without browsers) → report |
| CLAUDE.md template | file | invariants: no raw httpx in tools, no secrets in errors, path-param validation via SDK helpers, adapters own retries, SKILL.md conventions |

---

## 12. Versioning, releases, CI

- SemVer over the **stable core** (§4.0); provisional surfaces may change in minors with CHANGELOG notice. Tags `vX.Y.Z` + recorded SHA. CHANGELOG mandatory.
- CI on every PR:
  1. unit tests;
  2. **build the wheel and install it** (catches missing console assets — the smoke runs against the installed wheel, never the source tree);
  3. boot the example agent on a real HTTP port **with `PUBLIC_URL` set** (a dev-fallback card would weaken the card checks);
  4. `agent-stack-check` + per-protocol checks;
  5. **curl-level probes** the umbrella check doesn't own: unauthenticated 401 + WWW-Authenticate, both PRM endpoints, AS metadata fields, CORS preflight (204 + headers), GET/DELETE /mcp, unknown-session POST /mcp → 404, token-leak assertion on the built image (§10.1);
  6. Playwright console smoke;
  7. model-shape fidelity: the FakeModelClient replays **recorded real Converse responses** (fixtures captured once from Bedrock) so translators are exercised against real wire shapes without AWS credentials in CI.
  8. **`python -m agent_sdk test-chat`** end-to-end smoke: boots the example agent in-process (`--app src.main:app`), drives one AG-UI turn and one A2A turn, and asserts the reply is non-empty and the A2UI artifact is emitted on both transports (`docs/testing.md`).
- Release gate additionally runs `claude mcp add --transport http <url>` as the cheapest Claude-connector correctness probe.

### Developer use

During development `python -m agent_sdk test-chat --app src.main:app` drives a live turn without a browser.  For a running server, `--url http://localhost:<PORT> --token <key>`.  See `docs/testing.md` for the full interface and for using `ChatDriver` directly in integration tests.

---

## 13. Migration validation

1. Clone `agents/investment_analyst` → `agents/investment_analysts_v2`; port onto the SDK. Success: template-footprint repo; side-by-side console parity; clean `agent-stack-check`; no tool-test regressions. API friction feeds back before v1.0.0.
2. **m365 port follows before contrib modules graduate from experimental** — action_gate, obo, commitments, webhooks have no real consumer until then (§9), and an SDK validated only by a plain-query agent would never exercise interrupts, OBO, or scheduling.

---

## 14. Known risks

| Risk | Mitigation |
|---|---|
| Reference agents drifted; several reference behaviors are spec-defective | §1 lists the defects explicitly; SDK follows spec; red-team review validated each choice |
| In-memory state vs restarts/replicas | single-process invariant enforced (§2); `TaskStore` interface for a shared backend later; consumer contract documented (§5.2) |
| OAuth subtleties (rotation races, audience) | port pitchbook's hardened core, plus §5.5 corrections (8707 resource at authorize, suffixed PRM, two-value audience set with hard reject outside it, kind tagging) |
| Bedrock non-streaming = chunky SSE | acceptable v1; `converse_stream()` reserved |
| Contrib generalized without a second consumer | experimental status until the m365 port (§13) |
| Teams editing generated files | all generated files are domain-owned by design; SDK behavior unreachable from the template |
