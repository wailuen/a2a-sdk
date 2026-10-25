# Protocol surfaces

One task runner serves every protocol: a single worker per task folds loop
events into the canonical A2A `Task` and publishes dual-form stream items
(pre-built A2A frame + raw event for the AG-UI mapper). Interrupts resume
identically across protocols.

## A2A v0.3.0 (HTTP+JSON)

| Endpoint | Behavior |
|---|---|
| `POST /v1/message:send` | 200 + Task. Default: immediate snapshot. `configuration.blocking: true` waits for a terminal or `input-required` state (capped at the smaller of the task deadline and `AGENT_SDK_BLOCKING_SEND_MAX`, default 120 s; on the cap it returns the current non-terminal Task while the worker keeps running, so poll `tasks/get`). Resume by including `taskId` (blocking resume waits the same way) |
| `POST /v1/message:stream` | SSE; first frame is the **full Task**, then status/artifact frames until `final: true` |
| `GET /v1/tasks/{id}` | Task; `historyLength` truncates (0 → `[]`) |
| `POST /v1/tasks/{id}:cancel` | 200 + canceled Task; 404/409 per table |
| `POST` or `GET /v1/tasks/{id}:subscribe` | re-attach SSE; both verbs share one handler, auth and stream cap |
| `GET /v1/tasks` | 200; identity-scoped paginated list — query params `pageSize` (1–100, default 50) and `pageToken`; response `{tasks, totalSize, pageSize, nextPageToken}`; a non-empty `pageToken` the task store rejects → 400 `-32602` "invalid pageToken" (empty = first page). The route asks `TaskStore.is_valid_page_token` (default accepts any token; `InMemoryTaskStore` accepts 32 lowercase hex characters) and pages with `TaskStore.list_tasks_for_identity`; a custom store overrides both. Listing is always scoped to the caller's identity, so a token from another identity pages nothing |

