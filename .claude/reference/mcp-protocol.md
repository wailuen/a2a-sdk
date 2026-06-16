# Research — MCP Protocol Reference (build + conformance)

**Track:** Protocol spec. Authoritative reference for the `mcp-advisor` agent and the
`mcp-server` skill, and for any "build / shape up an MCP server" work. **Companion
file:** `mcp-claude-platforms.md` (the five Anthropic/Claude surfaces, connector
building, Directory submission, icons, known client bugs). Cite this file's sections
(§1–§13) when advising.

**Scope:** Model Context Protocol revisions **2025-03-26**, **2025-06-18** (current
broadly-supported baseline), **2025-11-25** (latest). Primary sources, all under
`https://modelcontextprotocol.io/specification/{rev}/`: `architecture`,
`basic/lifecycle`, `basic/transports`, `basic/authorization`,
`basic/security_best_practices`, `basic/utilities/{cancellation,progress,tasks}`,
`server/{tools,resources,prompts}`, `server/utilities/{pagination,logging,completion}`,
`client/{sampling,elicitation,roots}`, each `changelog`. RFCs from `datatracker.ietf.org`.
SDKs: `github.com/modelcontextprotocol/{typescript-sdk,python-sdk}`. Fetch the live spec
when you need exhaustive field detail beyond this digest.

> **Version strings (exact — used in `protocolVersion` and the `MCP-Protocol-Version`
> header):** `"2024-11-05"`, `"2025-03-26"`, `"2025-06-18"`, `"2025-11-25"`. These are
> **date strings, not semver.** **Baseline to target: `2025-06-18`.** Adopt `2025-11-25`
> for icons, richer elicitation, sampling tool-calls, and tasks (tasks = experimental).

---

## §1 Protocol basics

- MCP is **JSON-RPC 2.0** over a **stateful session**. Architecture is **host → client →
  server**: one host process spawns multiple clients; each client holds a **1:1 stateful
  session** with one server. Servers can't read the whole conversation or see other servers;
  the host enforces security boundaries.
- **Three message types.** **Request**: `{jsonrpc:"2.0", id, method, params?}` — `id` is
  string|int, MUST NOT be null, MUST be unique per session and not reused. **Response**:
  `{jsonrpc, id, result|error}` — exactly one of `result`/`error`; `error` is
  `{code, message, data?}`. **Notification**: `{jsonrpc, method, params?}` — **no `id`**,
  never answered.
