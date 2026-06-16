---
name: agent-stack-check
description: "Umbrella conformance auditor for the whole agent-interop stack — MCP + A2A + AG-UI + A2UI — in one pass. Detects the project's role (server/consumer/both) per protocol, runs each protocol's existing check skill + advisor agent (never re-deriving a rule), then adds cross-protocol SEAM audits no single check owns (A2UI-over-A2A, A2UI-over-AG-UI, agent-card↔implementation, version/capability alignment, catalog coherence). Produces ONE consolidated, deduped, severity-ranked issue list with per-protocol/seam/overall verdicts. Advisory only — lists issues for the project to fix, never edits. Portable, project-agnostic. Use when the user wants a full-stack interop compliance audit of a project."
---

# /agent-stack-check — full agent-interop stack conformance audit

One pass that audits a project's conformance across the **entire agent-interop stack** and returns a
single prioritized issue list the team can work through:

```
MCP    → tools / data layer
A2A    → inter-agent layer (cards, task routing, artifacts)
AG-UI  → agent↔UI transport (event streaming)
A2UI   → UI specification layer (component catalog)
```

It is an **orchestrator, not a fifth rulebook.** It composes the four existing per-protocol pairs —
one source of truth each — and adds the **cross-protocol seam audits** that no single check owns:

| Protocol | Advisor agent (reasoning) | Check skill (mechanical) |
|---|---|---|
| MCP | `mcp-advisor` | `/mcp-check` |
| A2A | `a2a-advisor` | `/a2a-check` |
| AG-UI | `ag-ui-advisor` | `/ag-ui-check` |
| A2UI | `a2ui-advisor` | `/a2ui-check` |

**Authority rule (non-negotiable):** this skill **never re-derives or restates a protocol rule.** It
delegates every per-protocol judgment to that protocol's advisor + check, and only *synthesizes* —
fan-out, seam-audit, dedupe, rank. When the underlying pairs are tightened, this skill inherits the
change for free. **Advisory only — it lists issues; it does not fix them.**

## Usage

```
/agent-stack-check [path] [--live <base-url>] [--only <p,..>] [--skip <p,..>] [--server|--client|--all] [--renderer] [--tck] [--cli]
```
- `path` — project root to audit (default: cwd).
- `--live <url>` — forward live probing to the protocols that have a live surface (MCP endpoint, A2A endpoint, AG-UI SSE). A2UI has no live endpoint of its own; under `--live` its payloads are inspected on the A2A/AG-UI stream.
- `--only mcp,a2a` / `--skip ag-ui` — restrict which **protocols** are audited.
- `--server` / `--client` (alias `--consumer`) / `--all` — **filter which role(s)** to audit across protocols (see Phase 0; detection still decides what exists).
- `--renderer` — forwarded to `/a2ui-check` (audit the A2UI Path-A renderer).
- `--tck` — forwarded to `/a2a-check` (A2A TCK suite). `--cli` — forwarded to `/mcp-check` (connector CLI validation).

## Role coverage owned by the kit

| Protocol | Server role | Consumer/client role |
|---|---|---|
| MCP | ✅ audited | **deliberate N/A** — consumer (host) side is Claude.ai/external, not owned; report as N/A-by-design, not a gap |
| A2A | ✅ (D1–D6) | ✅ (D7) |
| AG-UI | ✅ | ✅ (`--client`) |
| A2UI | ✅ (emit) | ✅ (render Path A / extract Path B) |

## Phase 0 — Discover protocols AND roles (report up front)

Detect which of the four protocols the project actually touches, and for each, the project's
**role**: `server` / `consumer` / `both` / `N-A`. Signals:
- **MCP** — an MCP server (Streamable HTTP/stdio transport, `initialize` handler, OAuth/`.well-known`). *(Consumer/host side is N/A by design.)*
- **A2A** — server: serves an agent card + task/RPC surface. consumer: an A2A client/SDK, outbound `message/send`·`message/stream`, agent-card fetching, `X-A2A-Extensions` headers.
- **AG-UI** — server: an SSE run endpoint emitting AG-UI events. consumer: a frontend parsing those events.
- **A2UI** — server: emits A2UI (createSurface/updateComponents/… over A2A DataPart or AG-UI CUSTOM). consumer: renders (Path A) or extracts (Path B).

