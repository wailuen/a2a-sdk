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
| A2UI | v0.9.1 + Standard Profile v1.1 (18 types: 14 FROZEN + 4 RESERVED) | `a2ui-check` |
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

**Per-task date suffix (GH-154):** `app.state.system_prompt` (persona, skills catalog, A2UI section) is rendered once at boot and never mutated. When `inject_current_date` is on, the task worker appends `\n\nToday is YYYY-MM-DD (<tz>).` as the LAST segment, computed once per task (stored on the task record, so resumed turns keep the original date). It goes last so the stable prefix stays cacheable by future prompt caching.

**Deployment invariant: exactly one process per deployment.** The task store, SSE subscriber queues, and rate limiter are process-local. The template Dockerfile hard-codes `--workers 1`; `BaseAgentSettings` refuses `WEB_CONCURRENCY > 1` with an explanatory error. Multi-replica support arrives only with a shared `TaskStore` backend (post-v1). OAuth server state (IdP flows, consent tickets, auth codes, access tokens) and MCP sessions are also per-process, so any deployment serving `/mcp` or OAuth connectors requires exactly one replica (GH-162); shared sign-in storage is deferred work.

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
│   ├── content_types.py    # Standard Profile v1.1 models — ALL 14 FROZEN types,
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
│   ├── _consent_ui.py      # shared consent + notice (error, hand-off) page layout (TPC mark, light/dark, phone); inline-only for the consent CSP
│   ├── _tpc_logo.py        # TPC mark as an inline SVG constant
│   ├── admin.py            # console API (credentials, keys, usage, samples)
│   └── health.py
├── a2ui/
│   ├── translator.py       # content model → message-envelope sequences (§5.4)
│   └── catalog.py          # Standard Profile v1.1 registry + domain-catalog extension API
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

- **Stable core (strict SemVer):** `Agent`, `ToolSet`/`@tool`, `SourceAdapter`, `BaseAgentSettings`, `Reusable`/`ReuseKind`/`DeferredResult` (§8.1; `tests/test_public_api_exports.py` pins these as top-level `agent_sdk` exports), wire shapes in `models/`, Standard Profile contracts, the template contract.
- **Provisional (may change in minors, with CHANGELOG notice):** `agent_sdk.testing`, console internals, everything under `contrib/`.
- **Wire-shape conformance exemption:** a breaking change to a stable-core wire shape in `models/` is exempt from the major-bump requirement when its sole purpose is bringing the SDK's wire output/parsing into conformance with an external protocol spec (A2A, AG-UI, A2UI, MCP) rather than a voluntary redesign — it may ship under a patch or minor bump instead. The exemption is conditional: the release MUST carry a dedicated `🔴 Breaking changes` CHANGELOG heading naming the exact type/field, both directions of impact (emit + parse), and an explicit Migration callout (precedent: 0.5.40's `TaskStore.interrupt_ttl_remaining`; 0.5.44's `DataPart.data` narrowing for GH-128). A voluntary breaking change to the stable core — not required by spec conformance — still requires a major bump; this exemption cannot be cited for those. This is the standing rule referenced by CHANGELOG breaking-change entries — it need not be re-argued from precedent release-by-release. It is an owned, signed-off decision: see REVIEWS.md Round 7 (w038 group G) for the rejected alternative (require a major bump for every stable-core wire break) and the accepted risk to `~=0.5.x` pinners.

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
    emits=TimeSeriesChart,         # → x-sdk render hints + MCP outputSchema; a tuple (A, B) for a dispatcher tool (GH-225)
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

`build_app()` validation (all failures raise at boot, never at call time): every adapter annotation resolves to a registered adapter class; duplicate tool names raise; duplicate `source_name` or repeated `register_source` of the same class raises (registration is once-per-class); every `emits` type is a known Profile/domain type; declared CUSTOM event names match the console routing table (§5.3); every `exclude_from_catalog` name resolves to a skill discovered under `skills_dir`.

**Skills catalog exclusion:** `skills_dir` scanning folds a `name: description` catalog line per skill into the system prompt (§2), with full bodies loaded on demand through the built-in `load_skill` tool. `Agent(exclude_from_catalog=[...])` omits named skills from that catalog text — validated at `build_app()`, never a post-build mutation — while `app.state.skills.load(name)` (and `load_skill`) still resolves them; they are simply not advertised. `app.state` is otherwise frozen after `build_app()` (no `rebuild_skills_catalog()`-style hook), so this is the **recommended pattern for always-on/guardrail skills**: inline the skill's content directly into `persona`/`artifacts_dir` so it is unconditionally present in the system prompt rather than gated behind the model choosing to call `load_skill`, and list that same skill's name in `exclude_from_catalog` so its now-redundant catalog entry doesn't duplicate instructions the model already always sees.

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

The SDK ships **all 14 FROZEN** Standard Profile v1.1 types as Pydantic models whose field shapes are **wire-isomorphic with the Profile contracts** (no adapter remapping layer to drift): Core — `KpiCard` (`metrics: [{label, value, …}]`), `TimeSeriesChart` (`x_key, y_key, data, total_count`), `ComparisonTable`, `BarChart`, `EntityList`, `MarketBriefing`; Extended — `WaterfallChart`, `MultiCategoryChart`, `FundPerformance`, `EmailList`, `CalendarEvents`, `UserProfile`, `UserList`, `DocumentList`. The 4 RESERVED types (`TradeActivity`, `CompanyInfo`, `DealList`, `InvestorProfile`) are name-allocated only — no field contract, no translator. Class names equal wire component names exactly (case-sensitive renderer lookup).