- Messages **MUST be UTF-8**.
- **JSON-RPC batching**: added 2025-03-26, **REMOVED in 2025-06-18** (PR #416). Do not send
  batches at 2025-06-18+.

---

## §2 Lifecycle

Phases: **Initialization → Operation → Shutdown**.

**`initialize`** (client→server, MUST be the first message):
```json
{ "jsonrpc":"2.0","id":1,"method":"initialize","params":{
  "protocolVersion":"2025-06-18",
  "capabilities":{"roots":{"listChanged":true},"sampling":{},"elicitation":{}},
  "clientInfo":{"name":"ExampleClient","title":"Example Client","version":"1.0.0"} } }
```
**`initialize` result** (server→client):
```json
{ "jsonrpc":"2.0","id":1,"result":{
  "protocolVersion":"2025-06-18",
  "capabilities":{"logging":{},"prompts":{"listChanged":true},
    "resources":{"subscribe":true,"listChanged":true},"tools":{"listChanged":true}},
  "serverInfo":{"name":"ExampleServer","title":"Example Server","version":"1.0.0"},
  "instructions":"Optional usage instructions for the client/model" } }
```
- **`Implementation`** (`clientInfo`/`serverInfo`): `name` (programmatic ID, REQ),
  `title` (human display, OPT, **added 2025-06-18**), `version` (REQ). 2025-11-25 also adds
  `description`, `websiteUrl`, and **`icons`** (`{src, mimeType, sizes}`).
- **`initialized` notification** (`{"method":"notifications/initialized"}`) follows a
  successful init. Before init completes only `ping` (and server `logging`) is allowed.
- **`instructions`** in the result is OPTIONAL — free-text guidance surfaced to the model.

**Version negotiation:** client sends a version it supports (SHOULD be latest). If the
server supports it, it **MUST echo the same string**; else it MUST return another version
it supports. If the client doesn't support the server's answer, it SHOULD disconnect.
Unsupported version → error `-32602` with `data:{supported:[...],requested:"..."}`.

**Shutdown:** no protocol message. stdio → close child stdin, then SIGTERM, then SIGKILL.
HTTP → close the connection(s).

---

## §3 Capabilities (negotiation)

Declare a capability to use its feature; respect the peer's declared set.

| Side | Capability | Sub-flags |
|---|---|---|
| Server | `tools` | `listChanged` |
| Server | `resources` | `subscribe`, `listChanged` (independent) |
| Server | `prompts` | `listChanged` |
| Server | `logging` | `{}` |
| Server | `completions` | `{}` |
| Server | `tasks` (2025-11-25) | `list`, `cancel`, `requests.tools.call` |
| Client | `roots` | `listChanged` |
| Client | `sampling` | `{}` |
| Client | `elicitation` | `{}`=form-only at 2025-06-18; `{form:{},url:{}}` at 2025-11-25 |
| Client | `tasks` (2025-11-25) | `list`, `cancel`, `requests.{sampling.createMessage,elicitation.create}` |
| Both | `experimental` | non-standard |

Don't emit `notifications/.../list_changed` unless you declared `listChanged`; don't emit
`notifications/resources/updated` unless `resources.subscribe:true`.

---

## §4 Tools (model-controlled)

**Methods:** `tools/list` (paginated via `cursor`/`nextCursor`); `tools/call`
(`params:{name,arguments?}` → `{content:[...],structuredContent?,isError?}`);
`notifications/tools/list_changed`.

**Tool definition:** `name` (REQ, unique), `title` (OPT, 2025-06-18+), `description`,
`inputSchema` (JSON Schema `type:"object"`; 2025-11-25 defaults to **JSON Schema 2020-12**;
no-params → `{"type":"object","additionalProperties":false}`), `outputSchema` (OPT),
`annotations` (OPT), `icons` (2025-11-25), `execution:{taskSupport}` (2025-11-25:
`"forbidden"`(default)|`"optional"`|`"required"`).

**Annotations (`ToolAnnotations`) — all OPT hints, all untrusted unless from a trusted server:**

| Field | Default | Meaning |
|---|---|---|
| `title` | — | human display name |
| `readOnlyHint` | **false** | no environment modification |
| `destructiveHint` | **true** | may do destructive/irreversible updates (only meaningful if not read-only) |
| `idempotentHint` | **false** | repeat calls with same args have no extra effect |
| `openWorldHint` | **true** | interacts with external entities |

> **Easy to get wrong:** `destructiveHint` and `openWorldHint` **default to `true`**;
> `readOnlyHint`/`idempotentHint` default to `false`.

**Result content blocks (`content[]`):** `text {type,text}` · `image {type,data(b64),mimeType}`
· `audio {type,data(b64),mimeType}` · `resource_link {type,uri,name,description?,mimeType?}`
· embedded `resource {type,resource:{uri,mimeType,text|blob}}`. All support optional
`annotations` (`audience`, `priority`, `lastModified`).

**Structured output:** `structuredContent` is a JSON object in the result. If `outputSchema`
is set, the server **MUST** return conforming `structuredContent`; clients SHOULD validate.
**Always also serialize the same JSON into a `text` content block** for back-compat clients.

**`isError`:** absent/false = success; `true` = **tool execution error** reported *inside a
normal `result`* (see §9).

---

## §5 Resources (application-driven)

**Methods/notifications:** `resources/list` (paginated), `resources/read`
(`{uri}`→`{contents:[...]}`), `resources/templates/list`, `resources/subscribe` &
`/unsubscribe` (need `subscribe`), `notifications/resources/updated {uri}`,
`notifications/resources/list_changed` (need `listChanged`).

**Resource:** `uri` (REQ, unique), `name` (REQ), `title` (OPT, 2025-06-18+), `description?`,
`mimeType?`, `size?` (bytes), `annotations?`, `icons?` (2025-11-25).
**Contents:** text `{uri,mimeType,text}` or binary `{uri,mimeType,blob(b64)}`.
**Templates:** `{uriTemplate (RFC 6570, e.g. "file:///{path}"), name, title?, description?, mimeType?}`;
template args are auto-completable via §8 completion.
**URI schemes:** `https://`, `file://`, `git://`, custom (RFC 3986). Not-found → `-32002` (with `data.uri`).

---

## §6 Prompts (user-controlled — e.g. slash commands)

**Methods:** `prompts/list` (paginated); `prompts/get` (`{name,arguments?}`→
`{description?,messages:[...]}`); `notifications/prompts/list_changed`.
**Prompt:** `name` (REQ), `title?` (2025-06-18+), `description?`, `arguments?:[{name,description?,required?}]`.
**`PromptMessage`:** `{role:"user"|"assistant", content}` — content is `text|image|audio|resource`
(no `"system"` role). Bad name / missing required arg → `-32602`.

---

## §7 Client features (a server MAY call these *on the client*)

**Sampling** (`sampling/createMessage`, client cap `sampling:{}`): server asks the client's
LLM to generate — no server API key. Params: `messages[]` (`{role,content}`),
`modelPreferences{hints:[{name}],costPriority,speedPriority,intelligencePriority}` (priorities
0–1; hints are advisory substrings, client may map to other providers and makes the final
choice), `systemPrompt?`, `includeContext?` (`none|thisServer|allServers`), `maxTokens`,
`temperature?`, `stopSequences?`, `metadata?`. Result: `{role:"assistant",content,model,stopReason}`.
**Human-in-the-loop SHOULD always be possible** (user can review/edit/deny). 2025-11-25 adds
`tools`+`toolChoice` (SEP-1577).

**Elicitation** (`elicitation/create`, **new in 2025-06-18**, client cap `elicitation`): server
requests structured user input. Params: `message` + `requestedSchema` = a **flat object,
primitives only** (no nesting, no arrays-of-objects). Property types: string (`minLength`,
`maxLength`, `format`∈`email|uri|date|date-time`), number/integer (`minimum`,`maximum`),
boolean (`default`), enum (`enum`+`enumNames`). Result `action`∈`accept|decline|cancel`; only
`accept` carries `content`. **Servers MUST NOT request secrets via (form) elicitation.**
2025-11-25: `mode:"form"`(default)|`"url"`; default values on all primitives (SEP-1034);
EnumSchema via `oneOf`/`anyOf`+`const`, multi-select arrays (SEP-1330); URL mode for
sensitive/out-of-band flows with `elicitationId` + `notifications/elicitation/complete` +
error `-32042` (SEP-1036).

**Roots** (`roots/list`, client cap `roots`): client exposes filesystem roots
`{roots:[{uri(file:// MUST),name?}]}`; `notifications/roots/list_changed`.

---

## §8 Utilities

- **Pagination:** opaque `cursor`→`nextCursor`; missing `nextCursor` = end. Server picks page
  size; cursors are **opaque** (don't parse/persist). On `tools/list`, `resources/list`,
  `resources/templates/list`, `prompts/list` (and `tasks/list`). Invalid cursor → `-32602`.
- **Ping:** either side; receiver replies empty result promptly. Allowed pre-init.
- **Cancellation:** `notifications/cancelled {requestId,reason?}`. **`initialize` MUST NOT be
  cancelled.** Receiver stops work and does NOT respond; a late response may still arrive —
  ignore it.
- **Progress:** opt in via `params._meta.progressToken` (string|int, unique). Server emits
  `notifications/progress {progressToken,progress,total?,message?}`; `progress` MUST increase.
- **Logging** (server cap `logging`): `logging/setLevel {level}`;
  `notifications/message {level,logger?,data}`. **Levels (RFC 5424):** `debug, info, notice,
  warning, error, critical, alert, emergency`. No credentials/PII in logs.
- **Completion** (server cap `completions`): `completion/complete {ref,argument,context?}` →
  `{completion:{values(≤100),total?,hasMore?}}`. `ref`=`{type:"ref/prompt",name}` or
  `{type:"ref/resource",uri}`; `context.arguments` (previously-resolved args, added 2025-06-18).
- **Tasks (2025-11-25, experimental):** augment any request with `params.task:{ttl?}` →
  receiver returns `CreateTaskResult{task:{taskId,status,createdAt,lastUpdatedAt,ttl,pollInterval?}}`.
  `tasks/get`|`result`|`list`|`cancel`; `notifications/tasks/status`. Statuses: `working`,
  `input_required`, `completed`, `failed`, `cancelled` (last three terminal). Opt-in per tool
  via `execution.taskSupport`.

---

## §9 Error handling — the build rule

Two mechanisms, **don't conflate them**:

1. **Protocol errors** — standard JSON-RPC `error`. For: unknown tool/method, malformed
   request, bad params shape, server faults. The model generally can't self-correct.
2. **Tool execution errors** — returned **inside a successful `result`** with `isError:true`
   and the failure in `content[]`. For: API failures, business-logic errors, and (2025-11-25,
   SEP-1303) **input-validation errors** — so the model can read the message and retry. Clients
   SHOULD feed these back to the LLM.

> **Rule:** a tool that *runs but fails* → `{result:{content:[...],isError:true}}`. Reserve
> JSON-RPC `error` for "the request itself was wrong" (unknown tool / malformed params).

| Code | Meaning | Typical use |
|---|---|---|
| `-32700` | Parse error | malformed JSON |
| `-32600` | Invalid Request | e.g. task-augmentation required (2025-11-25) |
| `-32601` | Method not found | unsupported capability/method; roots unsupported |
| `-32602` | Invalid params | unsupported version, invalid cursor, bad prompt name, missing args, bad log level |
| `-32603` | Internal error | server-side failure |
| `-32002` | Resource not found | `resources/read` |
| `-32042` | URLElicitationRequired | 2025-11-25 |

App-defined codes allowed outside the reserved JSON-RPC range.

---

## §10 Transports

All JSON-RPC 2.0, UTF-8. Two standard transports + one deprecated.

**stdio (local, process-spawned).** Client launches server as a subprocess; server reads
JSON-RPC from stdin, writes to stdout, **newline-delimited, no embedded newlines.**
**THE #1 stdio BUG:** writing anything non-MCP to **stdout** corrupts the stream — a stray
`print`/`console.log` breaks the session. **Log to stderr only.** Use for local, single-client
integrations (editors, desktop, CLI). Simplest; also a security win (access limited to the
spawning client).

**Streamable HTTP (remote — recommended for production).** One endpoint path (e.g. `/mcp`)
serving **POST + GET**:
- **POST**: each client→server message is a POST. Client MUST send
  `Accept: application/json, text/event-stream`. For a *request*, server replies either
  `application/json` (one object) or `text/event-stream` (SSE that eventually carries the
  response). For a *notification/response* input → **202 Accepted**, no body.
- **GET (optional SSE)**: client MAY open a server→client SSE stream; server returns
  `text/event-stream` or **405** if none offered.
- **`Mcp-Session-Id`**: server MAY assign it on the InitializeResult; if assigned the client
  MUST echo it on every later request. SHOULD be globally unique + cryptographically secure;
  visible ASCII only (0x21–0x7E). Missing-when-required → **400**; expired/terminated → **404**
  (client re-initializes). Client ends a session with HTTP **DELETE** + the header.
- **Resumability (`Last-Event-ID`)**: server MAY put `id` on SSE events; on reconnect the
  client GETs with `Last-Event-ID` and the server MAY replay **on the same stream only**.
- **`MCP-Protocol-Version` header** required on all post-init HTTP requests; invalid →
  **400**; absent → server SHOULD assume `2025-03-26`.
- **Security (spec MUST):** validate the **`Origin`** header (DNS-rebinding defense; 2025-11-25
  → invalid Origin = **403**); bind to `127.0.0.1` when local; implement auth (§11).

**Deprecated HTTP+SSE (two-endpoint, 2024-11-05).** Old: a GET SSE endpoint emitting an
`endpoint` event + a separate POST endpoint. Replaced by Streamable HTTP; keep only for legacy
clients. Back-compat: host both; clients POST `InitializeRequest` (new) and on 4xx fall back to
GET-expecting-`endpoint` (old).

---

## §11 Authorization (OAuth 2.1) — for remote HTTP servers

Auth is **OPTIONAL** in MCP and **only for HTTP transports**; stdio servers take credentials
from the environment, not this flow. The MCP server is an **OAuth 2.1 Resource Server**; the
**Authorization Server** is a logically separate role (co-located or an external IdP),
discovered via RFC 9728. The MCP client is the OAuth client.

**Discovery chain (exact order):**
1. **401 challenge.** Unauthenticated request → `401` + `WWW-Authenticate: Bearer
   resource_metadata="https://<host>/.well-known/oauth-protected-resource"`. (2025-11-25 also
   allows serving metadata at the well-known URI without the header; clients support both.
   SHOULD add a `scope=` param.)
2. **`GET /.well-known/oauth-protected-resource`** (RFC 9728). Fields: `resource` (REQ — the
   canonical server URI), `authorization_servers` (≥1, MCP requires it), `scopes_supported`
   (RECOMMENDED), `bearer_methods_supported`, `jwks_uri?`, `resource_name?`,
   `resource_documentation?`, etc. The returned `resource` MUST equal the identifier the
   well-known suffix was inserted into.
3. **`GET /.well-known/oauth-authorization-server`** (RFC 8414), fallback
   `/.well-known/openid-configuration`. Fields: `issuer` (REQ), `authorization_endpoint`,
   `token_endpoint`, `registration_endpoint?`, `response_types_supported` (REQ),
   `grant_types_supported?`, **`code_challenge_methods_supported`** (load-bearing — see PKCE),
   `token_endpoint_auth_methods_supported?`, `scopes_supported?`. 2025-11-25 mandates a
   multi-endpoint probe order (path-insertion vs path-appending for OAuth + OIDC).
4. **Obtain `client_id`.** 2025-06-18: Dynamic Client Registration (RFC 7591, `POST
   registration_endpoint`; req fields `redirect_uris`, `token_endpoint_auth_method`∈
   `none|client_secret_post|client_secret_basic`, `grant_types`, `client_name`, `logo_uri`…;
   resp 201 with `client_id`, `client_secret?`). 2025-11-25 priority: **pre-registered →
   Client ID Metadata Documents (CIMD, new) → DCR (downgraded SHOULD→MAY) → prompt user.**

**OAuth 2.1 flow:** authorization code + **PKCE**. Browser→`authorization_endpoint` with
`code_challenge` (**S256 required** when capable), `redirect_uri`, `state`, `scope`, and the
**`resource` param**. Then `token_endpoint` with `code_verifier` + `resource` → access token
(+ refresh). PKCE: `code_verifier` 43–128 chars unreserved; `code_challenge =
BASE64URL(SHA256(verifier))`; mismatch → `invalid_grant`.

**Resource Indicators (RFC 8707):** clients **MUST** send `resource` in **both** auth and
token requests; it MUST be the server's **canonical URI** (absolute, no fragment, prefer no
query/trailing slash) — e.g. `https://mcp.example.com/mcp`. Sent regardless of whether the AS
supports it.

**Token rules (server side, MUSTs):** validate every `Authorization: Bearer` token —
signature/introspection, expiry, and **`aud` == your canonical URI** (RFC 8707 / JWT profile
RFC 9068). Reject mismatches with **401**. **Never** accept tokens in the query string. Issue
short-lived tokens; rotate refresh tokens for public clients. **Token passthrough is
explicitly forbidden** — if you call upstream APIs, exchange for a *separate* upstream token;
never forward the client's token.

**Security MUSTs:** HTTPS for all AS endpoints; redirect URIs `localhost` or HTTPS, **exact
match** (no wildcards); PKCE S256 (2025-11-25: refuse to proceed if
`code_challenge_methods_supported` absent); `state` for CSRF; **confused-deputy** — proxies
with static client IDs MUST get per-client user consent before forwarding. 2025-11-25 adds
step-up auth (`403` + `WWW-Authenticate: error="insufficient_scope"`) and CIMD/SSRF guidance.

**OAuth-server implementation MUSTs (field-hardened — build a real AS, not theater):**
- **Bind grant identity to the token, not the caller.** On `refresh_token` and auth-code
  exchange, read `client_id` (and key/scope) from the **stored token metadata** and assert it
  equals the caller-supplied `client_id` *before* any secret check or minting — else a public
  client can rotate a confidential client's refresh token, or any registered client can redeem
  a stolen one. Never branch confidential-vs-public on the caller-supplied value.
- **A claimed binding must be validated-at-issue AND persisted-in-metadata AND checked-at-use
  — all three.** The `resource`/audience that's validated at `/authorize` is theater unless it's
  written into the minted token's metadata and re-checked by the resource server on every
  request (and carried through refresh rotation). Same rule for scope/tenant/expiry. A binding
  present in the authorize handler that never appears in the mint signature or the verification
  path protects nothing.
- **Adding a new credential KIND to a shared auth dependency widens authority to every
  consumer.** If you teach a shared `require_auth` to also accept OAuth connector tokens so
  `/mcp` works, every other route using that dependency (admin, management, other protocol
  surfaces) silently starts accepting them too — authority the consent screen never showed.
  **Tag the resolved identity with its `kind` and re-assert per surface** (admin/management
  planes reject the connector kind); don't assume the union. Enumerate every consumer before
  changing a shared resolver's accepted-credential set.

---

## §12 Security best practices (server authors)

From `basic/security_best_practices` and the tools/transport security sections:
- **Validate all tool inputs**; enforce access control; **rate-limit** invocations; **sanitize
  outputs** (tool results can carry prompt injection — clients SHOULD validate before passing
  to the LLM).
- **Token passthrough prohibited** (§11): never accept a token not issued *to you*, never
  forward the client's token downstream.
- **Confused deputy** (OAuth proxy with static client ID): store per-client consent server-side
  and check before forwarding; exact-match `redirect_uri`; random single-use short-lived
  `state`; CSRF + anti-clickjacking on consent pages; `__Host-` cookies (`Secure`,`HttpOnly`,
  `SameSite=Lax`).
- **SSRF** (fetching attacker-controlled URLs e.g. OAuth metadata): require HTTPS; block
  private/reserved ranges (`10/8`,`172.16/12`,`192.168/16`,`127/8`,`169.254/16` incl. cloud
  metadata `169.254.169.254`, `fc00::/7`,`fe80::/10`); validate each redirect hop; egress proxy;
  pin DNS (TOCTOU). **Don't hand-roll IP parsing** — encoding tricks defeat it.
- **Session IDs are NOT auth.** Use a CSPRNG/UUID; **MUST NOT** authenticate by session; verify
  every request; bind session data to identity with a key like `<user_id>:<session_id>`
  (defeats session-hijack via guessed IDs, esp. with shared/resumable queues across nodes).
- **Don't log secrets**; minimize scopes (least privilege, progressive elevation via
  `WWW-Authenticate`; never publish wildcard scopes like `*`/`full-access`).
