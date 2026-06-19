# Research 08 — A2A Protocol v0.3.0 Reference

**Track:** Protocol spec (NOT market data). Authoritative reference for the
`a2a-advisor` agent and any "shape up to fully A2A" work.

**Scope: A2A v0.3.0 ONLY** (released 2025-07-30). Sources, all pinned to the
`v0.3.0` tag: spec prose `a2a-protocol.org/v0.3.0/specification/`; JSON Schema
`github.com/a2aproject/A2A@v0.3.0/specification/json/a2a.json`; TypeScript
`types/src/types.ts`; `CHANGELOG.md`. The project moved from `google-a2a/A2A`
to `a2aproject/A2A` (Linux Foundation). v1.0 deltas are listed only to mark what
is **out of scope** — a 0.3.0 checker treats any v1.0-only shape as
non-conformant for 0.3.0.

---

## §1 Discovery & the Agent Card

**Well-known URI:** `https://{domain}/.well-known/agent-card.json` (RFC 8615,
SHOULD-strength). **v0.3.0 RENAMED** `agent.json` → `agent-card.json` (breaking).
v0.3.0 does not list `agent.json` as an allowed fallback — treat `agent.json` as
**v0.2.x-only**. Other discovery: registries/catalogs, direct configuration. A
card with sensitive info MUST be access-controlled. No card-caching guidance in
0.3.0 (ETag/conditional-GET is a valid local extension, not spec-mandated).

**AgentCard fields** (REQUIRED unless marked OPT; wire is camelCase):

| Field | Type | Req |
|---|---|---|
| `protocolVersion` | string (`"0.3.0"`) | **REQ** (in `required[]`; the `@default` JSDoc ≠ optional) |
| `name`, `description`, `version` | string | **REQ** |
| `url` | string | **REQ** — MUST serve the `preferredTransport` |
| `capabilities` | `AgentCapabilities` | **REQ** |
| `defaultInputModes`, `defaultOutputModes` | string[] (MIME) | **REQ** |
| `skills` | `AgentSkill[]` | **REQ** |
| `preferredTransport` | `TransportProtocol\|string` | OPT (`@default "JSONRPC"`) — but functionally required; must match `url` |
| `additionalInterfaces` | `AgentInterface[]` (`{url, transport}`) | OPT |
| `provider` (`{organization, url}`), `documentationUrl`, `iconUrl` | — | OPT |
| `securitySchemes` | `{name → SecurityScheme}` | OPT |
| `security` | `{scheme: string[]}[]` (OR-of-ANDs) | OPT |
| `signatures` | `AgentCardSignature[]` (JWS, **new in 0.3.0**) | OPT |
| `supportsAuthenticatedExtendedCard` | boolean (default false) | OPT |

- **`AgentCapabilities`**: `streaming?`, `pushNotifications?`, `stateTransitionHistory?` (booleans), `extensions?: AgentExtension[]`. ONLY these keys are spec — do NOT put `skills`/`contentTypes` inside it.
- **`AgentSkill`**: `id`, `name`, `description`, **`tags: string[]`** all REQUIRED; `examples?`, `inputModes?`, `outputModes?`, `security?` (per-skill, new in 0.3.0) OPT. **`tags` is required — common miss.**
- **`TransportProtocol` enum** (exact wire values): `"JSONRPC"`, `"GRPC"`, `"HTTP+JSON"` (note the `+`; gRPC + HTTP+JSON added in 0.3.0).
- **Authenticated Extended Card** (§7.10): method `agent/getAuthenticatedExtendedCard` → full `AgentCard`; only when `supportsAuthenticatedExtendedCard: true`; client MUST auth with a declared scheme; not-configured → error `-32007`.
- **Card signing**: `AgentCardSignature{protected, signature, header?}` — detached-payload JWS (RFC 7515) over the card JSON; key via `jku` in the protected header.

---

## §2 Transports & Methods

Three co-equal bindings; a compliant server MUST implement **≥1** (JSON-RPC is
NOT individually mandatory): **JSON-RPC 2.0** (`application/json`, POST),
**gRPC** (proto3/HTTP2), **HTTP+JSON/REST** (`/v1/{resource}[:{action}]`). Declare
via `preferredTransport` + `additionalInterfaces`. **Transport equivalence
(§3.4, §11.1.4):** all declared transports MUST offer identical operations,
semantically equivalent results, and consistent §8 error codes; task IDs are
portable across transports.