**Text fallback carries follow-up identifiers (GH-156).** `to_plain_text()` is the text block on MCP `tools/call`, the A2A `TextPart` and the admin try-tool, so it must include every identifier a follow-up call needs: `EntityList` item `id`, `EmailList` message `id` (+ `conversation` id where present), `CalendarEvents` event `id`, `UserList` user `id`, `UserProfile` `id` and manager `id`, `DocumentList` document `id`, and `FundPerformance.pb_id`. Each id is rendered via `safe_id_text` (SI-2) on its own labelled `id:` line (GH-167), and in a `ComparisonTable` column marked `ColumnDef(is_id=True)` (GH-212). The id alphabet (GH-212, ruling https://github.com/wailuen/a2a-sdk/issues/212#issuecomment-6359828392): `( )`, single spaces and `= + / : , . _ - ! ~ @` stay byte-exact, a run of whitespace collapses to one space, control characters are stripped, `| < > [ ]` are neutralised, length is capped. Joined-slot exception (https://github.com/wailuen/a2a-sdk/issues/212#issuecomment-6366237627): the two ids joined into a row with other fields, `EmailList` `(id: ..., conversation: ...)` and `FundPerformance.pb_id` (`source <pb_id>` in the ` | ` row), render through `safe_joined_id_text` (whitespace -> `_`, `( )` swapped for look-alikes, same neutralisation and 256-char cap), so they cannot forge a second `id:`/`conversation:` or a fake figure. The MCP text block stays `to_plain_text()`, not serialized JSON (§5, unchanged). `tests/test_content_types.py` derives the expected ids from the model fields (LRN-241).

**Standalone vs joined text slots (GH-167, refines GH-130/RT-005; ruling https://github.com/wailuen/a2a-sdk/issues/167#issuecomment-6137225466).** Each untrusted value in `to_plain_text()` is rendered by where it sits. Joined with other text on its line (column, `label: value` detail, `(type)`, `k=v`, dates, `EmailList` rows and their `preview`): `safe_cell_text` (separator look-alikes). Alone on its own line (titles, names, summaries, as-of headers): `safe_line_text` (line-break and control-char collapse, surrounding whitespace stripped, 256-char cap, `( ) [ ] < > = , : |` kept; per the ruling, only the line-break/control-char collapse applies, with no swap option). A standalone title above delimited rows keeps ASCII too, and the rows are indented so the column-0 title cannot pass for one: `KpiCard` (`Title` / `  label: value` / `    trend: ...`), `ComparisonTable` (`Title` / `  header` / `  ---` / `  a | b`). Ids sit on their own labelled line via `safe_id_text` (GH-212: `( )` and single spaces kept verbatim there), so names are never joined to them: `EntityList` (`  - Name` / `    id: <id>`), `UserList` (`  - Name` / `    email:` / `    title:` / `    id:`), `UserProfile` (name line / `  email:` / `  id:`; `  manager: Name` / `    email:` / `    id:`), `DocumentList` (`  - Name` / `    type:` / `    modified:` / `    id:`), `CalendarEvents` (`  - Subject` / `    start – end @ place` / `    id:`). `MarketBriefing` renders `Title` and `as of: <as_of>` as two lines. `EmailList` keeps its single-line ` | ` rows with `(id: ..., conversation: ...)`, and `FundPerformance` its ` | ` row with `source <pb_id>`; both joined ids use `safe_joined_id_text` (GH-212 joined-slot exception, above). `safe_cell_text` is unchanged. Trade-off: a standalone slot can start with text like `id: x`, but it is one collapsed line at a fixed position and cannot carry indentation, so it cannot stand in for the real indented `id:` line. `tests/test_content_types.py` (GH-167 blocks).

Three non-obvious contracts: `MarketBriefing` is the only type whose wire `data` is a **markdown string** — the translator emits `model.to_markdown()`, never `model_dump()`. **Consequence — the one `metadata` carve-out (RT-008):** because that path calls `to_markdown()` rather than `to_plain_text()`, and `to_markdown()` is deliberately kept free of the suffix, a `MarketBriefing`'s `metadata` envelope **does not reach the A2UI surface at all** — not in the `updateDataModel` value, and so not in any Path-A renderer or the admin console (whose `appendMetadataFootnote` only reads object-valued data). The "unskippable" guarantee below is a guarantee about `to_plain_text()`, which is where a `MarketBriefing`'s metadata still surfaces (the A2A dual-part TextPart, the MCP `text` block) — it is **not** a guarantee about the A2UI wire value for this one type. Practical rule for agent authors: **do not put disclosure, compliance or provenance text that an A2UI client must see in `MarketBriefing.metadata`** — put it in the `prose` body, which is the only field of that type an A2UI client renders. Every other content model emits `wire()` and carries `metadata` on both surfaces. `model_dump()` of any content model is **never** placed on the wire directly — the translator (§5.4) is the sole emission path (it adds envelopes, computes nothing); and **every content model (FROZEN and domain) implements `_body_text() -> str`** — the abstract hook behind `to_plain_text() -> str`, the required interface backing the A2A dual-part TextPart fallback (§5.1, §5.4), enforced by the base-model ABC. `to_plain_text()` itself is CONCRETE on `ContentModel` (`self._body_text() + self._metadata_suffix()`) and must not be overridden — that split is what makes the `metadata` suffix below unskippable rather than a per-subclass convention (a card that overrides `to_plain_text()` anyway still works: `__init_subclass__` adopts the override as its `_body_text()`). The bare-markdown-string shape is the AG-UI/A2A (translator) wire contract only; on the MCP surface, `MarketBriefing`'s `structuredContent`/`outputSchema` is instead a JSON object `{"markdown": <str>}`, per MCP 2025-06-18's object-only requirement for both fields (GH-105) — see §5.5.

Domain cards live in the agent repo: subclass `ContentModel`, declare `data_type` (snake_case) / `component` (PascalCase wire name) / a non-Profile `catalog_id`, implement `_body_text()`, and register the class (import the module so registration runs at boot — no module-level global):

```python
class CompanyProfile(ContentModel):
    data_type: ClassVar[str] = "company_profile"
    component: ClassVar[str] = "CompanyProfile"                      # globally unique wire name
    catalog_id: ClassVar[str] = "urn:a2ui-catalog:acme-finance:v1"  # never the standard-profile URI
    # …instance fields = the wire data shape…
    def _body_text(self) -> str: ...          # NOT to_plain_text — the base class owns that

register_content_type(CompanyProfile)
```

`register_content_type` enforces uniqueness of **both** `data_type` **and** the wire `component` name across the whole registry (A2UI resolves components by bare componentType with no catalog qualifier, so a duplicate name — even under a different `catalog_id` — would silently shadow), refuses the four RESERVED names, and rejects any new type that claims the frozen standard `catalog_id`. Negotiation mechanics in §5.4. The console renders registered domain components automatically.

`ContentModel` declares one SDK-wide field, `metadata: dict[str, Any] | None = None` (GH-63), on the base class itself — every registered card, FROZEN or domain, inherits it and emits it on the wire when set. It is an out-of-band disclosure envelope, not a per-type Profile field, so it does not appear in any of the per-type frozen field lists above; see the `agent_sdk/models/content_types.py` module docstring for the full rationale and its current gap against the a2ui-advisor's frozen tables. Because the field is declared once on the base class, all three rules about it are enforced once on the base class too — a domain card gets them for free and cannot silently opt out: `wire()` emits it when set; **`to_plain_text()` appends it as a trailing `key=value` suffix** (each key and value routed through `common.redact.sanitize_text`, the assembled suffix bounded), which is why `to_plain_text()` is concrete and `_body_text()` is the hook subclasses implement; and a `field_validator` rejects non-finite floats anywhere inside it, so the A2UI DataPart's JSON `null` and the mandatory TextPart's `inf` can never disagree about the same value. The console renders it too — `paintSurface` appends one dimmed footnote row per surface (`agent_sdk/console/static/a2ui.js`), the visual counterpart of the text suffix, so a domain card needs no renderer work to make its disclosure annotation visible.

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
- `AgentSkill` entries carry only spec fields (`id, name, description, tags, examples?, inputModes?, outputModes?, security?`). SDK extras — `inputSchema`, tier, emits — live under the `x-sdk` namespace, never bare. The card does **not** repeat each tool's `outputSchema`; MCP `tools/list` is the one place that carries it (GH-219, ruling https://github.com/wailuen/a2a-sdk/issues/219#issuecomment-6345507008).
- `capabilities.extensions[]` lists **only URIs with a real negotiation path**: the A2UI extension URI `https://a2ui.org/a2a-extension/a2ui/v0.9.1` (exact string; activated via `X-A2A-Extensions` echo). The previous "enhanced-content-types" pseudo-extension is dropped; content-type metadata rides in `x-sdk` fields.
- `capabilities.pushNotifications: false`, `capabilities.streaming: true`.
- AG-UI surface advertised via the top-level `x-agui` block (deliberate choice over a `urn:agui:run:v1` extension; AG-UI has no normative card form): `{transport, endpoint, customEvents: [...]}` — `endpoint` is absolute, derived from the same resolved base URL as `url` (so the dev localhost fallback applies here too; it is never null or malformed).
- A2UI catalogs advertised under the A2UI extension params: `supportedCatalogIds` is built from the catalogs of the registered tools' `emits` types, after the `a2ui_allowed_components` filter. The Standard Profile (`urn:a2ui-profile:standard:v1`) is listed first only when some tool emits a Profile type; a registered domain catalog no tool emits is not advertised; an agent with no emitting tools advertises `[]` (the A2UI extension entry is still present). Ruling (GH-188): https://github.com/wailuen/a2a-sdk/issues/188#issuecomment-6229361485.
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

`MessageSendParams.configuration` is a typed **`MessageSendConfiguration`** model (`acceptedOutputModes?, historyLength?, pushNotificationConfig?, blocking?`) — never a raw dict. The SDK honors `acceptedOutputModes` and `historyLength`; `pushNotificationConfig` present → `-32003 PushNotificationNotSupported` (capability is false); `blocking: true` waits until the task is terminal or `input-required`, capped at `min(task deadline, AGENT_SDK_BLOCKING_SEND_MAX)`, and returns the current Task at the cap (A2A v0.3.0 §7.1.1).

**Task identity binding (security):** every task records its creating identity (`kind` + id, §6). `GET`, `:subscribe`, `:cancel`, and resume require the same identity (admin `api_key` identities may override); mismatch → 404 + `-32001` — existence is not leaked. Without this, anyone who learns a taskId from a log or trace could read it or, worse, confirm another identity's pending action_gate proposal.

The admin override does **not** reach one step further back: `TaskStore.context_messages()` (§5.2) — the mechanism behind `contextId` continuation — is identity-scoped with no exception for an admin `api_key` identity (RT-004). There is no ownership check on a bare `contextId` itself, only on an existing `taskId` (the binding above), but that no longer matters here: an admin who starts a **new** task (`message/send`/`:stream` with no `taskId`) on another identity's `contextId` inherits nothing — the new task simply starts with no prior history, exactly as it would on a `contextId` no task has ever used. An earlier revision of this section special-cased an admin `api_key` identity to bypass the filter here too, framed as "operator task inspection"; that framing undersold what the bypass actually did — it fed a foreign identity's transcript straight into the admin's *own new task* and from there into the upstream model's context, not a read-only view of the foreign task. That was a wave's own redteam self-ratifying new cross-identity data-exposure policy, never put to the user — removed rather than mitigated. Genuine operator inspection of another identity's task remains available, safely, as a read that never seeds a new task's model context: `GET /v1/tasks/{id}` (the admin override on the binding above).

**Interrupt / resume flow** (required by `contrib.action_gate` and spec lifecycle): `input-required` and `auth-required` are non-terminal interrupt states; the stream MAY close `final: true` while the task is interrupted. A `message/send` (or `:stream`) whose `message.taskId` references an existing task: terminal state → error; `input-required`/`auth-required` → **resume that task** (same `contextId`, same identity, message handed to the paused worker via the task store's resume channel) — never create a new task. While interrupted, the per-task wall-clock deadline is **suspended** (§8) and the interrupted-task TTL (§5.2) governs expiry instead.

**Audit status frame (RT-005, §8.1's `Reusable`/`ReuseKind` mechanism):** every `$ref` substitution, `$raw:` override, and forced-passthrough decision (§8.1) emits an EXTRA `TaskStatusUpdateEvent` frame onto the stream — `{taskId, contextId, status: {state: <unchanged current state>, timestamp}, final: false, metadata: {audit: {code, tool_name, field_name, kind}}}` — never carrying `status.message` (RT-009: internal plumbing, not user-facing chat text; the frame's `status.state` is whatever the task's current state already was, re-serialized message-free rather than repeating a prior chat sentence). This is a real, additional wire-visible frame shape a strict consumer must expect and ignore (or read for audit purposes) alongside the ordinary status/artifact frames above — it is not merely "an internal `AuditEvent`" with no wire consequence. AG-UI's mapper emits no frame for this event at all (falls through its default no-frame case) — the audit trail is A2A-stream-only; AG-UI callers must read it from `logger.info`/stored state instead.

Complete A2A error code table (all seven; internal sentinel names match spec names):

| Code | Name | SDK trigger |
|---|---|---|
| -32001 | TaskNotFound | unknown/expired task id |
| -32002 | TaskNotCancelable | cancel on terminal task |
| -32003 | PushNotificationNotSupported | any push-config request (capability false) |
| -32004 | UnsupportedOperation | terminal-task re-message (`message/send`, `message/stream`), any unimplemented method |
| -32005 | ContentTypeNotSupported | unacceptable `acceptedOutputModes` |
| -32006 | InvalidAgentResponse | internal translator failure |
| -32007 | AuthenticatedExtendedCardNotConfigured | extended-card request (not configured) |

An unmatched `/v1/*` route (unknown-route dispatch miss, not a task lookup) returns **HTTP 404 with the standard JSON-RPC `-32601`** (Method not found) — distinct from the `-32001 TaskNotFound` above, which known task routes emit for a missing/expired task id.

Wire-shape rules baked into `models/a2a.py`:

- Parts discriminate on `kind`, never `type`. `FilePart` = FileWithBytes XOR FileWithUri.
- Structured artifacts are dual-part: TextPart fallback + DataPart payload.
- **`TaskStatus` serializes to `{state, message?, timestamp?}` only** — internal fields (`note`, `error_category`, `source`, `usage`) are whitelist-stripped before the wire.
- Server-emitted `contextId` is always a non-empty UUID and present on every emitted `Task`/`Message`.
- Extension negotiation: `X-A2A-Extensions` request → response echoes the activated subset.
- `AgentError{category, message, source?, a2a_code?, detail?}` is the **internal** error model only — it is never emitted on the wire. Wire errors are the spec error shape (`{code, message, data?}` with the HTTP status mapping above), built from it; no input values, no credentials in either.

### 5.2 Task store

`TaskStore` interface; `InMemoryTaskStore` default (LRU 1000 / TTL 1h, per-subscriber bounded queues maxsize 256, sentinel close), plus the resume channel for interrupted tasks (§5.1). Tasks carry their creating identity (§5.1 binding). Process-local — see the §2 deployment invariant.

**In-place mutation + durability hooks (C-005, RT-005/RT-B-003):** callers that already hold a `TaskRecord` — `run_loop`, `set_task_status`, `agent/runner.py`'s out-of-loop repair helper `repair_dangling_tool_use`, and `routes/a2a.py`'s `tasks_cancel` — mutate its fields (`task.status`, `messages`, `pending_tool_results`) directly on that object rather than through a setter. `InMemoryTaskStore.get()` returns the live record by reference, so the mutation IS the write; a durable subclass whose `get()` deserializes a fresh copy per call must instead override two non-abstract, default-no-op hooks that flush the mutated fields back to storage keyed by `record.task.id`: `persist_messages(record)` for `messages`, and `persist_status(record)` for `task.status`. **Both must be overridden together** — a durable store that overrides only `persist_messages` never learns a `CANCELED` transition, so `context_messages()`'s `TERMINAL_STATES` filter never selects the task and the transcript `persist_messages` just flushed is never read back as a continuation candidate. Flush order is fixed and fail-unsafe: `persist_messages` runs first, and `persist_status` only after it returns without raising — publishing a terminal status ahead of the transcript flush it depends on would leave a durably terminal task whose stored transcript is still the unrepaired dangling-`toolUse` tail. `TaskRecord.pending_tool_results` is a runtime-only field (never serialized, like `worker`/`resume_future`) holding `toolResult` blocks already built for the turn currently in flight, kept outside `messages` so a mid-turn exit (a `DeferredEvent` handoff, a cancellation, or a raise unwinding the generator frame) can't discard results that already completed; `run_loop` clears it at each turn boundary and `repair_dangling_tool_use` once it has consumed it. Both hooks default to a no-op — mirroring the `interrupt_ttl_remaining` precedent (0.5.40, §4.0) — so a pre-existing external `TaskStore` subclass keeps instantiating unmodified, silently losing durability for these fields until it adds the overrides.

**RT-B-104/RT-B-205 — `INTERRUPT_STATES` flushes `persist_messages` too, and it is a MID-TURN snapshot:** `set_task_status` flushes `persist_messages` under the same fail-closed ordering not only on `TERMINAL_STATES` but also on `INTERRUPT_STATES` (AUTH_REQUIRED/INPUT_REQUIRED) — status alone is not a coherent resume-after-restart record without the matching transcript. But an interrupt is always raised from INSIDE the per-tool-call loop, after that turn's assistant `toolUse` fold and before its matching `toolResult` fold, so `record.messages` at that instant is **guaranteed** to end on a dangling `toolUse` with no matching `toolResult` — the exact shape `repair_dangling_tool_use` (C-018) exists to close, which nothing calls on this path. This flush is therefore NOT Converse-replayable as-is: a durable subclass whose own resume-after-restart mechanism reads it back must run an equivalent repair before handing the transcript to a model. Unaffected: the SDK's own in-memory resume, since `context_messages()` selects continuation candidates only from `TERMINAL_STATES` and in-process resume reads the live `resume_future` directly, never this flushed copy. See `TaskStore.persist_messages`'s docstring (store.py) for the full rationale and docs/deployment.md for the implementer-facing summary.

**`TaskRecord.date_line` durability (GH-154):** the worker sets `record.date_line` once, on a task's first turn, and reuses it on every resumed turn so the task keeps its original date. `InMemoryTaskStore` keeps it by reference. A durable `TaskStore` subclass should save and restore it alongside `messages` (e.g. inside `persist_messages`); if it does not, a task resumed after a restart recomputes the date from the clock, which is safe but may differ from the original day. Default `None` keeps existing subclasses working unmodified.

**RT-007 default gating on `persist_status` (`TaskStore.persist_every_status` class attribute, `agent_sdk/tasks/store.py` — cited by name, not line: pinned line numbers rot as the module grows, per C-017's registry note):** `set_task_status` is the single choke point for every in-place `record.task.status` mutation, including WORKING — reapplied once per streamed `TextEvent`/`ProgressEvent`/`NoteEvent`/`ToolProgressEvent` chunk within a turn. A synchronous `persist_status` hook doing a durable write on every one of those blocks the event loop far more often than durability actually requires, so by default `set_task_status` calls `persist_status` only when the new `record.task.status.state` is in `TERMINAL_STATES` (COMPLETED/CANCELED/FAILED/REJECTED) or `INTERRUPT_STATES` (AUTH_REQUIRED/INPUT_REQUIRED — an interrupted task must survive a restart to be resumed) — **not** on WORKING transitions. A durable subclass that wants the pre-RT-007 every-transition granularity (e.g. to drive a live status dashboard) sets the class attribute `persist_every_status = True`, rather than re-deriving `record.task.status.state` itself. Author a durable `TaskStore` subclass against this default — expecting `persist_status` on every mutation without checking for the opt-in silently drops WORKING-state durability.

**`MAX_CONTEXT_MESSAGES` (`InMemoryTaskStore`, `agent_sdk/tasks/memory.py`) is coupled to `LoopPolicies.max_turns` (`AGENT_SDK_MAX_TURNS`), not independent of it.** A single task that never finishes folds `2 * max_turns + 2` messages (a `toolUse`/`toolResult` pair per turn, plus the seed and the `bridge_trailing_user` close) with its only plain user-authored turn boundary at index 0 — the seed message. `context_messages()` truncates a longer-than-cap transcript at the newest such boundary (`_turn_boundary_slice`), so once `2 * max_turns + 2` exceeds the default cap of 50 (`max_turns` above ~24), the trailing cap-sized window contains no boundary at all. Rather than dropping the whole prior transcript in that case, the slice search widens backward past the cap for the nearest earlier boundary and logs a `WARNING` — bounded safely because a single task's own message list is already finite (governed by that task's `max_turns`), unlike the cross-task growth `MAX_CONTEXT_MESSAGES` itself guards against. An operator raising `AGENT_SDK_MAX_TURNS` well above the default, or a durable subclass lowering `MAX_CONTEXT_MESSAGES`, should expect that warning to fire routinely and treat it as a signal to raise the cap (or the subclass's override) to keep continuation replay close to the nominal `MAX_CONTEXT_MESSAGES` size rather than relying on the fallback. See docs/deployment.md.

Lifecycle rules the implementation must honor:

- **Interrupted tasks** get their own TTL (`AGENT_SDK_INTERRUPT_TTL`, default 30 min — a confirmation window, distinct from the general 1h task TTL) and are excluded from LRU pressure-eviction while waiting — bounded by `AGENT_SDK_MAX_INTERRUPTED` (default 100): at the cap, a new interrupt becomes a typed task failure instead of pinning another worker (each interrupted task holds a paused coroutine; without the cap an interrupt flood bypasses the LRU bound). On interrupt-TTL expiry or any eviction, the store **cancels the paused worker coroutine, closes the resume channel, and sentinel-closes all subscriber queues** — nothing leaks; a later resume gets 404 + -32001.
- **Subscriber queue overflow** (slow consumer hits maxsize 256): that subscriber's stream is terminated without a `final` frame — never silent frame-dropping, which could swallow `final: true` and hang the consumer forever. Termination engages the documented re-subscribe path.

Documented consumer contract: a stream severed without a `final` frame → re-`:subscribe` (A2A HTTP+JSON binding §5.3); 404 → task expired (restart, TTL, or confirmation window elapsed).

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

**History processing (not rejection):** truncate to most-recent 50 messages (oldest dropped); messages over `AGENT_SDK_AGUI_MAX_MESSAGE_CHARS` (default 32000, minimum 1000) keep their start and end with a `[... N chars omitted ...]` marker in the middle (marker counted within the limit; control characters stripped first) and a logged warning (GH-168); blank assistant turns silently skipped during the Bedrock fold. `RUN_ERROR` is reserved for agent-side failures, not large-but-valid client history.

**CUSTOM events — frozen payload contracts** (consumers read exactly these):

| name | value shape |
|---|---|
| `AGENT_ARTIFACT` | `{dataType, toolName, data}` |
| `A2UI_UPDATE` | `{messages: [<a2ui message>, …]}` (translator list wrapped under `messages`) |
| `AGENT_PROGRESS` | `{message: str}` |
| `AGENT_NOTE` | `{note: str}` |
| `TOOL_PROGRESS` | `{message: str, toolName: str}` |

The card's `x-agui.customEvents` list and the console's routing table are asserted equal by a unit test; adding a name to one side without the other fails the build. **`AuditEvent` (RT-005, §8.1) is deliberately absent from this table** — internal `ReuseKind` substitution/override/forced-passthrough plumbing (RT-009: never user-facing) has no AG-UI wire representation at all; A2A gets the extra audit `TaskStatusUpdateEvent` frame documented in §5.1, AG-UI does not.

**Interrupts (action_gate path):** `RUN_FINISHED` with `outcome={type:"interrupt", interrupts:[{id, reason, message, responseSchema, toolCallId, expiresAt}]}` (camelCase, consistent with the rest of the AG-UI wire) — `toolCallId` links the interrupt to the pending tool call (action_gate requires it; the spec field is optional); `expiresAt` is an ISO-8601 UTC string (e.g. `"2026-04-20T17:00:00Z"`), matching upstream ag-ui-protocol's `Interrupt.expires_at: Optional[str]` — never epoch-ms; resume via new `RunAgentInput` with `resume=[{interrupt_id, status, payload}]`. The §5.1 identity binding applies to this path identically: an AG-UI resume must come from the identity that started the interrupted run. Custom events are not used for interrupts.

### 5.4 A2UI v0.9.1

- **Catalog negotiation (GH-240):** over A2A a Standard Profile card is sent only when the client's advertised catalogs (first list of `catalogs`, `v0.9.supportedCatalogIds`, `supportedCatalogIds`) contain `CATALOG_ID`; otherwise the artifact carries the TextPart plus a plain model-dump DataPart (no A2UI mimeType). No catalogs key keeps today's behaviour. AG-UI CUSTOM is unchanged. Ruling: https://github.com/wailuen/a2a-sdk/issues/240#issuecomment-6379597173
- **Delivery:** over A2A — DataPart artifacts, `metadata.mimeType = "application/a2ui+json"` (the legacy `application/json+a2ui` is accepted inbound, never emitted); over AG-UI — `A2UI_UPDATE` CUSTOM events (§5.3 shape). One translator feeds both.
- **A2A wire shape — object-wrapped, not a bare array (GH-128):** `DataPart.data` for an A2UI DataPart is the JSON object `{"messages": [<a2ui message>, …]}`, never a bare array — matching the AG-UI CUSTOM event's `value.messages` convention exactly (same key, same shape). `agent_sdk/models/a2a.py`'s `DataPart.data` is typed `dict[str, Any]` (not `dict[str, Any] | list[Any]`), so a bare-array `data` fails at construction; every released version through v0.5.42 emitted a bare list here, which was already non-conformant to the A2A base spec. This is a genuine, unresolved conflict between two pinned specs, not a clear-cut fix: A2A v0.3.0's `DataPart.data` typing (`{[key: string]: any}`, `types.ts`, pinned tag) requires an object, which the wrapper satisfies — but A2UI v0.9.1's own A2A binding (`a2ui_extension_specification.md`, "Data encoding") independently says `data` MUST be a bare array of messages and shows no `messages` wrapper in its example. The `"messages"` key is this SDK's own invented resolution, not a citable canonical shape on either side. **Residual interop cost:** a strictly spec-conformant third-party A2UI Path-A renderer — built from the A2UI spec alone, with no knowledge of this SDK — looks for the message array at `data` and will not find it at `data.messages`, so it renders nothing for every A2UI artifact this SDK delivers over A2A; this SDK's own console/testing clients (`agent_sdk/console/static/chat.js`'s `handleA2aArtifact()`, `agent_sdk/testing/chat.py`'s `extract_a2ui()`) unwrap `data.messages` and are unaffected. This particular residual cost — a third-party renderer finding nothing at `data.messages` — is scoped to the PRODUCER direction (this SDK's own emission). The `DataPart.data` **type** narrowing that enforces the object shape (`dict[str, Any]`, `agent_sdk/models/a2a.py`) is NOT producer-only, however: it is symmetric, also tightening INBOUND parsing so that a spec-conformant A2UI v0.9.1 client's bare-array action `DataPart` on `message:send` is rejected with `-32602` (Invalid Params) rather than coerced — pinned by `tests/test_protocol_wire.py::test_inbound_data_part_bare_array_rejected_as_invalid_params` and flagged in the future-work note at `agent_sdk/models/a2a.py:71`. That inbound rejection is latent today (GH-159: `routes/a2a.py` accepts text input only and rejects any non-`TextPart` with `-32005`/HTTP 415 after model validation, so even a well-formed object `DataPart` is refused rather than dropped; inbound A2UI actions are a separate future feature), but it is a genuine consumer/server-direction cost, so the narrowing's impact is stated in BOTH directions. RT-002 (w038 group G): both first-party consumers additionally accept a bare-array `data` on read (`Array.isArray(part.data) ? part.data : …` / `isinstance(data, list)` before the dict-unwrap branch), so they can also consume a strictly spec-conformant third-party A2UI producer's bare-array DataPart, matching the tolerant-consumer pattern `harness/agents/a2ui-advisor.md` itself prescribes to downstream agents (`Array.isArray(raw) ? raw : Array.isArray(raw?.messages) ? raw.messages : []`). Tightening this SDK's own emission to satisfy the A2A base spec does not require narrowing what this SDK's own consumers can read — the consumer accepts both shapes losslessly. The AG-UI `A2UI_UPDATE` path carries no equivalent conflict — A2UI defines no normative AG-UI binding, so this SDK's `value.messages` shape is not a deviation from anything. See LRN-134 for the full citation trail; a non-normative agent-card hint for this wrapper is implemented, (the former `deleteSurfaceSemantics` hint was removed by GH-214): `agent_sdk/a2ui/catalog.py::a2ui_extension()` advertises `params.dataEncoding: "data.messages"`, giving a strictly spec-conformant third-party renderer a wire-discoverable way to find the message array without reverse-engineering it.
- **Sequence per artifact — three-message open sequence, ONE delivered array, client-managed lifetime (GH-214):** `translate()` (`agent_sdk/a2ui/translator.py`) computes `createSurface` → `updateComponents` → `updateDataModel` as one `list[dict]`, and delivery callers (`agent/runner.py::build_artifact`, `routes/ag_ui.py`'s `ArtifactEvent` branch) pass it through `validate_a2ui_delivery()` and deliver it as ONE array: one A2A DataPart (artifact = `[TextPart, DataPart(open)]`) or one AG-UI `A2UI_UPDATE` CUSTOM event (after `AGENT_ARTIFACT`). The SDK emits NO `deleteSurface` for a surface in the artifact or run that created it, on either transport: a spec renderer folds the array, paints, and would otherwise unmount the card straight away. Surface lifetime is managed by the client; each artifact has a fresh `surfaceId` (a caller-supplied `surface_id` must be unique per artifact). A replayed `createSurface` for a held surface is a no-op (`tasks/get` returns the same artifact), so replay is safe. Ruling: https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762. This is a stable-core wire change (§4.0), recorded under Breaking changes in CHANGELOG.md. `validate_a2ui_delivery()` still rejects a `translate()` output with no open messages. The first `updateComponents` for a surface establishes exactly one component with `id: "root"` (spec MUST — a conforming client buffers forever otherwise). Every message carries `version`. The card's A2UI extension (`a2ui_extension()`, §4.5) advertises `supportedCatalogIds`/`acceptsInlineCatalogs`/`dataEncoding`; the former SDK-private `deleteSurfaceSemantics` param (GH-113) was removed with the close message.
- **Catalog ids:** Standard Profile surfaces always emit `catalogId: "urn:a2ui-profile:standard:v1"`. Domain components get **their own surface** with the domain `catalogId` — surfaceId+catalogId are immutable once set; the two catalogs never share a surface.
- **Capability extraction (transport-specific, resolved by the route, never by tools/translators):** A2A → `message.metadata.a2uiClientCapabilities`, gated on the `X-A2A-Extensions` opt-in header carrying the A2UI extension URI; AG-UI → `forwardedProps.a2uiClientCapabilities`. **The route-level default is fail-closed:** no opt-in signal at all (A2A: `X-A2A-Extensions` absent or missing the A2UI URI; AG-UI: no `forwardedProps`, or `forwardedProps` missing the `a2uiClientCapabilities` key) → `A2uiCapabilities(tier="none", catalogs=[])`, suppressing every A2UI emission (DataPart artifacts and `A2UI_UPDATE` CUSTOM events alike) for that request. This is *not* the same default as `A2uiCapabilities.from_metadata()`'s own `tier="core"`, `catalogs=[standard]` fallback — `from_metadata()` only defaults an already-scoped capability *payload* for a caller that has already established the client is A2UI-aware (e.g. parsing a stored/forwarded claim dict); it is never invoked on the raw absence of any opt-in signal at the network boundary, where fail-open would mean every A2UI-naive client starts silently receiving A2UI frames it never asked for. See LRN-046 (the opt-in gate this default enforces) and LRN-115 (do not "align" this route default to `tier="core"` — that change reintroduces the exact violation LRN-046 exists to prevent).
- **Tier gating:** Extended types emitted only on `tier="core+extended"`. The full Extended gate set: `waterfall_chart, multi_category_chart, fund_performance, email_list, calendar_events, user_profile, user_list, document_list`. (m365 currently doesn't gate its three — SDK corrects this.)
- **Domain gating:** a domain component is emitted only when the client's `a2uiClientCapabilities.catalogs` (or, when `catalogs` is absent or not a non-empty list, upstream A2UI v0.9.1's `{"v0.9": {"supportedCatalogIds": [...]}}` per client_capabilities.json, then a flat root `supportedCatalogIds` as lenient fallback; `catalogs` wins, GH-213; on A2A a present `catalogs` list, even an empty one, is final, GH-240) includes that domain `catalog_id`. Tier alone never unlocks domain types.
- Fallback: when a type is gated off, the artifact still ships its TextPart (`to_plain_text()`); nothing is silently dropped.

### 5.5 MCP (2025-06-18) + OAuth 2.1

**Streamable HTTP at `/mcp` — three verbs:**

- `POST /mcp` — JSON-RPC; a request is answered with `application/json` regardless of `Accept` header (MCP 2025-06-18 §3.2 permits a JSON response to SSE-accepting clients — SSE is reserved for `GET /mcp` streaming only). A notification, or a POSTed JSON-RPC *response* (`id` plus `result`/`error`, no `method`), gets `202 Accepted` with an empty body, after the same auth, origin and session checks (GH-221). `tools/call` for an unknown or Tier 2 tool returns `-32602` (invalid params) with the fixed message `tool not found`, never echoing the name (GH-221; reverses wave-10 L-1). Session id allocated on `initialize`, returned via `Mcp-Session-Id` header; unknown/expired session → 404 (except `initialize` itself, the recovery path). **Session sharing (GH-201, reverses RTGA-010 evict-all and the `Mcp-Session-Id required` 400):** the identity key has no user part for a shared API key or org-wide OAuth client, so several clients can sit on one identity. A successful `initialize` therefore evicts only the session it replaces (the presented `Mcp-Session-Id`, if live and owned by the caller; a foreign id is never evicted), an identity holds at most `AGENT_SDK_MAX_MCP_SESSIONS_PER_IDENTITY` live sessions (default `_MAX_SESSIONS_PER_IDENTITY = 200`, clamped to `_MAX_SESSIONS`; least-recently-used evicted beyond that, never another identity's). The default is sized like the stream cap because under an org-wide OAuth client or shared API key it is a per-org cap; an org with more concurrent connectors raises the setting, and a non-initialize request with no `Mcp-Session-Id` is dispatched normally. The global `_MAX_SESSIONS` LRU and idle TTL are unchanged. Ruling: https://github.com/wailuen/a2a-sdk/issues/201#issuecomment-6234642337 (cap made a setting: issuecomment-6235185280).
- `GET /mcp` — server→client SSE channel: returns `text/event-stream` with heartbeats (returning 405 breaks Claude.ai Desktop — LRN-053), **or 429 + `Retry-After` when the concurrent-stream budget is exhausted** (see the stream-admission bullet below). A present `Mcp-Session-Id` gets the same checks as `POST /mcp` (GH-221): longer than 64 chars → 400; unknown, expired or other-owner session → 404 (identical static body, the id is never echoed). No header → 200 SSE as before.
- `DELETE /mcp` — session termination: honors `Mcp-Session-Id`, idempotent, 204.
- **Stream admission cap — a documented spec deviation (GH-143 + RT-001/RT-002; `tests/test_gh143_mcp_get_stream_cap.py`, `tests/test_rt001_mcp_sse_stream_cap.py`, `tests/test_rt002_a2a_stream_admission_cap.py`, `tests/test_rt001_admission_before_mutation.py`).** Every authenticated, indefinitely-held `text/event-stream` is admitted against a bounded budget before its `StreamingResponse` is created; at capacity the server **rejects with 429 + `Retry-After: 5`** rather than evicting an existing stream (evicting the bookkeeping entry would not stop the live generator or free its connection, and on the legacy SSE path evict-oldest additionally let one caller make another tenant's live session unroutable). Two budgets, each enforced global-first then per-identity: MCP's `GET /mcp` + `GET /mcp/sse` share one (`_MAX_GET_STREAMS`, `AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY`); A2A's `POST /v1/message:stream`, `POST /v1/tasks/{id}:subscribe` and AG-UI's `POST /ag-ui/run` share the other (`_MAX_A2A_STREAMS`, `AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY`, plus a per-task subscriber cap that bounds `record.subscriptions`, the list `store.publish` walks per frame). A budget is shared across transports because capping one is otherwise bypassed by calling the other. **Deviation:** `harness/reference/mcp-protocol.md` §"GET (optional SSE)" specifies exactly two outcomes for `GET /mcp` — `text/event-stream` or 405; 429 is a third. It is deliberate (the server is single-process by design, §2, so unbounded streams degrade every tenant) and load-shedding only — never returned on a first connection under normal load. **Operational note:** `harness/reference/mcp-claude-platforms.md` records a 429 on the MCP path as a known Claude.ai *"Couldn't connect"* failure mode, so the per-identity default is sized in the low hundreds (org-wide OAuth client provisioning collapses a whole org onto one identity key — §4.4) and is operator-raisable without a code change. Ordering rule (RT-001), scoped to the load-shed path: stream admission runs **before any durable state mutation** on the request path, so a 429 never leaves an orphan `TaskRecord` behind. That rule is about the *shed* path only — it is not, and never was, a general guarantee that live streams are safe from eviction. The general guarantee is owned one layer down, by the task store: `_evict_over_capacity`, `get()`, and `sweep()` all skip records with live subscribers exactly as they skip `interrupted` ones (RT-001 round 5 for capacity overflow, `tests/test_rt001_r5_eviction_never_severs_live_streams.py`; round 6 for TTL/interrupt-deadline expiry and the background sweeper, `tests/test_rt001_r6_expiry_never_severs_live_streams.py`). It has to live there, because neither overflow nor expiry eviction is driven by anything about the record's own owner — the caller who overflows the store, or whose unrelated `find_interrupt()` resume lookup walks past an expired record, is essentially never that record's owner, and uncapped-by-design routes like `POST /v1/message:send` reach `create()` too. Route-layer admission bounds how many streams exist; it cannot bound which record overflow or expiry picks.
- **Agent instructions (GH-157).** `initialize.instructions` = credential-forwarding note, then the agent text, joined by a blank line; the key is omitted when both are empty. Agent text comes from `Agent(mcp_instructions=...)` (persona agents) or the optional `mcp_instructions` artifact (rendered once in `build_app` with the `system` variables, StrictUndefined), stripped, stored on `app.state.mcp_instructions`. Both set, over 4000 characters, or an undefined variable is a build error. No env setting (ruling). It is shown to every MCP client model: no secrets. Build fails (field name only) if the rendered text contains the value of any `SecretStr` on settings or in `artifact_vars` (SI-6 guard; credential-store values are not checked, so keep them out of artifact vars). `tests/test_gh157_mcp_instructions.py`.
- `MCP-Protocol-Version` header validation is **transport-split** (GH-77 — this is not one blanket rule). Per spec §10: the client MUST send the header on every non-`initialize` request, and the server MUST reject a present-but-unrecognized version with 400 — both hold uniformly across every path below. The paths diverge only on the ABSENT-header case, where §10 merely SHOULDs that the server assume 2025-03-26 for clients that predate the header. **Streamable HTTP** (`POST /mcp`, non-`initialize`) — GH-200 reverses GH-77's absent→400 (Copilot Studio omits the header on `tools/list` after a successful `initialize`): absent → dispatched; the response `MCP-Protocol-Version` header carries the `protocolVersion` negotiated at `initialize` and recorded against the `Mcp-Session-Id` (session record is `(last_seen, owner, version)`), else `2025-03-26` when the caller has no session. `_dispatch()` is version-agnostic, so this version sets only the response header; `tools/list`/`tools/call` output does not change with it. Session checks (404 unknown/expired/foreign) run first; a missing `Mcp-Session-Id` is not an error (GH-201). Present-but-unrecognized → 400 "unsupported MCP-Protocol-Version" (§10 MUST); only values in `SUPPORTED_PROTOCOL_VERSIONS` are ever echoed. Ruling: https://github.com/wailuen/a2a-sdk/issues/200#issuecomment-6234026443. `GET`/`DELETE /mcp` — absent → allowed (no negotiation context to validate against), present-but-unrecognized → 400 (GH-111, mirrors the POST check). **Legacy SSE** (`POST /mcp/messages`) — absent → allowed, assume 2025-03-26 per §10's SHOULD-assume carve-out for older clients that predate the header. This "assume" is a *rationale*, not a threaded value: `_dispatch()` is version-agnostic, so no 2025-03-26 value is materialized anywhere in the request path — admission simply treats the caller as pre-header. present-but-unrecognized → 400 (§10 MUST). version-future fields gated on the negotiated version.

Legacy SSE pair (`GET /mcp/sse` + `POST /mcp/messages?session_id=`) retained for older clients.

**Methods:** `initialize` — echo the client's `protocolVersion` if we support it; otherwise return our highest supported version and let the client decide whether to continue. `ping`; `tools/list` — Tier 1 only, each tool with `inputSchema` **and `outputSchema`** (derived from the `emits` model — `structuredContent` is never emitted unclaimed); `tools/call` — validate → execute → result with `structuredContent` + serialized `text` block; tool failures are `isError: true` results, never JSON-RPC errors. Capabilities declare `listChanged: false` (no notifications we don't send). `notifications/*` acknowledged with 202, never answered. Per MCP 2025-06-18, `outputSchema` and `structuredContent` are always JSON objects, never a bare string/scalar — this forces one exception to §4.3's `MarketBriefing` markdown-string contract: on the MCP surface only, its `outputSchema` is `{"type": "object", "properties": {"markdown": {"type": "string"}}, "required": ["markdown"]}` and its `structuredContent` is `{"markdown": <str>}` (GH-105); the `text` block still carries the raw markdown, and the AG-UI/A2A bare-string wire contract (§4.3, §5.4) is unaffected. **Void-result parity deviation (documented — GH-115 / w033, RT-001/RT-002; signed off REVIEWS.md Round 5; `tests/test_rt002_mcp_empty_result.py`):** a Tier-1 tool that declares `emits` — so `tools/list` advertises its `outputSchema` — but returns/yields no terminal value (`None`) folds to `isError: false` with an empty `text` block and **no** `structuredContent`. This is a deliberate, parity-motivated deviation from MCP 2025-06-18 §4's "advertised `outputSchema` MUST return conforming `structuredContent`": `loop.py`'s `fold_result_content(None)` folds the identical void result to a **success** `toolResult` on the A2A/AG-UI surfaces, and §5.6 requires a Tier-1 tool to reach the same success/failure verdict on every surface — so the same void call must not succeed over A2A/AG-UI yet fail over MCP. The deviation is scoped **strictly to the emits-declared void case**: a `None`-returning tool with **no** `emits` advertises no `outputSchema`, so its empty-`structuredContent` result is not a §4 deviation at all (§4 requires `structuredContent` only when the tool advertises output to describe). This is **not** a "None is always fine" blanket carve-out — it is the single narrow case where an advertised schema meets an absent value. Mirrored in `routes/mcp.py`'s module docstring. (Prior drafts mis-cited this as GH-113/LRN-118 — GH-113 was the `deleteSurfaceSemantics` wire-hint (since removed, GH-214) and LRN-118 is the version-header staleness rule; neither documents this ruling.)

**Skills over MCP (GH-205, opt-in `Agent(mcp_skills=None | "tool" | "prompts")`, default `None` = byte-identical `initialize` and `tools/list`).** `"tool"` lists the built-in `load_skill` on `tools/list` (tier-1 shape: `name`, `description` listing the catalog skills, `inputSchema` with a required `name` string, `annotations.readOnlyHint: true`) and serves it on `tools/call` (skill body as text; unknown or excluded name -> `isError: true`, fixed text). `"prompts"` advertises `capabilities.prompts: {"listChanged": false}`, serves paginated `prompts/list` (`name`, `description`) and `prompts/get` (one `user` message whose text is the skill body; unknown or excluded name -> `-32602`); without `"prompts"` these methods stay `-32601`. Both modes need `skills_dir` (boot error otherwise); `exclude_from_catalog` skills are never listed or fetchable; the requested name is never echoed or logged (SI-2). Same `require_identity` and session check as `tools/*` (SI-5). Ruling: https://github.com/wailuen/a2a-sdk/issues/205#issuecomment-6359827386.

**Tuple `emits` (GH-225).** `emits=(A, B)` declares a dispatcher tool that returns different content types (`ToolDecl.emits_types` is the normalized tuple). The `outputSchema` is `{"type": "object", "anyOf": [<each member schema without its $defs>], "$defs": {<merged>}}` (members whose `$defs` collide with different content fail at boot; title stripping stays the single GH-221 pass in `tools/list`). `structuredContent` is sent when the result is any member; raw-dict coercion tries members in declaration order and uses the first that validates, else `isError` with the fixed text. Ruling: https://github.com/wailuen/a2a-sdk/issues/225#issuecomment-6359382542.

**OAuth chain (Claude.ai connector compatible):**

- `/.well-known/oauth-protected-resource` **and the path-suffixed `/.well-known/oauth-protected-resource/mcp`** (Claude probes the suffixed form first). `resource` is the **absolute canonical URI** `{PUBLIC_URL}/mcp` — the same exact string used in `authorization_servers` checks, the `resource` parameter, and token audience.
- `/.well-known/oauth-authorization-server` (RFC 8414) — includes `code_challenge_methods_supported: ["S256"]` (load-bearing for Claude.ai's PKCE probe), `grant_types_supported`, `response_types_supported`, `token_endpoint_auth_methods_supported` (`none`, `client_secret_post`, `client_secret_basic` — GH-222: DCR may issue a client secret, stored as sha256 only; `/oauth/token` and unauthenticated `/oauth/revoke` enforce the method on the stored record; PKCE S256 stays mandatory; secrets are a compatibility measure, not a trust boundary — consent at `/authorize` is the gate).
- `POST /oauth/register` (RFC 7591, unauthenticated DCR — rate-limited per §6, registration cap with LRU eviction: admin-approved (`consented`) clients are never evicted; IdP user-consented clients (`user_consented_at`, a separate field that never grants the one-time-consent shortcut) are protected only while they hold a live refresh family; everything else is evictable oldest-first).
- `GET/POST /oauth/authorize` — consent gated on a real admin API key (header-borne; OAuth-kind tokens rejected here). **RFC 8707 `resource` parameter: accepted and validated at authorize (omitted → defaults to the canonical MCP URI), persisted into the auth code, carried from code metadata into minted tokens and through refresh rotation. It is NOT re-required as a parameter at the token request** — Claude.ai does not send it there; requiring it would break the live connector.
- `POST /oauth/token` — PKCE S256 exchange + single-use refresh rotation; `scope` omitted from the response when empty (never `"scope": ""`).
- `POST /oauth/revoke` (RFC 7009).
- 401 responses carry `WWW-Authenticate` pointing at the PRM (degrading header-less on malformed Host, never 503).

**Auth on `/mcp`:** API key or OAuth token; resolved identities are **`kind`-tagged** (`"api_key"` | `"oauth"`). **Token audience enforcement — explicit two-value equivalence:** the accepted audience set is exactly `{PUBLIC_URL origin, {PUBLIC_URL}/mcp}`; anything else → hard 401, never log-and-allow. (Deliberate, documented deviation from strict RFC 8707 single-URI matching: Claude.ai sends the bare origin as `resource` in some flows — pitchbook's live-connector behavior, kept. The real privilege boundary is kind-based surface assertion, below.) Surface assertions: `/admin/*`, `/oauth/authorize`, and key-management endpoints reject `kind="oauth"`; `/mcp` accepts both kinds; `/oauth/revoke` accepts oauth-kind callers **for their own tokens only** (self-revocation) and non-service API keys for any token (service keys are a silent no-op on tokens they do not own); `/oauth/token` is unauthenticated by design (public client + PKCE).

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

**IdP sign-in addendum (opt-in, GH-152 / ADR-003; `AGENT_SDK_OAUTH_IDP=oidc`, default `none` = everything above unchanged).** `/oauth/authorize` federates to an upstream OIDC IdP (Entra ID is the primary target) instead of asking for an admin API key; the SDK stays the authorization server, so DCR, PKCE S256, PRM, AS metadata, token, refresh and revoke are unchanged. Flow: `GET /oauth/authorize` validates the client request as today, stores it server-side under a single-use `state` (TTL 10 min, bounded, memory-only), sets the `__Host-agent_sdk_idp` browser-binding cookie and 302s to the IdP; `GET /oauth/idp/callback` pops the flow, exchanges the code (confidential client, PKCE), verifies the ID token (RS256 only, JWKS signature, `iss`, `aud`, `exp`, `nonce`, and `tid` for Entra), applies the optional required role/group claim, then renders a **consent page** (client name, `redirect_uri` host, signed-in user) because DCR is open and silent SSO would otherwise enable a confused-deputy code theft; `POST /oauth/idp/consent` (single-use ticket) mints the code. With sign-in on, admin-key consent at `/oauth/authorize` is disabled and `AGENT_SDK_OAUTH_ONE_TIME_CONSENT=true` is refused at boot. Membership lives in Entra only (enterprise application "Assignment required", app roles, groups); the SDK keeps no access list. Audience rules above are unchanged. The callback and consent routes are intentionally unauthenticated (state + cookie + ticket gated, per-IP rate limited), a documented SI-5 exception. `response_mode=query` puts `code` and `state` in the callback URL, so `build_app()` always installs a `uvicorn.access` filter that strips the query from `/oauth/` paths (GH-166, SI-2); proxy and ingress logs are outside the SDK. Setup steps: `/setup` skill; settings: ADR-003.

### 5.6 Surface parity rule

Tier 1 tools appear on A2A + MCP; Tier 2 on A2A only. Card, `tools/list`, and console all render from the single ToolRegistry.

`load_skill` is a built-in on both surfaces: the agent loop offers it whenever `skills_dir` holds skills, and `Agent(mcp_skills="tool")` lists it on MCP `tools/list` too (GH-205). It is not in the ToolRegistry and `load_skill` is a reserved tool name at boot whenever `skills_dir` is set. It is read-only and never listed in the agent card.

---

## 6. Auth and credentials

- **Persistence:** API keys (sha256-hashed), OAuth client registrations, and refresh tokens persist in **reserved namespaces of the encrypted SQLite store** — restarts never wipe Claude.ai connector registrations. Auth codes are memory-only (short-lived, single-process).
- **API keys:** bearer, sha256-hashed at rest, constant-time comparison, prefix-only display. **Last-key protection:** revoking the final admin key is refused (pitchbook LRN-049) — lockout is impossible by that path. Within one process, `ApiKeyStore` serialises `revoke()` and the `last_used` write behind one lock (they run in worker threads); the same race across replicas is out of scope (a later fix could use an ETag-conditional update on Azure).
- **Bootstrap (no TOFU race):** whenever the key store holds **zero keys** at startup, a single-use bootstrap token is generated in memory and printed to stdout; the first `POST /admin/api/keys` requires it (atomic consumption). It expires after 15 minutes (it lands in log aggregation — the TTL bounds that exposure); a restart regenerates it and invalidates the old one. There is no window where key-minting is open to the network. The zero-keys re-arm covers fresh deploys and wiped volumes; recovery from a *lost key plaintext* (hash still stored, so the store is never zero) is an out-of-band store wipe — which also destroys stored credentials and connector registrations, stated plainly in the ops docs. Every bootstrap-path request is loudly logged. (Replaces the references' open-until-first-key mode.)
- **Key-store I/O (GH-202):** key listing, count, revoke and `verify` run off the event loop (`asyncio.to_thread`), so a slow store (Azure Table is one HTTP round trip per read) cannot stall `/health` or other routes. `list_keys` and revoke's last-admin check use one `CredentialStore.list_items` call, not one `get` per key; `count` uses one names-only `list_fields` query (no decrypt). `verify` writes `last_used` only when the stored value is missing or more than 60 s old, so `last_used` is accurate to ~60 s. API keys stay uncached; revocation is immediate on every replica.
- **`CredentialStore` interface:** abstract `get`, `set`, `delete`, `list_fields`, `close`, plus non-abstract `list_items(namespace) -> dict[str, str]` (`{field: plaintext}`). The default is `{f: v for f in list_fields(ns) if (v := get(ns, f)) is not None}`, so third-party stores keep working. Azure Table does one partition query and decrypts in place (never touching its cache); SQLite does one `SELECT` under its lock. All store methods block; async callers use `asyncio.to_thread`.
- **Identity kinds:** every resolved identity carries `kind`; per-surface assertions per §5.5.
- **`Identity.user` (GH-152):** an optional trailing field, `None` unless the token was minted through IdP sign-in. Entra: `{tid}:{oid}`; generic OIDC: `sub`. `subject` still means the registration (client_id / key id). `binding` stays `(kind, subject)` when `user is None`, else `(kind, f"{subject}|{user}")`, so task isolation is per (client, person). `Identity.principal_key` keys the per-identity rate limiter and stream admission, so two people behind one DCR client get separate budgets. Email and username go to the display label only, never to an allow decision.
- **`__oauth_idp__` namespace (GH-152):** reserved credential-store namespace holding the IdP `client_secret` (set/unset in the admin Credentials card). Never `.env`, argv or logs; read per token exchange so rotation needs no restart. A missing secret does not fail boot: it logs a warning and `/oauth/authorize` fails closed with `temporarily_unavailable`.
- **Session cap and removal lag (GH-152):** with sign-in on the SDK requests no `offline_access` and keeps no IdP token. Each token family gets an absolute lifetime of `AGENT_SDK_OAUTH_IDP_SESSION_HOURS` (default 720, bounds 1-2160), copied through every rotation; after it, refresh returns `invalid_grant` and the client must sign in again. **A person removed in Entra keeps access until their family expires: worst case equals `SESSION_HOURS` (default 30 days).** Re-checking Entra at refresh is out of scope. **Operator revocation (GH-163):** `GET /admin/api/oauth/identities` lists signed-in users (no token values or hashes) and `DELETE /admin/api/oauth/identities/{user}` (URL-encoded `tid:oid`, admin-only, idempotent) revokes every refresh family for that user, so removal need not wait for `SESSION_HOURS`. Access tokens are per-process memory (GH-162): other workers honour a revoked user's access token until it expires (max 1 h); refresh is refused everywhere. Refresh families minted before sign-in was enabled carry no `user` and are refused at rotation.
- **API-key switch (GH-152):** `AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS=true` (only valid with `oidc`) rejects non-admin `api_key` identities on every route guarded by `require_identity`. **Admin keys stay accepted everywhere**, so a holder of the admin key can still call protocol routes without signing in.

  | API key rejected (401 + PRM `WWW-Authenticate`) | API key still accepted |
  |---|---|
  | `/v1/message:send`, `/v1/message:stream`, `/v1/tasks*`, `/v1/card` | `/admin/*` and `/admin/api/*` (`require_admin`) |
  | `/ag-ui/run` | key management and bootstrap |
  | `/mcp`, `/mcp/sse`, `/mcp/messages` | `POST /oauth/revoke` |
  | agent routes using `require_identity` | `/.well-known/*`, `/health`, `/oauth/register`, `/oauth/token` |
- **Rate limiting — three layers:** (1) per-identity sliding window after auth (default 100/min); (2) **per-IP windows on all unauthenticated paths** (auth failures, `/oauth/register`, `/oauth/token`, consent) so key brute-force and DCR flooding are throttled — client IP derived per the `AGENT_SDK_TRUSTED_PROXIES` rule (§4.4), never blind `X-Forwarded-For`, and the per-IP map is a bounded LRU (cardinality cap, no memory-exhaustion vector); (3) **concurrent-stream admission** on every indefinitely-held `text/event-stream` (`GET /mcp`, `GET /mcp/sse`, `POST /v1/message:stream`, `POST /v1/tasks/{id}:subscribe`, `POST /ag-ui/run`) — a *concurrency* budget, not a rate window: layers 1–2 bound request frequency and cannot bound how many connections one caller holds open on a single-process server. Global-first then per-identity, reject-never-evict, and checked **before any durable state mutation** on the request path; see §5.5's stream-admission bullet for the budgets, the spec deviation and the Claude.ai operational note. All three in-memory (single-process invariant, §2). 429 + Retry-After.
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

**Surface lifetime (GH-214):** the SDK emits no `deleteSurface` for a surface in the artifact or run that created it (§5.4), so a renderer never unmounts a card the SDK just delivered; the client owns surface lifetime and each artifact has a fresh `surfaceId` (a caller-supplied `surface_id` must be unique per artifact). A replayed `createSurface` for a held surface is a no-op (`tasks/get` returns the same artifact), so replay is safe. Ruling: https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762. The console renderer (`agent_sdk/console/static/a2ui.js`) keeps every surface mounted in the transcript, and still accepts a `deleteSurface` received from another producer: it closes the registry entry post-paint (further updates for that surfaceId are rejected) while the painted DOM persists. Over A2A the message array is delivered as `DataPart.data.messages`, not a bare `DataPart.data` array (§5.4, GH-128) — a deliberate SDK resolution of a conflict between A2A v0.3.0's object-typed `DataPart.data` and A2UI v0.9.1's own A2A binding; a strictly spec-conformant third-party renderer built from the A2UI spec alone will not find its array at `data` (LRN-134). The AG-UI `A2UI_UPDATE` path carries no such gap. The agent card hints `params.dataEncoding: "data.messages"` (`agent_sdk/a2ui/catalog.py::a2ui_extension()`), an SDK-private param, not defined by the A2UI spec.

Scope (explicit): the v1 renderer is display-only — two-way input binding and `action` dispatch are out of scope (no FROZEN Standard Profile type is interactive); they arrive with any future interactive type. `MarketBriefing` renders as inline prose — no card chrome (the one Profile type with a rendering rule); an unknown component type whose bound value is an object renders a generic card (title from the component name, scalar fields as a key/value table, arrays of objects as tables, a collapsed raw-JSON block); only an unknown type bound to a non-object value renders the artifact's TextPart fallback. Every list, table, bar chart and generic scalar-row table is capped at `MAX_ROWS` (100) rows through the shared `capRows`/`moreNote` helpers, with an "N more" note for the rest. The registry drops entries whose painted node is no longer attached to the document (`node.isConnected === false`) at the start of each `renderA2ui` call.

---

## 8. ModelClient seam

```python
class ModelClient(Protocol):
    async def converse(self, *, system, messages, tools, max_tokens) -> ModelResponse: ...
    # reserved (non-breaking to add): async def converse_stream(...)
```

v1: `BedrockModelClient` — boto3 Converse on a **dedicated bounded executor** (model calls never starve the default `to_thread` pool); credential chain (Bedrock API key → IAM static → default); ARN/region from config only.

Loop policies: max 20 turns; per-tool timeout Tier 1 = 130s / Tier 2 = 180s; **per-task wall-clock deadline (default 10 min) and token budget (default configurable), exceeded → typed failure event** (GH-155: the max-turns and token-budget exits first make one tools-disabled summary call so the user still gets an answer; the run still ends as that typed failure — see `LoopPolicies.final_summary`. `final_summary_max_tokens` (env `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS`) caps only that call's output; the call is always made, and a fixed notice is sent only if it fails or returns no usable text (maintainer ruling on GH-155). A cap exit costs at most one extra call, so spend can end above the budget by that one call (see `_summary_max_tokens`). The OpenAI client sends `max_completion_tokens = min(final cap, operator max_completion_tokens)` on the summary call, with no provider-specific widening (non-reasoning deployments such as gpt-4o reject values above 16,384), and sends `reasoning_effort` only if the operator configured it (`AGENT_SDK_OPENAI_REASONING_EFFORT`, `AGENT_SDK_OPENAI_MAX_COMPLETION_TOKENS`). Reasoning models count hidden reasoning against that cap, so on gpt-5/o-series raise `AGENT_SDK_FINAL_SUMMARY_MAX_TOKENS` or lower the reasoning effort if the summary comes back empty — a fixed warning is logged when it does) (cost-runaway guard the references lack). The deadline clock **suspends while the task sits in an interrupt state** (`input-required`/`auth-required`) and resumes on resume — otherwise every action_gate confirmation slower than 10 minutes would fail by default; the interrupted-task TTL (§5.2) owns that waiting period. The token budget is **cumulative across resume cycles** (it guards spend, which resumes don't reset). Per-call result cache (task-local); AgentError from a tool → tool result, never a crash.

### 8.1 `Reusable` / `ReuseKind` — cross-turn reference substitution (GH-148)

A tool marks a result citable in later turns by returning `Reusable(value=result, kind="entity_id", label="PT IMC Pelita Logistik")` instead of `result` directly — the model receives `.value` unchanged (same wire shape as a plain `return`), and the loop folds a `__resolved__` marker (`{kind, label, value}`) into that call's tool-result block in `messages`. This closes a live-tested failure mode: with nothing to reference a value it resolved earlier, the model would retype a different-but-real, WRONG id from memory — a silent data-correctness bug with no validation-layer signal, since the substituted id is itself a real one.

A tool opts an input field into the substitution/validation contract via `Annotated[<scalar>, ReuseKind("entity_id")]` on its `input_model` — **top-level scalar fields only**; a container field or a field on a nested model raises `TypeError` at `@tools.tool` registration time rather than shipping a silent no-op. Before invoking the tool, the loop:

- resolves the literal token `$ref:<kind>` (or `$ref:<kind>:<label>` to disambiguate more than one resolution of the same kind) to the matching value, recorded as an internal `AuditEvent` — never as a user-facing `NoteEvent`, and never carrying the resolved value or label (SI-2);
- rejects the call with a generic error when a raw value matches no `__resolved__` value of that kind while at least one resolution of that kind exists — the exact GH-148 substitution bug, now caught instead of silently executed;
- rejects an ambiguous call — a bare `$ref:<kind>` or raw value with MORE than one resolution of the kind on record — telling the caller to disambiguate via `$ref:<kind>:<label>`; **RT-D-001: this rejection text names the kind's own on-record LABELS** (tool-author-supplied display names, never a resolved value or the caller's own supplied label — SI-2 unaffected), since that is the only way the `$ref:<kind>:<label>` move it recommends is actually constructible on a transport whose transcript never replays the original marker back to the model (AG-UI — see the carriage note below). Live testing found this reject-forever with no reachable recovery on a real AG-UI thread before the fix;
- passes a raw value through unchanged when no resolution of that kind exists yet, or it already matches one that does.

Three escape hatches. The first two are per-field operator opt-ins (never advertised in the rejection text, so a model that hallucinated a wrong id gets no hint either exists); the third is a loop-wide policy that defaults OFF (RT-002 — a correctness gate must never default to fail-open):

- `ReuseKind("entity_id", strict=False)` — substitute-only: `$ref` still resolves, but a raw value is never checked against prior resolutions.
- `ReuseKind("entity_id", allow_raw_override=True)` — the per-call token `$raw:<value>` bypasses the mismatch check for that one call, passing `<value>` through as-is; still recorded as an auditable substitution (`via_raw_override=True`), just not name-checked against history.
- `LoopPolicies.reuse_forced_passthrough_limit` (RT-C-001, default **`0`** — reject-forever) — bounded liveness recovery for a field left at every default: without this, a model stuck retrying the exact same wrong-but-plausible raw value has no in-band recovery move at all and can only keep calling the resolver tool until `max_turns`. Set it to a positive integer to opt IN: after that many *consecutive* rejections of the *identical* `(tool, field, raw value)` triple, the next call passes the value through unchanged instead of rejecting again, recorded as `ReuseSubstitution(via_forced_passthrough=True)` and surfaced as a distinct `AuditEvent(code="reuse_forced_passthrough")` (never silent). Scoped to the exact raw value, not merely the field — a sequence of *different* hallucinated ids exhausts nothing and is rejected forever regardless of this setting; only a genuinely stuck retry of one identical value ever recovers. See `docs/tools.md`'s "Bounded recovery for a stuck raw value" for the full contract.

**Cross-request carriage reaches both transports, by two different routes (RT-A-004).** The mechanism has no store of its own — it rides `messages` — but `messages` itself only preserves tool-result blocks on A2A, so AG-UI needs a second path to the same data. Each new A2A task is seeded from `TaskStore.context_messages()` straight into `record.messages`, the prior task's `messages` verbatim, so a marker folded in turn N survives into turn N+1's fresh loop run as part of what the model itself sees. AG-UI's `_fold_history` collapses every resent message — including tool-result blocks — down to plain text, so `routes/ag_ui.py` cannot put a marker back into the model-visible transcript the same way; instead, on a fresh (non-resume) run it calls `TaskStore.context_reusable_messages(thread_id)` (`thread_id` and `context_id` are the same value there) and passes the result to `run_loop` as a new `extra_resolved_messages` parameter — scanned to seed the resolved-value index only, never appended to `messages` and never shown to the model, so AG-UI's smaller, text-only transcript is unchanged. The substitution still also works *within* one AG-UI run regardless (`run_loop` grows the resolved index across the several model turns one request drives); `extra_resolved_messages` is what additionally carries it to the *next* request. A resume run (continuing the same `TaskRecord`) needs neither — its `messages` already carries everything relevant from within that run.

**Why `context_reusable_messages()`, not `context_messages()` (RT-001/RT-009).** An AG-UI `TaskRecord.messages` never inherits a prior run's `messages` the way A2A's does — each run starts fresh from that run's own folded text only. Seeding from `context_messages()` (the single most recent terminal task, correct for A2A because its history already accumulates transitively) would decay after exactly one intervening, unrelated run: as soon as a later run with no marker of its own becomes the newest terminal task, the next run's seed is empty — silently reopening the wrong-but-real-id substitution GH-148 exists to catch, on a live thread that never stops being continued. `context_reusable_messages()` instead scans EVERY terminal task in the thread, so a marker survives for the life of the conversation. Neither method ever honours an admin api_key identity's cross-identity override (RT-009 for `context_reusable_messages()`; RT-004 below for `context_messages()`) — both seed a caller's own new task/run, not a read-only inspection view, so admin privilege must not leak another identity's resolved values or transcript into either. RT-010: to keep the reusable-messages scan bounded on a long-lived thread, it caps the number of terminal tasks scanned per call (newest first, `InMemoryTaskStore.MAX_REUSABLE_TASKS`) and returns only each task's `__resolved__` marker content (`agent.reuse.extract_resolved_markers`), never the full transcript — `scan_resolved` never reads anything else out of it.

**RT-004: `context_messages()`'s admin cross-identity override — A2A's own carrier, not just AG-UI's — was the same covert side channel closed above for `context_reusable_messages()`, and is now removed rather than mitigated.** A2A never calls `context_reusable_messages()`/`extra_resolved_messages` at all: `context_messages()`'s result is folded straight into `record.messages`, which `run_loop` scans directly for `__resolved__` markers — so any marker the bypass reached would have silently substituted into the admin caller's own `$ref` calls, exactly the risk RT-009 closed on AG-UI's carrier. An earlier revision mitigated only that half (stripping the marker while still returning the surrounding transcript) and documented the surrounding-transcript leak itself as intended design — a wave's own redteam self-ratifying new cross-identity data-exposure policy, never put to the user. `context_messages()` is now identity-scoped exactly like `context_reusable_messages()`: a cross-identity `contextId` returns no transcript at all, marker or otherwise, admin or not. See `tests/test_admin_continuation_scoped_to_own_identity.py` (end-to-end through the live ASGI app) and `tests/test_context_reusable_messages.py` (store-level).

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
