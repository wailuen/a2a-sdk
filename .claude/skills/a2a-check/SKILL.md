---
name: a2a-check
description: "Audit an A2A project for protocol v0.3.0 conformance in BOTH roles — server/provider (agent card, transports/methods, Task/Message/Part/Artifact shapes, streaming + final, error codes, auth) AND consumer/client (card discovery, transport selection, request construction, result + Part consumption, streaming consumption, interrupt resume, extension activation incl. A2UI-over-A2A, client auth). Detects the project's role(s) and audits each. Static code audit + optional live probes across the field-hardened conformance traps (dual-part artifacts, kind-not-type, FilePart XOR, final-event tail). Portable, project-agnostic. Use when the user wants to verify/debug whether an A2A server or client conforms to v0.3.0, or before claiming A2A compliance."
---

# /a2a-check — A2A v0.3.0 conformance audit

Runs a systematic audit of an A2A agent against the **A2A protocol v0.3.0** spec + the
field-hardened conformance traps. **Portable / project-agnostic** — discover the agent, don't
assume its name, language, layout, or transport binding.

This skill is the **mechanical audit**; the **`a2a-advisor` agent** is the deep-reasoning
expert (design questions, "how should I shape this up to full A2A", remediation strategy). Run
this for a repeatable pass/fail sweep; dispatch `a2a-advisor` for judgment calls. Both read the
same kit: `.claude/reference/a2a-protocol-0_3_0.md` (§1–§7) and, for exhaustive field detail,
the live spec at `a2a-protocol.org/v0.3.0` + the JSON Schema `a2a.json` at the `v0.3.0` tag of
`github.com/a2aproject/A2A`.

**Scope is v0.3.0.** Treat any v1.0-only shape as non-conformant for 0.3.0: snake/SCREAMING
enums (`TASK_STATE_*`, `ROLE_USER`), `supportedInterfaces[]`, a `TaskStatusUpdateEvent` without
`final`, `mediaType` (vs `mimeType`), removed `kind` discriminators.

## Usage

```
/a2a-check [--live <base-url>] [--tck] [--server|--client|--all]
```
- no flag → static code audit only (read source, run tests); **role auto-detected** (server / consumer / both)
- `--live <url>` → also probe the running agent with curl (+ JSON-Schema-validate the card) — server role
- `--tck` → also run the A2A TCK gating suite against the running agent — server role
- `--server` / `--client` / `--all` → **filter** which role(s) to audit; detection still determines what actually exists, so a role you ask for but the code doesn't have is **skipped with a warning** (never failed). `--client` aliases `--consumer`.

## Step 0 — Discover (never assume)

**First, detect the project's A2A role(s)** — and report it up front:
- **server** — serves an agent card + a task/RPC surface (→ audit D1–D6).
- **consumer** — calls *other* A2A agents: an A2A client/SDK, outbound `message/send`·`message/stream`, agent-card fetching, `X-A2A-Extensions` request headers (→ audit D7).
- **both** — score both sets. A genuinely-absent role's dimensions are **N/A**, never failures.
Honor `--server`/`--client`/`--all` as a **filter** over detection: a role you request but the code lacks is **skipped with a warning**, not failed; detection alone determines what exists.

Locate, by search not by hardcoded path: **(server)** the **agent-card route** (`/.well-known/agent-card.json`
and/or legacy `agent.json`); the **task/RPC surface** (JSON-RPC 2.0 / gRPC / HTTP+JSON REST) and
its method handlers; the **A2A object models** (`Task`/`Message`/`Part`/`Artifact`/events); the
**auth** layer. **(consumer)** the **A2A client** call sites (outbound calls, card discovery,
transport selection, credential injection, extension activation). Note the **declared
`protocolVersion`** and **`preferredTransport`**, and which transport the `url` actually serves.
Typical homes: `src/routes/`, `src/models/` (server); `src/clients/` / agent-runtime call sites
(consumer) — verify.

## What this checks  (dimensions D1–D7; cite `a2a-protocol-0_3_0.md §`)

