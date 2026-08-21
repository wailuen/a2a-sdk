# Protocol surfaces

One task runner serves every protocol: a single worker per task folds loop
events into the canonical A2A `Task` and publishes dual-form stream items
(pre-built A2A frame + raw event for the AG-UI mapper). Interrupts resume
identically across protocols.

## A2A v0.3.0 (HTTP+JSON)

| Endpoint | Behavior |
|---|---|
| `POST /v1/message:send` | 200 + Task snapshot (non-blocking); resume by including `taskId` |
| `POST /v1/message:stream` | SSE; first frame is the **full Task**, then status/artifact frames until `final: true` |
| `GET /v1/tasks/{id}` | Task; `historyLength` truncates (0 → `[]`) |
| `POST /v1/tasks/{id}:cancel` | 200 + canceled Task; 404/409 per table |
| `POST /v1/tasks/{id}:subscribe` | re-attach SSE |
| `GET /v1/tasks` | 200; identity-scoped paginated list — query params `pageSize` (1–100, default 50) and `pageToken`; response `{tasks, totalSize, pageSize, nextPageToken}` |

Error table (body `{"error": {code, message}}`): unknown/foreign task →
404 `-32001`; terminal-task cancel → 409 `-32002`; terminal-task resume
(`message:send` or `message:stream` with `taskId`) → 501 `-32004`; push
config → `-32003`; `blocking: true` → `-32004`; unacceptable
`acceptedOutputModes` → `-32005`; missing `messageId` → 400 `-32602`;
too many concurrent streams → 429 `-32000` + `Retry-After` (see below). Task
access is
**identity-bound**: someone else's task id returns 404 `-32001` —
existence is never leaked (admin keys bypass).

Supported output modes: `text`, `text/plain`, `application/json`,
`application/a2ui+json`. `X-A2A-Extensions` is echoed with only the
activated subset (the A2UI extension URI).

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

Inbound history is processed, not rejected: >50 messages or >4000-char
messages truncate, blank assistant turns are skipped, consecutive
same-role messages merge. Control characters are stripped, not rejected —
never `RUN_ERROR`.

## MCP (2025-06-18, Streamable HTTP at `/mcp`)

- Auth: OAuth 2.1 (Claude.ai connector flow) or API key; unauthenticated →
  401 with a `WWW-Authenticate` pointer to the protected-resource
  metadata. Discovery: both PRM variants + AS metadata, S256 PKCE only.
- `tools/list` exposes **Tier 1 tools only**; `emits` becomes
  `outputSchema` and results carry `structuredContent`.
- Sessions via `Mcp-Session-Id`; CORS preflight is an exact-origin table.
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
`capabilities.extensions` = the A2UI extension with `catalogIds`,
`x-sdk` per-skill metadata (tier, schemas, emits), and the `x-agui` block
(transport, endpoint, customEvents). All URLs derive from `PUBLIC_URL`.