A protocol with no surface present → **N/A** (not a failure). Then:
1. **Apply `--only`/`--skip`** to the protocol set.
2. **Apply `--server`/`--client`/`--all` as a FILTER over detection** — a role you request but the code doesn't have is **skipped with a warning**, never failed; detection alone determines what exists. Default = audit whatever was detected.
3. **Print the role matrix before auditing**, e.g.:
```
Detected (audit scope):
  MCP    server                 (consumer N/A — not owned)
  A2A    both        (D1–D6 + D7)
  AG-UI  server
  A2UI   server (emit)
  [--client requested but no AG-UI consumer surface found → AG-UI consumer skipped]
```
The user reads the matrix and can re-run with a flag if detection misjudged a role.

## Phase 1 — Fan out (parallel subagents; reuse, never reimplement)

Dispatch **one subagent per detected protocol, in parallel** (single message, multiple `Agent`
calls). Use that protocol's **advisor agent** as the `subagent_type` (`mcp-advisor`, `a2a-advisor`,
`ag-ui-advisor`, `a2ui-advisor`) so the deep-reasoning expert runs the audit.

> **ANTI-PATTERN — single-advisor collapse (PROHIBITED):** Dispatching ONE advisor (e.g.
> `a2ui-advisor`) and asking it to "also cover" MCP, A2A, or AG-UI is **not a valid Phase 1
> implementation** — it silently drops entire protocol dimensions and produces false COMPLIANT
> verdicts. Any scope cues in the call arguments (e.g. "focus on the A2UI regression") are
> **Phase 3 emphasis hints only** — they narrow what Phase 3 highlights, never which protocols
> Phase 1 audits. Every detected protocol MUST get its own dedicated advisor subagent.
> This failure mode recurs when `/agent-stack-check` is triggered from the `/wave` Protocol Audit
> phase or any call site — the full four-advisor fan-out is mandatory regardless of call site or
> apparent narrowness of recent changes. Prior sessions lost MCP (M-001, M-002), A2A error-code
> (D2-F1), and seam S1 (3 missing skills) to this collapse.

Because a `subagent_type`-dispatched advisor runs as its own agent and **cannot invoke the parent's
`/<protocol>-check` slash command**, the subagent prompt MUST tell it to **Read the check skill file
and apply it as its checklist**:

- "**Read `.claude/skills/<protocol>-check/SKILL.md` and apply its full dimension methodology** to
  audit `<path>` for **<protocol>** conformance, for the **<role(s)>** role. Return findings as
  structured items `{severity, role, dimension, rule/spec-basis, file:line, fix}`, plus a
  per-dimension PASS/PARTIAL/MISSING table and a per-role verdict. Also report the protocol *facts*
  you observe (card contents, emitted MIME types, declared versions, advertised extensions,
  catalogId) for the seam pass. Do NOT fix anything."
- **Forward only that protocol's applicable flags** (don't broadcast all flags to all subagents):
  `mcp` ← `--live`, `--cli` · `a2a` ← `--live`, `--tck`, detected role · `ag-ui` ← `--live`,
  `--client` · `a2ui` ← `--renderer` (and, for `--live`, A2UI is otherwise spec-static — it has no
  live endpoint of its own, so `--live` for A2UI means *inspect the A2UI payloads emitted on the
  A2A/AG-UI endpoint*, not probe a separate A2UI service).
- For **A2UI**, instruct: report RESERVED Standard-Profile types as informational, **never as
  failures** (no field contract exists to violate).