| JSON-RPC method | REST | params → result | SSE |
|---|---|---|---|
| `message/send` | POST `/v1/message:send` | `MessageSendParams` → `Task\|Message` | no |
| `message/stream` | POST `/v1/message:stream` | `MessageSendParams` → stream | **yes** (cap `streaming`) |
| `tasks/get` | GET `/v1/tasks/{id}?historyLength=` | `TaskQueryParams` → `Task` | no |
| `tasks/cancel` | POST `/v1/tasks/{id}:cancel` | `TaskIdParams` → `Task` | no |
| `tasks/resubscribe` | POST `/v1/tasks/{id}:resubscribe` | `TaskIdParams` → stream | **yes** |
| `tasks/pushNotificationConfig/set` | POST `/v1/tasks/{id}/pushNotificationConfigs` | `TaskPushNotificationConfig` → same | no (cap `pushNotifications`) |
| `…/get` `…/list` `…/delete` | GET/GET/DELETE on `…/pushNotificationConfigs[/{cfgId}]` | — | no |
| `agent/getAuthenticatedExtendedCard` | GET `/v1/card` | → `AgentCard` | no |
| *(REST/gRPC only — no JSON-RPC method)* `tasks/list` | GET `/v1/tasks` | → `Task[]` | no |

**Required core (§11.1.2):** `message/send`, `tasks/get` AND `tasks/cancel` are
the hard MUSTs (a server missing `tasks/cancel` is non-conformant — not merely
"good practice"); `message/stream`/push are SHOULD/MAY (gated by capability flags).
**`tasks/list`** (REST `GET /v1/tasks` + gRPC `ListTask`) has **no JSON-RPC
equivalent** — only required on REST/gRPC surfaces that declare it.

**Streaming/SSE (§3.3):** `200 OK`, `Content-Type: text/event-stream`. **JSON-RPC:**
each `data:` is a full JSON-RPC response (`SendStreamingMessageResponse{jsonrpc,id,result}`)
whose `result` ∈ {`Task`,`Message`,`TaskStatusUpdateEvent`,`TaskArtifactUpdateEvent`}.
**REST/HTTP+JSON:** bare event objects (no JSON-RPC envelope). Conventional first
event = the full `Task` snapshot. Terminate on `TaskStatusUpdateEvent.final:true`,
then close.

**Errors (§8):** standard JSON-RPC `-32700/-32600/-32601/-32602/-32603`; A2A-specific
`-32001` TaskNotFound, `-32002` TaskNotCancelable, `-32003` PushNotificationNotSupported,
`-32004` UnsupportedOperation, `-32005` ContentTypeNotSupported, `-32006`
InvalidAgentResponse, `-32007` AuthenticatedExtendedCardNotConfigured.

**Error → JSON-RPC code → REST HTTP code mapping:**

| A2A error | JSON-RPC code | REST HTTP code |
|---|---|---|
| TaskNotFound | -32001 | 404 |
| TaskNotCancelable | -32002 | 409 |
| PushNotificationNotSupported | -32003 | 501 |
| UnsupportedOperation | -32004 | 501 |
| ContentTypeNotSupported | -32005 | 415 |
| InvalidAgentResponse | -32006 | 502 |
| AuthenticatedExtendedCardNotConfigured | -32007 | 501 |
| Parse error | -32700 | 400 |
| Invalid request | -32600 | 400 |
| Method not found | -32601 | 404 |
| Invalid params | -32602 | 400 |
| Internal error | -32603 | 500 |

(Auth failures map to `401` +`WWW-Authenticate`; authorization failures to `403`.)

**Error code → method**: `-32001` on `tasks/get`/`tasks/cancel`/`tasks/resubscribe`/push-config; `-32002` on `tasks/cancel`; `-32003` on `tasks/pushNotificationConfig/*` when cap false; `-32005` on `message/send`/`message/stream`; `-32007` on `agent/getAuthenticatedExtendedCard`.

---

## §3 Core Objects & Lifecycle (all camelCase; `kind` discriminators REQUIRED)