- **Confirm destructive actions**; keep a human able to deny tool invocations.
- **Local servers:** prefer stdio (access limited to spawner); if HTTP-local, require a token,
  validate `Origin`/`Host`, bind `127.0.0.1`. One-click installs MUST show the exact command +
  get consent.
- **CORS is set once at app construction and inherited by every later route.** Never
  `allow_origins=["*"]` on an app that mounts auth-bearing routes; drive the allowlist from a
  validated config field that rejects `"*"`/empty. "Permissive for now, tighten later" rarely
  tightens.
- **Error-response headers derived from request data must degrade, never escalate** (see
  platforms P9.2): if a `401`'s `WWW-Authenticate` URL is built from the `Host`/base-URL and that
  builder can raise, wrap it so a malformed `Host` yields a header-less `401` — never a `503`
  status flip (an availability + status-oracle bug that also drops the discovery header).

---

## §13 SDK / build patterns

> **TypeScript SDK version note:** `main` is **v2 (pre-alpha)**; **v1.x is recommended for
> production** (v2 targeted ~Q1 2026). v1.x imports `@modelcontextprotocol/sdk/...`; v2 splits
> packages and uses Standard Schema. `registerTool`/`registerResource`/`registerPrompt` is
> stable across both.

**TypeScript — `McpServer` + `registerTool` + stdio:**
```typescript
import { McpServer } from '@modelcontextprotocol/sdk/server/mcp.js';
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js';
import { z } from 'zod';

const server = new McpServer({ name: 'my-server', version: '1.0.0' });
server.registerTool('calculate-bmi',
  { title: 'BMI Calculator', description: 'Calculate Body Mass Index',
    inputSchema: { weightKg: z.number(), heightM: z.number() },
    outputSchema: { bmi: z.number() } },
  async ({ weightKg, heightM }) => {
    const out = { bmi: weightKg / (heightM * heightM) };
    return { content: [{ type:'text', text: JSON.stringify(out) }], structuredContent: out };
  });
await server.connect(new StdioServerTransport());
```