- For **A2A**, pass the detected role so D1–D6 (server) and/or D7 (consumer) run appropriately.
- For **AG-UI**, pass the detected role so the **consumer audit runs when an AG-UI consumer is
  detected, whether or not `--client` was supplied** — `/ag-ui-check` gates its consumer dimension
  behind `--client`, so the subagent prompt MUST instruct it to audit the consumer side on detection
  (the flag is an explicit override/filter, not the only trigger — matching Phase 0's
  detection-wins principle). Same applies to A2UI's render/extract (consumer) side.

Collect each subagent's structured findings + the protocol facts they surface (card contents,
emitted MIME types, declared versions, advertised extensions, catalogId) — those feed Phase 2.

## Phase 2 — Cross-protocol seam audit + dedupe

Using the facts the four subagents surfaced, audit the **seams** — the interop bugs that live
*between* protocols, which no single check fully owns (each assumes the seam is the other's job).
Each seam finding names **both** owning layers and cites the per-protocol basis.

| # | Seam | Verify |
|---|---|---|
| **S1** | Agent card ↔ implementation | The card advertises exactly what the code implements: MCP tools exist; A2A skills/methods exist; the **A2UI extension is advertised iff A2UI is emitted**; an AG-UI run endpoint exists iff AG-UI is used. Flag **orphan advertisements** (advertised, not implemented) AND **silent capabilities** (implemented, not advertised). |
| **S2** | A2UI ↔ A2A DataPart | The A2UI-over-A2A binding is **coherent end-to-end**: the A2UI extension URI advertised in the card's `capabilities.extensions[]` is the same one the client activates via `X-A2A-Extensions`, and the `DataPart` MIME + array shape `/a2ui-check` (A5) expects on emit is exactly what `/a2a-check` (D6/D7.11) expects on the wire. **This seam checks the two layers AGREE; defer the canonical MIME/URI literals to `a2ui-advisor` — do not restate them here.** |
| **S3** | A2UI ↔ AG-UI CUSTOM | The A2UI-over-AG-UI binding is **coherent**: the `CUSTOM` event carrying A2UI (its name + message-array shape per `/a2ui-check` A6) is exactly what the AG-UI consumer routes on (per `/ag-ui-check`), AG-UI is advertised via its run endpoint (not an invented agent-card extension id), and `a2uiClientCapabilities` sits in the transport-correct slot for each binding (the canonical slot paths are defined by `a2ui-advisor` — not restated here). **Defer the event-name, message-shape, and capability-slot literals to the pairs; this seam checks the two ends AGREE.** |
| **S4** | MCP ↔ A2A | If the project is both an MCP server and an A2A agent: tool/skill descriptions and **auth schemes are coherent across the two surfaces** (MCP OAuth discovery vs A2A card `securitySchemes`) — the genuine cross-protocol concern. (Single-protocol MCP output shape is owned by `/mcp-check`, not asserted here.) |
| **S5** | Version & capability alignment | The version each protocol *declares* matches what its own check expects (consult the per-protocol advisor for the current literal — this skill does not hardcode versions), and negotiation is **honored end-to-end, not just declared**: A2UI **tier** capability gating (tier vocabulary per `a2ui-advisor` — not restated here) drives whether Extended types are emitted; MCP version negotiation drives which fields appear; A2A `protocolVersion` matches the served surface. (AG-UI has no wire protocol version — only an SDK pin — so there is nothing to align there; don't invent one.) |
| **S6** | A2UI catalog coherence | The **`catalogId` advertised on the agent card == the one used in `createSurface` == the profile the renderer/extractor supports** — a mismatch silently breaks rendering. This seam checks the three references match; the canonical profile id literal is defined by `a2ui-advisor`, not restated here. |

**Dedupe across protocols:** when two per-protocol subagents flag the same underlying defect (e.g.
`/a2a-check` D-layer and `/a2ui-check` A5 both flag the DataPart MIME), **collapse into ONE seam
finding** naming both layers — do not double-count. Cite each contributing protocol's basis.

For any seam needing deeper judgment, **dispatch the relevant advisor(s)** (e.g. `a2ui-advisor` +
`a2a-advisor` for an S2 call) rather than guessing.

## Phase 3 — Synthesize the consolidated report

Merge per-protocol findings + seam findings into one list: **deduped, grouped, severity-ranked**
(Critical → High → Medium → Low). Every finding carries: owning protocol/seam · role · `file:line` ·
spec basis · concrete fix · a "consult `<advisor>`" pointer for the deep dive. Built for a team to
triage — **never auto-fixed.**

### Verdict (strict)

- A protocol/role is **COMPLIANT** only if it has **no Critical and no High** findings (Medium/Low
  become a punch-list, not a failure).
- **Overall = COMPLIANT** only if **every in-scope protocol AND every applicable seam** is COMPLIANT.
- **RESERVED A2UI Standard-Profile types never count as failures** (no contract to violate).
- A role marked **N/A** (absent, or MCP-consumer-by-design) does not affect the verdict.

## Steps

1. **Phase 0** — detect protocols + roles; apply `--only`/`--skip` and the role filter; **print the role matrix**.
2. **Phase 1** — dispatch the per-protocol advisor subagents in parallel, each running its `/<p>-check` methodology for the detected role(s); collect structured findings + protocol facts.
3. **Phase 2** — run the S1–S6 seam audit on the collected facts; dedupe overlapping per-protocol findings into single seam findings; dispatch advisors for judgment calls.
4. **Phase 3** — synthesize the consolidated, deduped, severity-ranked report with per-protocol/seam/overall verdicts.
5. Hand the issue list to the team. **Do not fix** (this skill is advisory). For remediation of a specific finding, point at the owning `/<p>-check --fix`-style flow or the advisor — not this skill.

## Report format

```
## Agent-Stack Conformance Audit — <date>
Scope: <path>   Mode: <static|live>   Protocols audited: <mcp,a2a,ag-ui,a2ui>

Role matrix:
  MCP    server                 (consumer N/A — not owned)
  A2A    both
  AG-UI  server
  A2UI   server (emit)

Per-protocol verdicts:
  MCP    [server]            COMPLIANT | NON-COMPLIANT (<n> findings)
  A2A    [server]            ...
  A2A    [consumer / D7]     ...
  AG-UI  [server]            ...
  A2UI   [emit]              ...   (RESERVED types: informational only)

Seam verdicts:
  S1 card↔impl              PASS | <finding>
  S2 A2UI-over-A2A          ...
  S3 A2UI-over-AG-UI        ...
  S4 MCP↔A2A                N/A | ...
  S5 version/capability     ...
  S6 catalog coherence      ...

Consolidated findings (deduped, severity-ranked):
  [CRITICAL] <protocol/seam> <role> — <issue>  (bases: <layer-A §> + <layer-B §> → fix @ file:line; consult <advisor(s)>)
  [HIGH] ...
  [MEDIUM] ...   [LOW] ...
  (a collapsed seam finding lists BOTH contributing layers' bases + both advisors)

OVERALL: COMPLIANT | NON-COMPLIANT
  (COMPLIANT iff every in-scope protocol + every applicable seam has zero Critical/High.)
Punch-list (Medium/Low, non-gating): <count> items.
Next: work the Critical/High list; re-run /agent-stack-check to confirm.
```

## Notes

- **Self-contained via composition:** this skill carries no protocol field-rules of its own — the
  four advisors + four checks are the source of truth, and the A2UI contract specifically lives in
  `a2ui-advisor` (the Standard Profile v1). Keep this skill thin; if a per-protocol rule seems
  wrong, fix it in that protocol's pair, not here.
- **Parallelism:** Phase-1 subagents are independent — always dispatch them in one message. Phase 2
  depends on Phase 1's facts (barrier), so it runs after fan-in.
- **No silent scope cuts:** if `--only`/`--skip`/a role filter drops a surface, or a protocol is
  N/A, **say so in the matrix** — never let an unaudited surface read as "passed".