- **Message** `kind:"message"`: `role`(`"user"|"agent"`), `parts`, `messageId` REQ; `taskId?`, `contextId?`, `referenceTaskIds?`, `extensions?`, `metadata?`.
- **Part** (union by `kind`): `TextPart`{`kind:"text"`,`text`} · `FilePart`{`kind:"file"`,`file`} where file = `FileWithBytes`{`bytes`(base64),mimeType?,name?} XOR `FileWithUri`{`uri`,mimeType?,name?} · `DataPart`{`kind:"data"`,`data`(arbitrary JSON)}. Optional `metadata?` on each. **Exactly 3 variants — `raw` and `url` are NOT standalone Part types** (bytes → `FilePart.file.bytes`; URI → `FilePart.file.uri`). The discriminator is **`kind`** (not `type` — `"type":"data"` is not a spec field; an agent or client using it is non-conformant). Structured artifacts MUST include a `DataPart` alongside any TextPart fallback — text-only for a chart/table/KPI is non-conformant.
- **Task** `kind:"task"`: `id`, `contextId`, `status`(`TaskStatus`) REQ; `history?`, `artifacts?`, `metadata?`. `id`=one unit of work; `contextId`=conversation grouping shared by related tasks.
- **TaskStatus**: `state`(`TaskState`) REQ; `message?`, `timestamp?`(ISO8601).
- **Artifact**: `artifactId`, `parts` REQ; `name?`, `description?`, `extensions?` (`string[]` of extension URIs), `metadata?`. (Field is **`artifactId`**, not `id`.)

**Request / param objects:**