**TypeScript — Streamable HTTP, stateful sessions** (pattern from the SDK's
`simpleStreamableHttp.ts`): keep a `transports` map keyed by `Mcp-Session-Id`; reuse on later
requests; on an initialize request create a new `StreamableHTTPServerTransport({
sessionIdGenerator: () => randomUUID(), eventStore, onsessioninitialized })`, register it, and
clean up `onclose`. Wire `app.post('/mcp')`, `app.get('/mcp')` (SSE), `app.delete('/mcp')`
(teardown). For **stateless** API-style servers use `sessionIdGenerator: undefined` and/or
`enableJsonResponse:true`. The SDK ships `createMcpExpressApp()` + `hostHeaderValidation(...)`
(on by default for localhost) for DNS-rebinding defense.

**Python — FastMCP (folded into the official `python-sdk`):**
```python
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel

mcp = FastMCP(name="Weather")

class WeatherData(BaseModel):
    temperature: float; humidity: float; condition: str

@mcp.tool()
def get_weather(city: str) -> WeatherData:   # return type → auto outputSchema + structuredContent
    """Get weather for a city."""             # docstring → tool description
    return WeatherData(temperature=22.5, humidity=45.0, condition="sunny")

if __name__ == "__main__":
    mcp.run()                                 # stdio (default)
    # mcp.run(transport="streamable-http")
```
FastMCP **auto-generates `outputSchema` from the return annotation** and returns both
`content` + `structuredContent` (validates against it). Supported return types: Pydantic
models, TypedDicts, dataclasses, `dict[str,T]`, primitives/generics (wrapped `{"result":value}`).
No type hints → no structured output. `structured_output=False` to suppress. Return
`CallToolResult` for full control (incl. `_meta`, which passes data to the client app without
exposing it to the model). `@mcp.resource("file://documents/{name}")` and `@mcp.prompt` for the
other primitives.