### D1 — Discovery & Agent Card  (`§1`)
| Check | Pass condition |
|---|---|
| Served at **`/.well-known/agent-card.json`**, unauthenticated (`agent.json` alone = v0.2.x) | rename is breaking in 0.3.0 |
| Required fields present | `protocolVersion:"0.3.0"`, `name`, `description`, `version`, `url`, `capabilities`, `defaultInputModes`, `defaultOutputModes`, `skills` |
| `capabilities` is typed `AgentCapabilities` | ONLY `streaming`/`pushNotifications`/`stateTransitionHistory`/`extensions` — no foreign keys |
| Every `AgentSkill` has `id`, `name`, `description`, **`tags`** | `tags` is required — common miss |
| `preferredTransport` ∈ {`JSONRPC`,`GRPC`,`HTTP+JSON`} (exact casing, note the `+`) and **matches the transport served at `url`** | functionally REQUIRED (§5.6.1 prose) — flag absence HIGH |
| `securitySchemes` valid OpenAPI variants; `oauth2` uses `flows` not `openIdConnectUrl`; no secrets in card | |
| `AgentProvider`/`AgentInterface` (if present) carry BOTH required sub-fields | partial object = finding |

### D2 — Transports & Methods  (`§2`)
| Check | Pass condition |
|---|---|
| **Declared == served** (the #1 ported-agent gap) | card's transport claims match the actual routes/methods |
| Core methods present with correct params→result | **`message/send` + `tasks/get` + `tasks/cancel`** (all hard MUSTs) |
| Conditional methods | `message/stream`+`tasks/resubscribe` iff `capabilities.streaming`; `tasks/pushNotificationConfig/*` iff `pushNotifications`; `agent/getAuthenticatedExtendedCard` iff `supportsAuthenticatedExtendedCard` |
| **`tasks/cancel` present** | hard MUST (§11.1.2) — flag MISSING (Critical) if absent |
| `message/send` handles **both `Task` and `Message`** return types | server may return a direct `Message` |
| Error code→method mapping | `-32001` TaskNotFound, `-32002` TaskNotCancelable, `-32003` PushNotSupported, `-32004` UnsupportedOperation, `-32005` ContentTypeNotSupported, `-32006` InvalidAgentResponse, `-32007` ExtendedCardNotConfigured |
| A2A error codes, **not bare HTTP 500 / framework defaults** | all errors use the canonical envelope + JSON-RPC codes (`-32700/-32600/-32601/-32602/-32603`) — never a framework's default error shape (e.g. FastAPI `{"detail":...}`) |
| REST HTTP mapping (if REST) | 400/401(+`WWW-Authenticate`)/403/404/409/415/500/501/502 per reference §2 |

### D3 — Core objects & lifecycle  (`§3`)
| Check | Pass condition |
|---|---|
| Object shapes | **Task**`{id,contextId,status,kind:"task"}` · **Artifact**`{artifactId(not id),parts}` · **Message**`{role,parts,messageId,kind:"message"}` |
| Wire is **camelCase** | `taskId`/`contextId`/`artifactId`, not `task_id` |
| **Part discriminator is `kind` not `type`** | 3 variants: `TextPart{kind:"text",text}` · `FilePart{kind:"file",file}` · `DataPart{kind:"data",data}`. Flag any `"type":"data"` |
| `TaskState` exact values, American `"canceled"` | `submitted`,`working`,`input-required`,`auth-required`,`completed`,`canceled`,`failed`,`rejected`,`unknown` |
| Server-emitted `Message`/`Task` carry `contextId` | server-emitted REQUIRED; client-sent OPT |
| Terminal-task re-message | sending to a terminal task MUST error, not silently start a new task |

### D4 — Streaming  (`§4`)
| Check | Pass condition |
|---|---|
| SSE `Content-Type: text/event-stream` | JSON-RPC wraps each event in `SendStreamingMessageResponse`; REST sends bare events |
| **First event = full `Task` snapshot** | not a status event |
| Updates carry `taskId`+`contextId`+`kind` | `TaskStatusUpdateEvent`/`TaskArtifactUpdateEvent` |
| **`final:true` terminates; nothing after it** | check the stream tail — no events after `final:true` |
| Artifact chunking | `append`/`lastChunk` keyed by stable `artifactId`; absence ≠ false |

### D5 — Security & auth  (`§5`)
HTTPS in prod; identity at the HTTP layer (`Authorization`), not in payloads; `401`+`WWW-Authenticate`/`403`; card endpoint unauthenticated, data endpoints authenticated. No `allow_origins=["*"]` on an app mounting auth-bearing routes (drive from a validated config field). Push (if advertised): gated by `capabilities.pushNotifications`, `X-A2A-Notification-Token` on delivery, JWT/JWKS + replay protection, **SSRF allowlist on webhook URLs**. `PushNotificationConfig` CRUD all four methods need the capability; `delete`→`null`.

### D6 — Conformance, versioning & extensions  (`§6`)
Hard-MUST table satisfied; `protocolVersion` correct. **Enhanced / custom content types or render
hints MUST be declared as an `AgentExtension`** (`capabilities.extensions[]` with its own `uri`,
negotiated via `X-A2A-Extensions`) — not smuggled into `x-` keys or tool payloads — and their
structured data rides in a spec `DataPart` with the render hint in `metadata`.

### D7 — Consumer / client-side (§11.2)  (`§7`) — **the consumer-role dimension; audit whenever the project ships an A2A client**
First-class, same rigor as D1–D6 (for a consumer-only project this is the primary audit; D1–D6 → N/A). All items grounded in A2A v0.3.0 §11.2 / §5.6.3 / §4.3 / extensions topic.

**Consumer hard-MUST floor (§11.2 — the compliance gate):** (a) parse the `AgentCard` + select a transport per §5.6.3 (§11.2.1); (b) construct valid `message/send` + `tasks/get` requests (§11.2.2); (c) handle all A2A error codes (§11.2.2→§8.2); (d) support ≥1 auth method when required (§11.2.2). **Streaming (D7.9), push (D7.13), and the extended card (D7.12) are OPTIONAL for clients (§11.2.3 MAY)** — audit only if implemented; they do not gate the consumer verdict.

| Check | Pass condition |
|---|---|
| **D7.1 Card discovery & caching** | Fetches the target's `AgentCard` (`/.well-known/agent-card.json`, legacy `agent.json` fallback); SHOULD JSON-Schema-validate + cache. **MUST NOT hardcode an endpoint/transport that bypasses card discovery** (#1 consumer gap) |
| **D7.2 Transport selection & fallback (§5.6.3)** | Prefer `preferredTransport`/`url`; fall back to `additionalInterfaces`; MUST use the correct URL for the selected transport; SHOULD fall back if preferred fails |
| **D7.3 Request construction** | Valid `MessageSendParams`: `message{kind:"message",role:"user",parts(kind-discriminated),messageId}`. Client emitting `"type"` not `"kind"`, or omitting `messageId`, is itself non-conformant; outbound `FilePart.file` honors `bytes` XOR `uri` |
| **D7.4 contextId association** | Supplies prior `contextId` to continue a context; omits to start fresh |
| **D7.5 Result handling** | **Handles BOTH `Task` and `Message`** as `message/send` results — not `Task`-only |
| **D7.6 Part consumption** | Handles all 3 inbound Part kinds; `FilePart.file` read as `bytes` XOR `uri`; structured `DataPart` render hint read from `metadata` not `data`; unknown kinds degrade, don't crash |
| **D7.7 Credentials (§4.3)** | Credentials in HTTP headers (`Authorization`/`X-API-Key`) per the card's `securitySchemes`/`security`, **never in the JSON-RPC payload**; SHOULD re-auth on `401` |
| **D7.8 Interrupt resume** | `input-required`/`auth-required` → follow-up reuses the SAME `taskId`+`contextId`; MUST NOT send to a terminal task |
| **D7.9 Streaming consumption** *(OPTIONAL — §11.2.3 MAY; only if it consumes `message/stream`)* | First event is *typically* the full `Task` snapshot (no normative ordering MUST — handle any `SendStreamingMessageResponse`); SHOULD stop consuming on `final:true` (server closes the SSE after it); SHOULD `tasks/resubscribe` to reconnect (**server MAY NOT backfill**); MAY `tasks/get` after for final state |
| **D7.10 Errors** | Handles all A2A codes (§11.2.2 client MUST; codes enumerated in §8.2) + standard JSON-RPC codes; surfaces `401`/`403`; transport/`5xx` failures handled distinctly from protocol errors |
| **D7.11 Extension activation** | Lists URIs in **`X-A2A-Extensions`** request header; reads the response header (same name) for activated URIs (server echo is a SHOULD — confirm on presence, don't hard-fail on absence alone); relies on an extension only when activated. **A2UI-over-A2A seam:** to render A2UI the client activates `https://a2ui.org/a2a-extension/a2ui/v0.9.1` AND dispatches inbound parts on `metadata.mimeType=="application/a2ui+json"` (`data` = array of A2UI messages; render/extract per `a2ui-advisor`) |
| **D7.12 Authenticated extended card** *(OPTIONAL — §11.2.3 MAY)* | After auth, SHOULD replace the cached public card with `agent/getAuthenticatedExtendedCard` for the session |
| **D7.13 Push webhook** *(OPTIONAL — §11.2.3 MAY; only if the client registers a `PushNotificationConfig`)* | Its webhook validates `X-A2A-Notification-Token`; registered URL is a real endpoint it controls; SHOULD verify JWT/JWKS + replay protection |

## Field-hardened conformance traps (the expensive-to-find ones)
- **Dual-part structured artifacts** — a chart/table/KPI artifact MUST carry a
  `DataPart{kind:"data",data:{...}}` alongside any `TextPart` fallback. Text-only for a
  structured result is non-conformant. Enforce as a model invariant, not a convention.
- **Payload-channel exclusivity** — a part carries exactly one payload matched to its type
  (`text` for text, `data` for data); reject both-set or neither-set. **`FilePart.file` XOR**:
  exactly one of `bytes`/`uri`, the other absent.
- **`final` tail** — `TaskStatusUpdateEvent.final` is REQUIRED (TS non-optional even though the
  JSON Schema omits it from `required[]`); MUST reach `true`, and **no event may follow it**.
- **Failed tasks carry a reason** — a `failed` status must be accompanied by caller-visible
  error info; a bare `failed` with no message/category is a contract gap.
- **Constrained content-type values** — Enhanced render-hint/content-type values come from a
  single source-of-truth enum/Literal, not free strings (typos surface only at render time).
- *(project-specific note: bunkerwire's `error_category`, `ContentTypeName` Literal, and
  canonical `to_wire_dict()` envelope are that project's expression of the last three — adapt
  to the audited project's models.)*

Consumer-role traps (score under D7):
- **Hardcoded endpoint bypassing the card** — client POSTs to a fixed URL/transport, never fetches/parses the `AgentCard` (no transport selection, no extension discovery).
- **`Task`-only result handling** — breaks on a synchronous `Message` return from `message/send`.
- **Credentials in the JSON-RPC payload** instead of HTTP headers.
- **Using an extension without activating it** — never sends `X-A2A-Extensions` or ignores the activated-URIs response header; for A2UI consumption, doesn't dispatch on `metadata.mimeType=="application/a2ui+json"`.
- **Streaming consumer (if it consumes `message/stream` at all) not stopping on `final:true`**, or assuming the server backfills missed events on resubscribe. (Streaming is an OPTIONAL client feature — §11.2.3 MAY; this trap applies only when streaming is implemented.)
- **New task on resume** — fresh/no `taskId` instead of reusing `taskId`+`contextId` for `input-required`/`auth-required`.

## Layer — Live probes (`--live <url>`)
```bash
BASE="<url from args>"

# 1. Agent card — served, unauthenticated, v0.3.0 path
curl -sf "$BASE/.well-known/agent-card.json" | python3 -m json.tool
#    → assert protocolVersion "0.3.0", preferredTransport set & matching url, skills[].tags present

# 2. JSON-Schema-validate the card against a2a.json @ v0.3.0 (fetch the schema, validate)

# 3. message/send (JSON-RPC binding example) — handles Task OR Message
curl -sf -X POST "$BASE" -H "Content-Type: application/json" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"kind":"message","role":"user","parts":[{"kind":"text","text":"ping"}],"messageId":"<uuid>"}}}'
#    REST binding instead: POST /v1/message:send ; poll GET /v1/tasks/{id} ; cancel POST /v1/tasks/{id}:cancel

# 4. Drive lifecycle: message/send → tasks/get until terminal; assert Task{kind,id,contextId,status}
# 5. Stream: message/stream (or POST /v1/message:stream) — first event full Task, final:true at tail, nothing after
# 6. tasks/cancel present and returns correct code on a terminal task (-32002 TaskNotCancelable)
# 7. Unauthenticated data endpoint → 401 + WWW-Authenticate; card endpoint stays unauthenticated
```

## Layer — TCK & Inspector (`--tck`, always recommend before claiming compliance)
```bash
# A2A TCK — gating MUST suite (fetches {host}/.well-known/agent-card.json)
./run_tck.py --sut-host <URL> --level must     # a2aproject/a2a-tck
# A2A Inspector — live response validation                a2aproject/a2a-inspector
# Typed clients for round-trip drift: a2a-python / a2a-js
```

## Steps
1. Step 0 discovery — **detect role(s)** (server/consumer/both), card route, transport binding, models, client call sites, declared version; apply any `--server`/`--client`/`--all` filter.
2. Run **D1–D6 for the server role and D7 for the consumer role** against the code with `file:line` evidence (mark the absent role's dimensions N/A); PASS / PARTIAL / MISSING per item. An item you can't positively confirm is a **finding, not a pass** (fail closed).
3. If `--live` / `--tck`, run the probes + JSON-Schema-validate the card + drive the lifecycle, and fold results in.
4. For each finding: state the spec basis (`§`/spec URL) and the fix @ file:line.
5. For design-level or ambiguous findings, **dispatch the `a2a-advisor` agent** rather than guessing.
6. If a new generalizable conformance trap surfaces, note it for the kit (`.claude/reference/a2a-protocol-0_3_0.md`).

## Report format
```
## A2A v0.3.0 Conformance Audit — <date>
Role(s): <server | consumer | both>   Transport: <JSONRPC | GRPC | HTTP+JSON>   Declared protocolVersion: <...>   Mode: <static|live|tck>

— Server role (D1–D6) —  [N/A if consumer-only]
D1 Agent Card:        [PASS] ...   [MISSING] ... (spec basis → fix @ file:line)
D2 Transports/Methods: ...
D3 Objects/Lifecycle:  ...
D4 Streaming:          ...
D5 Security/Auth:      ...
D6 Versioning/Extensions: ...
Field traps:           [PARTIAL] dual-part artifact only emits TextPart @ ...

— Consumer role (D7) —  [N/A if server-only]
D7 Client:            [PASS] D7.1 card discovery ... [MISSING] D7.11 A2UI ext not activated @ ...

Findings: Critical → High → Medium → Low
Verdict (per audited role): server v0.3.0-compliant? <yes/no/N-A> (D1–D6 hard-MUST gate) · consumer v0.3.0-compliant? <yes/no/N-A> (§11.2 hard-MUST floor: parse-card+transport-selection, message/send+tasks/get, A2A error codes, ≥1 auth — streaming/push/extended-card OPTIONAL, non-gating)
Remediation (cheapest-unblock-first):
  server: card well-known path → object shapes/camelCase → declared-vs-served transport/methods → streaming first-event + final → error codes → Enhanced-types-as-extension → optional push/extended-card
  consumer: card discovery → request construction/kind → both-result handling → credentials-in-headers → streaming final + resubscribe → interrupt resume → extension activation
Next action: <or "dispatch a2a-advisor for X">
```