- **`MessageSendParams`** (REQ: `message`): `message: Message` REQ · `configuration?: MessageSendConfiguration` OPT · `metadata?: {[key]:any}` OPT.
- **`MessageSendConfiguration`** (all OPT): `acceptedOutputModes?: string[]` (MIME types the client accepts) · `historyLength?: integer` (# history messages in response) · `pushNotificationConfig?: PushNotificationConfig` (inline push config) · `blocking?: boolean` (if true wait for completion; server MAY reject for long-running tasks).
- **`TaskQueryParams`** (REQ: `id`): `id: string` REQ · `historyLength?: integer` OPT · `metadata?: {[key]:any}` OPT.
- **`TaskIdParams`** (REQ: `id`): `id: string` REQ · `metadata?: {[key]:any}` OPT.
- **`TaskPushNotificationConfig`** (REQ: `taskId`, `pushNotificationConfig`): `taskId: string` REQ · `pushNotificationConfig: PushNotificationConfig` REQ.
- **`message/send` result**: `Task | Message` — a server MAY return a direct `Message` for a quick/synchronous response (no Task created); clients MUST handle both.
- **`GetAuthenticatedExtendedCardRequest.params`**: MUST be absent (TS `params?: never`).
- **`contextId`**: server-generated; client MAY supply it to associate a new task with an existing context. **Server-emitted `Message.contextId` is REQUIRED**; client-sent is OPT.
- **Terminal re-message rule**: a message targeting a task already in a terminal state MUST return an error — it MUST NOT start a new task.

**TaskState** (exact values; **American `"canceled"`, one L** in 0.3.0):

| value | terminal? | note |
|---|---|---|
| `submitted`, `working` | no | active |
| `input-required`, `auth-required` | no | **interrupted** — stream may close with `final`, resumes on new `Message` carrying same `taskId` |
| `completed`, `canceled`, `failed`, `rejected` | **yes** | absorbing |
| `unknown` | no | indeterminate |

**Streaming events:** `TaskStatusUpdateEvent`{`taskId`,`contextId`,`kind:"status-update"`,`status`,**`final`(REQ in 0.3.0)**,metadata?} · `TaskArtifactUpdateEvent`{`taskId`,`contextId`,`kind:"artifact-update"`,`artifact`,`append?`,`lastChunk?`}. Chunking: `append=true` concatenates parts onto the prior artifact of the same `artifactId`; `lastChunk=true` completes it.

**Lifecycle:** `submitted→working→completed|failed|rejected`; interrupted
`input-required`/`auth-required` → back to `working` on input; any non-terminal
→ `canceled`. Terminal states absorbing (a new turn = a new task).

---

## §4 Security & Push Notifications

**`securitySchemes`** map + **`security`** OR-of-ANDs array. SecurityScheme variants:

| variant | `type` | required fields | URL field |
|---|---|---|---|
| API key | `"apiKey"` | `type`,`in`(query/header/cookie),`name` | — |
| HTTP | `"http"` | `type`,`scheme`(bearer/basic), `bearerFormat?` | — |
| OAuth2 | `"oauth2"` | `type`,`flows`(`OAuthFlows`) | `oauth2MetadataUrl?` (**new in 0.3.0**) |
| OpenID Connect | `"openIdConnect"` | `type`,`openIdConnectUrl` | `openIdConnectUrl` |
| mTLS | `"mutualTLS"` | `type` | — (**new in 0.3.0**) |

`OAuthFlows`: `authorizationCode`{authorizationUrl,tokenUrl,scopes,refreshUrl?} ·
`clientCredentials`{tokenUrl,scopes} · `implicit`{authorizationUrl,scopes} ·
`password`{tokenUrl,scopes}. **Common error: `openIdConnectUrl` on an `oauth2`
scheme** — oauth2 uses `flows` (+ optional `oauth2MetadataUrl`); only
`openIdConnect` carries `openIdConnectUrl`.

**Transport security:** production MUST be HTTPS, TLS 1.2+ (1.3 recommended),
client verifies server cert. **Auth flow:** identity is established at the HTTP
layer (not in JSON-RPC payloads); credentials acquired out-of-band; sent via
`Authorization`/`X-API-Key`; server authenticates every request → `401` +
`WWW-Authenticate` or `403`. **Never put secrets in the card.** In-task secondary
auth via `auth-required` state. **Push** (gated by `capabilities.pushNotifications`):
webhook secured via JWT/JWKS, replay protection (timestamp + `jti`), SSRF allowlist
on client URLs (server MUST validate). On delivery, the server sends an
**`X-A2A-Notification-Token`** header carrying the config's `token`; the client
webhook validates it.

**`PushNotificationConfig`** (REQ: `url`):

| Field | Type | Req | Note |
|---|---|---|---|
| `url` | string | **REQ** | webhook URL |
| `id` | string | OPT | client-assigned; supports multiple configs per task |
| `token` | string | OPT | client validates on incoming webhook (`X-A2A-Notification-Token`) |
| `authentication` | `PushNotificationAuthenticationInfo` | OPT | — |

**`PushNotificationAuthenticationInfo`** (REQ: `schemes`): `schemes: string[]` REQ
(e.g. `["Bearer"]`) · `credentials?: string` OPT.

**Push config CRUD** (all require `capabilities.pushNotifications`): `set`/`get`/`list`/`delete`.
`delete` returns `null` on success and requires `pushNotificationConfigId`; `get`
takes an optional `pushNotificationConfigId`.

---

## §5 Conformance, Versioning, Extensions, Verification

**Hard MUSTs (§11.1):** (1) HTTP(S); (2) ≥1 core transport; (3) declare all
transports on the card; (4) serve a valid AgentCard (rec. `agent-card.json`);
(5) implement `message/send` + `tasks/get` + `tasks/cancel` (§11.1.2); (6) support `Task` + `TaskState`
transitions; (7) HTTP-header auth per §4; (8) multi-transport functional
equivalence; (9) conform to §3 data objects; (10) standard JSON-RPC error
semantics.

**Version deltas:**

| Added/changed in 0.3.0 (vs 0.2.x) | Changed/BROKE in v1.0 (OUT of scope) |
|---|---|
| well-known `agent.json`→`agent-card.json` | `final` removed from `TaskStatusUpdateEvent`; `kind` discriminators removed |
| `mutualTLS` + `oauth2MetadataUrl` | `preferredTransport`+`additionalInterfaces` → unified `supportedInterfaces[]` |
| `signatures` (card JWS) | enums → SCREAMING_SNAKE (`submitted`→`TASK_STATE_SUBMITTED`, `user`→`ROLE_USER`) |
| `supportsAuthenticatedExtendedCard` + `agent/getAuthenticatedExtendedCard` (`-32007`) | methods renamed (`message/send`→`SendMessage`…); `/v1` prefix dropped |
| per-skill `AgentSkill.security` | `mimeType`→`mediaType`; OAuth adds DeviceCode/`pkce_required` |

**Extensions (the sanctioned way to carry custom payloads):** declare in
`capabilities.extensions[]` as `AgentExtension{uri, description?, required?, params?}`;
negotiate via the `X-A2A-Extensions` HTTP header (client lists URIs to activate;
agent echoes those activated). **Our Enhanced content types / render-hints should
be a declared `AgentExtension` (own URI), not smuggled into payloads / `x-` keys.**

**Verification tooling:**
- **A2A Inspector** (`a2aproject/a2a-inspector`) — fetch card, schema-validate, live JSON-RPC console, validates each response against the spec.
- **A2A TCK** (`a2aproject/a2a-tck`) — official pytest conformance suite; `./run_tck.py --sut-host <URL> --level must` (RFC-2119 categorized; MUST=hard fail). Fetches `{host}/.well-known/agent-card.json`. Use as the gating CI check.
- **JSON-Schema validate** the live card against `a2a.json@v0.3.0`.
- **SDKs** `a2a-python` / `a2a-js` (pin a 0.3.0-compatible release) — typed clients round-trip `message/send`+`tasks/get`; type errors = drift.

**A2A vs MCP:** complementary — MCP = tool/resource provision to a model; A2A =
inter-agent collaboration/discovery across boundaries.

---

## §6 Top compliance mistakes (consolidated)

1. Serving legacy `/.well-known/agent.json` instead of `agent-card.json`.
2. Omitting `protocolVersion` / per-skill `tags`; polluting `capabilities` with non-spec keys.
3. `preferredTransport` value/`url` mismatch, or declaring a transport whose methods aren't actually implemented (declared ≠ served).
4. Missing `kind` discriminators on Part/Task/events; `artifactId`→`id`; snake_case wire (`task_id`) instead of camelCase (`taskId`); missing `contextId`. Using `"type"` instead of `"kind"` as the Part discriminator (`"type":"data"` is not a spec field — a client or agent using it is non-conformant). Structured artifacts missing the `DataPart` (text-only artifact for a chart/table = non-conformant).
5. `final` omitted/never `true` on status events → clients hang.
6. `openIdConnectUrl` on an `oauth2` scheme; secrets in the card; missing `WWW-Authenticate` on 401.
7. Accepting v1.0 shapes (snake-case enums, `supportedInterfaces`, no `final`) as 0.3.0.
8. `preferredTransport` absent (defaults to JSONRPC by type, but functionally required per §5.6.1 prose).
9. `tasks/cancel` missing (hard MUST §11.1.2, not optional).
10. `message/send` returning only `Task` when `Message` is also a valid result.
11. `GetAuthenticatedExtendedCard` carrying `params` (MUST be absent, `params?: never`).
12. `TaskStatusUpdateEvent.final` absent or never `true` (JSON Schema omits from `required[]`; TS marks non-optional — treat as required).
13. `FileWithBytes`/`FileWithUri` XOR violated (both or neither of `bytes`/`uri` set).
14. Sending messages to terminal tasks without returning an error (must not silently start a new task).
15. Emitting streaming events after `final:true`.

---

## §7 Client-Side Compliance (§11.2)

Obligations of an A2A **client** (a consumer calling another agent). Verify these
when the project ships a client, not just a server.

1. **Transport**: MUST implement ≥1 transport and select per **§5.6.3 transport selection rules** — prefer `preferredTransport`/`url`; fall back to `additionalInterfaces`; MUST use the correct URL for the selected transport; SHOULD implement fallback if the preferred transport fails.
2. **Request**: MUST construct valid `MessageSendParams` — `message` with `kind:"message"`, `role:"user"`, non-empty `parts`, `messageId`.
3. **Result**: MUST handle `Task | Message` as the result of `message/send`.
4. **Credentials**: MUST send credentials in HTTP headers (`Authorization`, `X-API-Key`) — never in JSON-RPC payloads.
5. **Errors**: MUST handle all A2A + standard JSON-RPC error codes (§8 / table in §2).
6. **Streaming**: MUST terminate consumption on `final:true`; SHOULD use `tasks/resubscribe` to reconnect after interruption (**server MAY NOT backfill missed events**); after the stream ends, MAY call `tasks/get` for final state.
7. **Interrupt resume**: for `input-required`/`auth-required`, MUST continue with the SAME `taskId`+`contextId` in the follow-up message.
8. **Extensions**: list extension URIs in the `X-A2A-Extensions` request header; read the agent's response header (same name) for the activated URIs.
9. **Authenticated extended card**: after auth, client SHOULD replace its cached public card with the authenticated version for the session duration.