Error table (body `{"error": {code, message}}`): unknown/foreign task →
404 `-32001`; terminal-task cancel → 409 `-32002`; terminal-task resume
(`message:send` or `message:stream` with `taskId`) → 400 `-32004`; push
config → `-32003`: `POST`/`GET /v1/tasks/{id}/pushNotificationConfigs` and
`GET`/`DELETE /v1/tasks/{id}/pushNotificationConfigs/{configId}` all return 501
`-32003` (identity required; same reply for known, foreign and unknown tasks;
body never read); unacceptable
`acceptedOutputModes` → `-32005`; missing `messageId` → 400 `-32602`;
too many concurrent streams → 429 `-32000` + `Retry-After` (see below);
client `message.role` other than `user` → 400 `-32602`; any unhandled error
on `/v1/*` → 500 `-32603` "internal error" (fixed text). `acceptedOutputModes`
matching is case-insensitive, ignores parameters, and accepts `*/*` and `type/*`
(`text` stays an alias of `text/plain`); `Content-Type` is compared
case-insensitively; `historyLength` applies to the resume reply and the first
stream snapshot. Deviation (GH-266): A2A v0.3.0 maps `-32004` to HTTP 501; the SDK answers 400 for wrong-state messages
(ruling: https://github.com/wailuen/a2a-sdk/issues/266#issuecomment-6395232882, restated in
https://github.com/wailuen/a2a-sdk/issues/271#issuecomment-6398502964). `-32004` takes its HTTP status per call site: a wrong-state message
(terminal-task resume on `message:send` or `message:stream`, and `message:send` or
`message:stream` to a task that is not awaiting input) → 400; an unsupported operation and the
colon-id wrong-verb guard (`GET /v1/tasks/{id}:cancel`) → 501; the 405 a wrong
HTTP verb gets from the router is transport-level and also carries `-32004`.
JSON-RPC client codes map `-32600` → 400 and `-32601` → 404 (with `-32700` and
`-32602` → 400).
A request body over 1 MiB gets 400 `-32602` "request body too large". A failed task
always carries `status.message` (role `agent`, one TextPart) with the same safe text
as `status.error.message`; `status.error` is an SDK extension that spec-compliant
clients can ignore. When a client sends `acceptedOutputModes`, artifact parts are
filtered to the accepted types; if none remain and `text/plain` is accepted, one
TextPart fallback is kept, otherwise the task fails with `-32005`. GH-261: A2UI
is used for an artifact only when the app gate, the `X-A2A-Extensions` opt-in and
the modes all agree (modes absent, or accepting `application/a2ui+json` directly or
by wildcard); otherwise the JSON DataPart / TextPart fallback is built and then
filtered, so `["application/json"]` with the header gets a JSON DataPart.
**Bare wire (GH-248):** success bodies and SSE frames are bare `Task | Message`
or frame objects, not the proto's wrapped `SendMessageResponse` /
`StreamResponse`; v0.3.0 HTTP+JSON examples and existing clients use the bare form. Task
access is
**identity-bound**: someone else's task id returns 404 `-32001` —
existence is never leaked (admin keys bypass).

Input is text only (`defaultInputModes: ["text/plain"]`). A2A rejects any
`FilePart`/`DataPart` on a new task with `-32005` (HTTP 415) and a message with
no text with `-32602`, before a task is created. A resume of an interrupt may
also carry exactly one `DataPart` (object `data`, no other parts); the tool's
`resume_handler` gets `{"status": None, "payload": <data>}` (GH-193). A resume
with a `FilePart` is `-32005`; any other mixed or repeated shape is `-32602`; AG-UI rejects non-text user content parts
in the current turn (the user messages after the last assistant message) with
`RUN_ERROR` (maintainer ruling on GH-159).
User `content` must be a string or a list of `text` parts; any other shape (for
example a bare part object) is also rejected with `RUN_ERROR`, never stringified
into model input. New input is never silently dropped. Earlier history is not re-checked: a rejected
message the client keeps in its history does not lock the thread, and its non-text
parts are left out of the model input.

Supported output modes: `text`, `text/plain`, `application/json`, and
`application/a2ui+json` only for a request that opts in (app gate and header);
without the header, asking for only `application/a2ui+json` gets 415 / `-32005` and
the error's "supported:" list leaves it out. A resume checks its modes against the
opt-in captured when the task started: its own header is never read and it cannot
newly opt in to A2UI. A resume that sends `acceptedOutputModes` replaces the stored
modes; one without them keeps the stored value. `X-A2A-Extensions` is echoed with only the
activated subset (the A2UI extension URI).

A2UI surface lifetime is managed by the client. The SDK emits no `deleteSurface`
for a surface in the artifact or run that created it: each A2A artifact is
`[TextPart, DataPart(open)]`, and each AG-UI emission is `AGENT_ARTIFACT` then
one `A2UI_UPDATE`. Each artifact uses a fresh `surfaceId`; a caller-supplied `surface_id` must be unique per artifact. The agent-card param
`deleteSurfaceSemantics` was removed (GH-214, ruling
https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762).

**Concurrent-stream cap.** `POST /v1/message:stream`,
`GET`/`POST /v1/tasks/{id}:subscribe` and AG-UI's `POST /ag-ui/run` each hold an
indefinite `text/event-stream` on a single-process server, so they share one
admission budget: global, then per-identity
(`AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY`), then per-task subscribers. The
per-task layer applies wherever the request names an existing task —
`tasks/{id}:subscribe`, a `taskId`-bearing `message:stream`, and an
`/ag-ui/run` carrying `resume` — and every admitted stream on every one of
these routes registers its task id on the shared budget, so the count is
never split per transport. A request that mints its own task (a bare
`message:stream`, a fresh `/ag-ui/run`) is still admitted under the global and
per-identity layers; its per-task count is simply 0 by construction. At
capacity the server **rejects** with 429 + `Retry-After: 5` rather than
evicting a live stream — a shed request creates no task and never disturbs
another caller's stream. On `/v1/*` the body is the standard error envelope
(`-32000`); on `/ag-ui/run` it is the bare `{"detail": ...}` shape that
surface's other transport-level rejections (403/415/413) already use, and it
is returned *before* `RUN_STARTED`, so it is never a `RUN_ERROR` frame.
Clients should retry after the advertised delay rather than treating 429 as
fatal.

A severed stream **without** a `final: true` frame means re-subscribe via
`tasks/{id}:subscribe` — that is the documented recovery signal (A2A §5.3).

## AG-UI (`POST /ag-ui/run`, SSE)

Frame contract per run: `RUN_STARTED` always first (validation errors
arrive *inside* the stream), `STATE_SNAPSHOT` second, `STEP_STARTED`/
`STEP_FINISHED` per loop turn (`turn-N`), text triplets with a fresh
`messageId`, `TOOL_CALL_START/ARGS/END/RESULT`, and exactly one terminal
`RUN_FINISHED` | `RUN_ERROR`.

Custom events (also advertised on the card's `x-agui.customEvents`):

| `name` | `value` |
|---|---|
| `AGENT_ARTIFACT` | `{dataType, toolName, data}` |
| `A2UI_UPDATE` | `{messages: [...]}` — the A2UI sequence |
| `AGENT_PROGRESS` | `{message}` |
| `AGENT_NOTE` | `{note}` |
| `TOOL_PROGRESS` | `{message, toolName}` |

Interrupts end the run with `RUN_FINISHED` carrying
`outcome={type: "interrupt", interrupts: [{id, reason, message,
responseSchema, toolCallId}]}` (camelCase keys on the AG-UI wire). Resume
with a new run whose body has `resume=[{interruptId, status, payload}]`
(snake_case `interrupt_id` also accepted) — identity-bound.
`resume` holds exactly one entry. More than one entry, a `resume` that is
not a list, or an entry that is not an object ends the run with `RUN_ERROR`
`invalid resume entry` (code `validation`). A present `status` must be
`"resolved"` or `"cancelled"`; any other value gets the same `RUN_ERROR`,
before the interrupt is looked up. A missing or null `status` is delivered
as `None`. The error carries no entry content.

On AG-UI the action gate reads the canonical form: `status="resolved"` (or
`"cancelled"`) with the human decision in `payload.decision`
(`"approved"`/`"rejected"`). A decision word directly in `status` is not
accepted on AG-UI (the route rejects it with `invalid resume entry`). A2A
resume has no `status` field: the gate reads the reply text, or
`payload.decision` from one `DataPart` (delivered as `status: None`). Signals are merged REJECT-WINS (a contradictory pair always
denies); a `resolved` status with no `payload.decision` is UNCLEAR, which
default-denies without aborting the run.

`RUN_FINISHED` always carries `outcome`: `{type: "success"}` on a normal
finish, `{type: "interrupt", ...}` when paused. `RUN_ERROR` carries `code` — one
of the `ErrorCategory` values: `rate_limited`, `upstream`, `auth`, `timeout`,
`budget`, `internal` (from the failing `AgentError.category` or a fixed code),
`validation` (malformed body, invalid resume, no user message, non-text part)
and `not_found` (unknown, expired or no-longer-resumable interrupt). `code` is
never built from client input.

Inbound history is processed, not rejected: >50 messages or messages over
`AGENT_SDK_AGUI_MAX_MESSAGE_CHARS` (default 32000) keep head and tail with an omission marker, blank assistant turns are skipped, consecutive
same-role messages merge. Control characters are stripped, not rejected —
never `RUN_ERROR`.

## MCP (2025-11-25, 2025-06-18, 2025-03-26; Streamable HTTP at `/mcp`)

- Auth: OAuth 2.1 (Claude.ai connector flow) or API key; unauthenticated →
  401 with a `WWW-Authenticate` pointer to the protected-resource
  metadata. Discovery: both PRM variants + AS metadata, S256 PKCE only.
  A request with no bearer always gets that 401 (never 429) with the bare
  challenge `Bearer resource_metadata="..."`; an invalid, expired or refused
  bearer gets `Bearer error="invalid_token", resource_metadata="..."`. Failed
  bearers count in their own per-IP window and the `/oauth/*` endpoints in
  another; both are sized by `AGENT_SDK_UNAUTH_RATE_LIMIT`, so one cannot drain
  the other. `POST /oauth/revoke` with a bad bearer also counts in the
  failed-bearer window. When that window is spent, the 429 carries `Retry-After`
  and the same `Bearer error="invalid_token", resource_metadata="..."` challenge
  as the 401 (that surface's PRM URL), so a client knows to re-authenticate. An API `/oauth/*` 429 (`register`, `token`, `revoke`) is
  `{"error":"temporarily_unavailable","error_description":"rate limit exceeded"}`
  with `Retry-After` and `Cache-Control: no-store`; the four browser routes
  (`GET`/`POST /oauth/authorize`, `GET /oauth/idp/callback`,
  `POST /oauth/idp/consent`) answer 429 with the branded HTML error page.
  Token responses also carry `Pragma: no-cache`.
- Versions: `initialize` echoes the client's `protocolVersion` when it is
  2025-11-25, 2025-06-18 or 2025-03-26; any other value gets the newest
  (2025-11-25). `serverInfo.title` is sent only at 2025-11-25 (the title gate).
  After `initialize`, a present `MCP-Protocol-Version` on a request that carries
  an owned `Mcp-Session-Id` must equal the version that session negotiated, else
  400 `unsupported MCP-Protocol-Version` (GH-273). An absent header uses the
  session's version. An unknown or other-owner session id stays 404.
  Deviation (GH-266): a tool that declares `emits` (so it advertises
  `outputSchema`) but returns no value (None) answers `isError: false` with an
  empty text block and no `structuredContent`, although MCP 2025-06-18 says a
  tool with an `outputSchema` MUST return conforming `structuredContent`. This
  keeps parity with the A2A/AG-UI fold of a void result.
- `tools/list` exposes **Tier 1 tools only**; `emits` becomes
  `outputSchema` and results carry `structuredContent`.
- Setting `AGENT_SDK_MCP_SCHEMA_MODE=strict` flattens `tools/list` schemas (inlined `$defs`, `anyOf` with null collapsed at property positions only, so list items and dict values keep `null`; no `default: null`; a recursive model keeps its `$ref`/`$defs`; `null` is also dropped from an `anyOf` of three or more members at property positions, with the same required and keep-null rules as the two-member case, while top-level unions stay intact). It applies to `inputSchema` and `outputSchema`, including the `emits` tuple `anyOf`, and `tools/list` only. Default `standard` is unchanged.
- Skills (opt-in, GH-205): `Agent(mcp_skills="tool")` adds the read-only
  `load_skill` tool to `tools/list` / `tools/call`;
  `Agent(mcp_skills="prompts")` advertises `capabilities.prompts` and serves
  paginated `prompts/list` plus `prompts/get` (one user message holding the
  skill body). Both need `skills_dir`; `exclude_from_catalog` skills are
  hidden; `load_skill` is a reserved tool name. Default `None` changes
  nothing.
- `initialize.instructions` carries the credential note, then your own text
  from `Agent(mcp_instructions=...)` (persona agents) or
  `artifacts/mcp_instructions.md` (artifact agents; same variables as
  `system`). Max 4000 characters; setting both is a build error. Every MCP
  client model sees this text, so it must contain no secrets.
- Sessions via `Mcp-Session-Id`; CORS preflight is an exact-origin table.
  `GET /mcp` with an `Mcp-Session-Id` applies the same checks as `POST`: over
  64 characters → 400; unknown, expired or other-owner session → 404 (same
  static body for all three 404 cases). No header → 200 SSE, as before.
- `tools/call` for an unknown or Tier 2 tool returns JSON-RPC `-32602`
  (invalid params) with the fixed message `tool not found`; the requested
  name is never echoed. An unknown MCP *method* still returns `-32601`.
- **Body and ids (GH-246).** `POST /mcp` and `POST /mcp/messages` read the body with a size cap (2 MiB): a declared over-cap `Content-Length` is refused before any read, and a streamed body stops being read once it passes the cap; both answer 413. A request (any method not under `notifications/`) whose `id` is missing, null, or not a string or integer gets `-32600` with `id: null` before any handler runs. `/mcp/messages` also checks `Content-Type` (415), acks a JSON-RPC response with 202, and answers a full session queue with a JSON 503. The `Content-Type` compare ignores case. `tools/list` does not change with the negotiated version.
- **Nesting depth (GH-250).** Every JSON ingress parses with `loads_strict`, which refuses input nested deeper than 64 levels (arrays and objects counted together). The input is valid JSON, but the answer keeps the parse-error code with its own fixed text, `nesting too deep`, apart from the malformed-JSON text: `POST /mcp` and `POST /mcp/messages` answer `-32700` `nesting too deep` (the second one on the session's SSE channel, as for any parse error); `POST /v1/message:send` and `:stream` answer HTTP 400 with `-32700` `nesting too deep`; `POST /ag-ui/run` ends the run with `RUN_ERROR` `nesting too deep` (code `validation`). Malformed JSON keeps `parse error` (MCP), `request body is not valid JSON` (A2A) and `malformed RunAgentInput body` (AG-UI). The text never echoes the body. The JSON-RPC envelope uses about 3 levels, so MCP tool `arguments` have about 61 levels left.
- A `POST /mcp` body that is a JSON-RPC response (`id` plus `result` or
  `error`, no `method`) returns `202 Accepted` with an empty body, after the
  auth, origin and session checks. Requests still get `application/json`.
- **Concurrent-stream cap.** `GET /mcp` and the legacy `GET /mcp/sse` both
  hold an indefinite `text/event-stream` and share one admission budget —
  global, then per-identity (`AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY`). At
  capacity the server returns **429 + `Retry-After: 5`** instead of opening
  the stream, and never evicts an existing one. This is a deliberate
  deviation from the spec's two-outcome rule for `GET /mcp`
  (`text/event-stream` or 405): the server is single-process by design, so
  unbounded open streams degrade every tenant. Because an org-wide OAuth
  client collapses a whole organization onto one identity, the per-identity
  default is sized in the low hundreds and is operator-raisable — a 429 on
  this path surfaces in Claude.ai as *"Couldn't connect"*, so it must stay a
  genuine overload signal, never routine.

## Agent card

`/.well-known/agent-card.json` (ETag + 304; `agent.json` is a
byte-identical alias): `protocolVersion: "0.3.0"`, HTTP+JSON transport,
`capabilities.extensions` = the A2UI extension with `supportedCatalogIds` (left off the card when no registered tool emits an A2UI type, GH-249; GH-257: that one decision is `app.state.a2ui_enabled`, computed once in `build_app()`, and it also drives the accepted output modes, the header and `forwardedProps` opt-in, and artifact building: with A2UI off, `application/a2ui+json` alone gets -32005, a header opt-in or `forwardedProps.a2uiClientCapabilities` is ignored, and results use the TextPart/JSON fallback),
`x-sdk` per-skill metadata (tier, schemas, emits), and the `x-agui` block
(transport, endpoint, customEvents). All URLs derive from `PUBLIC_URL`.

A2A clients must list a domain catalog in `a2uiClientCapabilities.catalogs` to receive its surfaces (GH-180). Upstream A2UI v0.9.1's `{"v0.9": {"supportedCatalogIds": [...]}}` shape (client_capabilities.json) is accepted too when `catalogs` is absent or unusable, then a flat root `supportedCatalogIds` as a lenient fallback; `catalogs` wins when present (GH-213). On A2A a present `catalogs` list, even an empty one, is final: it is not passed over for the upstream keys, and it must include `urn:a2ui-profile:standard:v1` for Standard Profile cards (GH-240). Without it the artifact carries the TextPart plus a plain model-dump DataPart.