**Tool design (Anthropic "Writing tools for agents"):** build tools around **high-impact
workflows**, consolidate (one `schedule_event` over `list_users`+`list_events`+`create_event`);
keep the count manageable; **namespace** names (`asana_projects_search`); unambiguous params
(`user_id` not `user`); descriptions written *for an LLM* (make formats/terminology explicit);
return **high-signal, token-efficient** output (human-readable names over UUIDs; support
pagination/filtering/truncation with guidance; offer a `response_format: concise|detailed`);
specific, actionable error messages so the agent self-corrects. **Tool vs resource:** action /
side effects / model-invoked → **tool**; read-only reference data, app-controlled, GET-like →
**resource**. Tool name guidance (2025-11-25 SEP-986): 1–128 chars, `[A-Za-z0-9_.-]`,
case-sensitive, unique (note: some Claude surfaces cap names tighter — see platforms doc).

**Testing:** **MCP Inspector** — `npx @modelcontextprotocol/inspector <command> <args...>`
(e.g. `npx @modelcontextprotocol/inspector node build/index.js`, or `... uvx mcp-server-git`).
Lists/executes tools/resources/prompts, shows notifications. Verify connectivity + capability
negotiation, then test edge cases (invalid input, missing args, errors). Also evaluate on
realistic multi-tool tasks and read raw transcripts.

