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
| `POST /v1/tasks/{id}:subscribe` | re-attach SSE |
| `GET /v1/tasks` | 200; identity-scoped paginated list — query params `pageSize` (1–100, default 50) and `pageToken`; response `{tasks, totalSize, pageSize, nextPageToken}` |

Error table (body `{"error": {code, message}}`): unknown/foreign task →
404 `-32001`; terminal-task cancel → 409 `-32002`; terminal-task resume
(`message:send` or `message:stream` with `taskId`) → 501 `-32004`; push
config → `-32003`: `POST`/`GET /v1/tasks/{id}/pushNotificationConfigs` and
`GET`/`DELETE /v1/tasks/{id}/pushNotificationConfigs/{configId}` all return 501
`-32003` (identity required; same reply for known, foreign and unknown tasks;
body never read); unacceptable
`acceptedOutputModes` → `-32005`; missing `messageId` → 400 `-32602`;
too many concurrent streams → 429 `-32000` + `Retry-After` (see below). Task
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

Supported output modes: `text`, `text/plain`, `application/json`,
`application/a2ui+json`. `X-A2A-Extensions` is echoed with only the
activated subset (the A2UI extension URI).

A2UI surface lifetime is managed by the client. The SDK emits no `deleteSurface`
for a surface in the artifact or run that created it: each A2A artifact is
`[TextPart, DataPart(open)]`, and each AG-UI emission is `AGENT_ARTIFACT` then
one `A2UI_UPDATE`. Each artifact uses a fresh `surfaceId`; a caller-supplied `surface_id` must be unique per artifact. The agent-card param
`deleteSurfaceSemantics` was removed (GH-214, ruling
https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762).

**Concurrent-stream cap.** `POST /v1/message:stream`,
`POST /v1/tasks/{id}:subscribe` and AG-UI's `POST /ag-ui/run` each hold an
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

`status` accepts two conventions, both processed by the action gate:
- **Canonical AG-UI** — `status="resolved"` (or `"cancelled"`) with the human
  decision in `payload.decision` (`"approved"`/`"rejected"`).
- **SDK shorthand** — the domain word directly in `status`
  (e.g. `status="approved"`/`"rejected"`), `payload` optional.

The two are merged REJECT-WINS (a contradictory pair always denies); an
unrecognized `status` with no `payload.decision` is UNCLEAR → default-deny,
without aborting the run.

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

## MCP (2025-06-18, Streamable HTTP at `/mcp`)

- Auth: OAuth 2.1 (Claude.ai connector flow) or API key; unauthenticated →
  401 with a `WWW-Authenticate` pointer to the protected-resource
  metadata. Discovery: both PRM variants + AS metadata, S256 PKCE only.
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
`capabilities.extensions` = the A2UI extension with `supportedCatalogIds`,
`x-sdk` per-skill metadata (tier, schemas, emits), and the `x-agui` block
(transport, endpoint, customEvents). All URLs derive from `PUBLIC_URL`.

A2A clients must list a domain catalog in `a2uiClientCapabilities.catalogs` to receive its surfaces (GH-180). Upstream A2UI v0.9.1's `{"v0.9": {"supportedCatalogIds": [...]}}` shape (client_capabilities.json) is accepted too when `catalogs` is absent or unusable, then a flat root `supportedCatalogIds` as a lenient fallback; `catalogs` wins when present (GH-213). On A2A a present `catalogs` list, even an empty one, is final: it is not passed over for the upstream keys, and it must include `urn:a2ui-profile:standard:v1` for Standard Profile cards (GH-240). Without it the artifact carries the TextPart plus a plain model-dump DataPart.
