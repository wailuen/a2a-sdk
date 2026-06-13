---
name: ag-ui-check
description: "Audit an AG-UI implementation for protocol conformance. Static code audit + optional live SSE probes across the event catalog (34 types), RunAgentInput schema, SSE transport + camelCase wire, event ordering, terminal event coverage, CUSTOM event spec, GenUI mode wiring, and the field-hardened conformance traps. Portable, project-agnostic. Use when the user wants to verify/debug whether an AG-UI server or client conforms to the protocol, or before claiming AG-UI compliance."
---

# /ag-ui-check — AG-UI protocol conformance audit

Systematic audit of an AG-UI implementation against the **AG-UI protocol** spec.
**Portable / project-agnostic** — discover the agent, don't assume its name, language, layout, or transport binding.

This skill is the **mechanical audit**; the **`ag-ui-advisor` agent** is the deep-reasoning expert (design questions, remediation strategy, GenUI mode selection). Run this for a repeatable pass/fail sweep; dispatch `ag-ui-advisor` for judgment calls.

Source of truth: `github.com/ag-ui-protocol/ag-ui` (events.py, types.py, encoder.py) and `docs.ag-ui.com`.
Python package: `ag-ui-protocol` v0.1.18 (PyPI). Pre-v1.0 — breaking changes announced.

## Usage

```
/ag-ui-check [--live <base-url>] [--client]
```
- no flag → static code audit only
- `--live <url>` → also probe the running server with curl
- `--client` → also audit the frontend SSE consumer

## Step 0 — Discover (never assume)

Locate by search, not hardcoded paths: the **SSE endpoint** (any path — commonly `POST /ag-ui/run` or `POST /`); the **event emitter** (look for `EventType`, `RunStartedEvent`, `encoder.encode`, `ag_ui.core`); the **frontend consumer** (look for `EventType` string checks, `data:` line parsing, CUSTOM event routing); the **auth layer**; and whether a **GenUI mode** is wired (Static = tool-call components, Declarative = A2UI CUSTOM events, Open-ended = MCP Apps iframes).

## What this checks

### C1 — Transport & serialization

| Check | Pass condition |
|---|---|
| Endpoint responds with `Content-Type: text/event-stream` | Required |
| Each SSE line is `data: <JSON>\n\n` (no `event:` or `id:` lines) | Default AG-UI encoder format |
| All field names on the wire are **camelCase** | `messageId` not `message_id`, `threadId` not `thread_id`, `toolCallId` not `tool_call_id` |
| Serialization uses `model_dump_json(by_alias=True, exclude_none=True)` | Raw `model_dump()` emits snake_case — silent client failure |
| `RunAgentInput` deserialized with camelCase aliases | `model_validate()` with `populate_by_name=True` or `alias_generator=to_camel` |
| Client sends `Content-Type: application/json`, `Accept: text/event-stream` | Required request headers |

### C2 — Event ordering & completeness

| Check | Pass condition |
|---|---|
| **`RUN_STARTED` is the first event** | Before any text/tool/step event |
| **Every code path terminates with `RUN_FINISHED` or `RUN_ERROR`** | Including exception paths; no path exits the generator silently |
| No events emitted after `RUN_FINISHED` or `RUN_ERROR` | Both are terminal |
| `TEXT_MESSAGE_START` before `TEXT_MESSAGE_CONTENT` before `TEXT_MESSAGE_END` | Same `message_id` in all three |
| `TEXT_MESSAGE_CONTENT.delta` is never empty string | Pydantic validator rejects empty; filter LLM token stream |
| `TOOL_CALL_START` before `TOOL_CALL_ARGS` before `TOOL_CALL_END` | Same `tool_call_id` throughout |
| `TOOL_CALL_END` always emitted after `TOOL_CALL_START` | Even when args are not streamed |
| `STEP_STARTED`/`STEP_FINISHED` are paired | Every START has a matching FINISHED with the same `step_name` |
| `STATE_DELTA` only after a `STATE_SNAPSHOT` in the same run | RFC 6902 patches against undefined state |

### C3 — Required fields

| Event | Required fields (wire names) | Common miss |
|---|---|---|
| `RUN_STARTED` | `threadId`, `runId` | Sending empty string |
| `RUN_FINISHED` | `threadId`, `runId` | Forgotten on early-exit path |
| `RUN_ERROR` | `message` | Using `RunFinishedEvent` for errors |
| `TEXT_MESSAGE_START` | `messageId`, `role` | `role` must be a valid value |
| `TEXT_MESSAGE_CONTENT` | `messageId`, `delta` | Empty `delta` |
| `TEXT_MESSAGE_END` | `messageId` | Mismatched `messageId` |
| `TOOL_CALL_START` | `toolCallId`, `toolCallName` | Missing `parentMessageId` |
| `TOOL_CALL_ARGS` | `toolCallId`, `delta` | |
| `TOOL_CALL_END` | `toolCallId` | |
| `TOOL_CALL_RESULT` | `messageId`, `toolCallId`, `content` | |
| `STEP_STARTED` | `stepName` | |
| `STEP_FINISHED` | `stepName` | |
| `CUSTOM` | `name`, `value` | Missing `name` — makes routing impossible |