**Deployment:** **stateless** (`stateless_http=True, json_response=True` in FastMCP;
`sessionIdGenerator: undefined` in TS) scales horizontally best — any node serves any request.
**Stateful** enables resumability + server-initiated streams but needs cross-node session
coordination (shared store or message routing; key queues by `<user_id>:<session_id>`).
Common host: **Cloudflare Workers** (Streamable HTTP; `createMcpHandler` stateless, `McpAgent`
stateful via Durable Objects).

---

## §14 Version deltas

**2024-11-05 → 2025-03-26:** added OAuth 2.1 framework; **replaced HTTP+SSE with Streamable
HTTP**; added JSON-RPC batching; added tool **annotations**; added **audio** content; added
`completions` capability; `message` on progress notifications.

**2025-03-26 → 2025-06-18:** **removed batching** (PR #416); **structured tool output**
(`outputSchema`+`structuredContent`); **`resource_link`** in tool results; **elicitation**
(new); MCP server reframed as **OAuth Resource Server** (RFC 9728 PRM discovery + **RFC 8707
Resource Indicators** required, audience-bound tokens) — the 2025-03-26 embedded-AS /
"third-party authorization flow" model was **removed**; **`MCP-Protocol-Version` header
required** post-init; **`title`** added on tools/resources/prompts/Implementation; `_meta`
broadened; completion `context`; security-best-practices page added.

**2025-06-18 → 2025-11-25 (latest):** **icons** on tools/resources/templates/prompts +
serverInfo/clientInfo (SEP-973); `Implementation.description`/`websiteUrl`; **elicitation
EnumSchema** overhaul (SEP-1330) + **URL mode** (SEP-1036) + defaults (SEP-1034); **sampling
tool-calling** `tools`/`toolChoice` (SEP-1577); **tasks** (experimental, SEP-1686); **JSON
Schema 2020-12** default (SEP-1613); **tool name guidance** 1–128 chars (SEP-986); **input
validation → tool execution error** (SEP-1303); invalid `Origin` → **403**; OAuth: OIDC
Discovery (SEP-797), incremental scope (SEP-835), Client ID Metadata Documents (SEP-991),
RFC 9728 alignment (SEP-985).

**Treat any feature above its revision as non-applicable when negotiating an older version.**
E.g. emitting `icons` while negotiating `2025-06-18` is version-inconsistent — gate icons on
`negotiated == "2025-11-25"`.