### C4 — Conformance traps (the expensive ones)

- **Empty `delta`** — `TEXT_MESSAGE_CONTENT.delta` and `TOOL_CALL_ARGS.delta` must be non-empty. LLM streams can produce empty chunks; filter before emitting.
- **Mismatched `message_id`** across START/CONTENT/END — creates dangling messages client-side.
- **`THINKING_*` used instead of `REASONING_*`** — deprecated, removed in v1.0.0. Any `THINKING_TEXT_MESSAGE_*` or `THINKING_START/END` in new code is a finding.
- **snake_case on the wire** — using `model_dump()` without `by_alias=True` emits snake_case; frontend parsers fail silently. Check all serialization sites.
- **`CUSTOM` event `name` undocumented** — frontend consumers need to know what names to expect. Undocumented names are silently dropped. Agent should document (in the agent card or README) what CUSTOM names it emits and their `value` schema.
- **Unbounded SSE queue** — if fan-out is used (`asyncio.Queue`), queues must be `asyncio.Queue(maxsize=N)` with sentinel overflow eviction. `grep "asyncio.Queue()" src/routes/` must return zero hits (only `asyncio.Queue(maxsize=N)` allowed).
- **`STATE_DELTA` without prior snapshot** — clients cannot apply RFC 6902 patches to undefined state.
- **Missing `parent_message_id` on tool calls** — tools emitted without linking to an assistant message lose context in the UI.
- **Interrupt flow incomplete** — `RUN_FINISHED` with `outcome.type="interrupt"` must carry non-empty `interrupts[]`; client must send `resume[]` in the next `RunAgentInput`.

### C5 — GenUI mode wiring (if applicable)

| Mode | Check |
|---|---|
| **Static** | Tool call names in `TOOL_CALL_START.tool_call_name` match frontend-registered component names |
| **Declarative (A2UI)** | `CUSTOM` events with `name="A2UI_UPDATE"` carry valid A2UI JSON in `value`; A2UI version field present; frontend routes by `name` |
| **Open-ended (MCP Apps)** | Iframe sandboxing + CSP in place; `CUSTOM` event references MCP App URI |

### C6 — Client consumer (if `--client`)

| Check | Pass condition |
|---|---|
| SSE `data:` lines parsed correctly | `line.startsWith("data:")` → `JSON.parse(line.slice(5))` |
| All 34 event types handled or explicitly ignored | Missing handlers are silent drops |
| `RUN_ERROR` shows error state (not silent) | |
| Reconnect/retry on disconnect | Optional but recommended |
| `CUSTOM` events routed by `name` | Consumers switch on `event.name` |
| `message_id` correlation correct | Same ID across START/CONTENT/END; fresh UUID per message |

## Live probes (`--live <url>`)

```bash
BASE="<url from args>"
AUTH="Authorization: Bearer <key>"

# 1. Basic run — inspect SSE stream
curl -N -X POST "$BASE/ag-ui/run" \
  -H "Content-Type: application/json" \
  -H "Accept: text/event-stream" \
  -H "$AUTH" \
  -d '{"threadId":"t1","runId":"r1","state":{},"messages":[],"tools":[],"context":[],"forwardedProps":{}}'
# Assert: first line type=RUN_STARTED, last line type=RUN_FINISHED or RUN_ERROR
# Assert: all field names camelCase

# 2. Unauthenticated request → 401
curl -s -o /dev/null -w "%{http_code}" -X POST "$BASE/ag-ui/run" \
  -H "Content-Type: application/json" \
  -d '{"threadId":"t1","runId":"r1","state":{},"messages":[],"tools":[],"context":[],"forwardedProps":{}}'
# Assert: 401

# 3. Empty delta (send a query that triggers a zero-length token) — assert no empty CONTENT event

# 4. Exception path — send malformed input that triggers an error
# Assert: stream emits RUN_ERROR (not a bare exception / empty stream)
```

## Steps

1. Step 0 discovery — endpoint, emitter, consumer, auth, GenUI mode.
2. C1–C6 against the code with `file:line` evidence; mark PASS / PARTIAL / MISSING. An item you can't positively confirm is a **finding, not a pass** (fail closed).
3. If `--live`, run the probes and fold results in.
4. For each finding: state the spec basis and the fix @ file:line.
5. For design-level findings, **dispatch `ag-ui-advisor`** rather than guessing.

## Report format

```
## AG-UI Conformance Audit — <date>
Endpoint: <url/path>   Auth: <scheme>   GenUI mode: <static|declarative|open-ended|none>   Mode: <static|live>

C1 Transport/Serialization:  [PASS] ... [MISSING] ... (fix @ file:line)
C2 Event ordering:            ...
C3 Required fields:           ...
C4 Conformance traps:         ...
C5 GenUI wiring:              ...
C6 Client consumer:           N/A | ...

Findings: Critical → High → Medium → Low
Verdict: AG-UI conformant? <yes/no>
Remediation (cheapest-unblock-first): terminal event coverage → camelCase wire → event ordering → CUSTOM name documentation → GenUI wiring
Next action: <or "dispatch ag-ui-advisor for X">
```
