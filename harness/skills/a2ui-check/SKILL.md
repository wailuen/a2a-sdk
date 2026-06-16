---
name: a2ui-check
description: "Audit an A2UI implementation for conformance to protocol v0.9.1 AND the A2UI Standard Profile v1 (Core 7 + Extended 11 component types with frozen field contracts). Static code audit + optional live probes across message types (createSurface/updateComponents/updateDataModel/deleteSurface), catalog wiring, Python SDK, A2A DataPart / AG-UI CUSTOM delivery, client renderer (Path A) or backend extraction (Path B), capability negotiation, structural field-contract validation, and the field-hardened conformance traps. Portable and self-contained — audits against the published spec (the a2ui-advisor agent), never against another project's codebase."
---

# /a2ui-check — A2UI v0.9.1 + Standard Profile v1 conformance audit

Systematic audit of an A2UI implementation against the **A2UI protocol v0.9.1** and the **A2UI
Standard Profile v1** (`urn:a2ui-profile:standard:v1`). Covers **both server (emit) and client
(render)**. **Portable / self-contained** — the contract is the published spec in the **`a2ui-advisor`
agent**; this skill audits an implementation against that spec, never against any other project's
source or a live endpoint.

This skill is the **mechanical pass/fail sweep**; the **`a2ui-advisor` agent** is the authoritative
spec + deep-reasoning expert (full field contracts, catalog design, renderer architecture,
remediation). Run this for a repeatable audit; dispatch `a2ui-advisor` for the contract details and
judgment calls.

Source of truth: the `a2ui-advisor` agent (protocol + Profile). Protocol grounding:
`github.com/google/A2UI`, `a2ui.org`. Python package: `a2ui-agent-sdk`.

## Usage

```
/a2ui-check [--live <base-url>] [--renderer]
```
- no flag → static code audit only
- `--live <url>` → also probe a running agent and inspect emitted A2UI payloads
- `--renderer` → also audit a Path-A frontend renderer

## Step 0 — Discover (never assume)

Locate by search: `A2uiSchemaManager`, `CatalogConfig`, `parse_response_to_parts`, `A2uiStreamParser`,
`create_a2ui_part`, `VERSION_0_9_1`. Find the catalog file(s) and which Profile types are emitted.
Find the delivery mechanism (A2A DataPart or AG-UI CUSTOM). Find the protocol `version`. Determine the
client architecture: **Path A** (full renderer) or **Path B** (backend extraction → own content
blocks). Note whether `generate_system_prompt()` is called and with what params.

## What this checks

### A1 — Python SDK wiring (server)

| Check | Pass condition |
|---|---|
| `A2uiSchemaManager` initialized with `VERSION_0_9_1` | Use the constant, not a version string |
| `generate_system_prompt()` called with `include_schema=True`, `include_examples=True` | Both required for the LLM to learn the catalog |
| All LLM output validated via `catalog.validator.validate()` before `create_a2ui_part()` | Unvalidated output reaches the client and breaks rendering |
| `create_a2ui_part()` used (not manual dict construction) | Manual construction risks the wrong MIME type |
| `try_activate_a2ui_extension()` called per request | Version negotiation for multi-version compatibility |
| `allowed_components` specified | Prunes the schema; stops the LLM hallucinating unsupported types |

### A2 — Message types & ordering

| Check | Pass condition |
|---|---|
| `createSurface` before any `updateComponents`/`updateDataModel` | Surface must exist first |
| `version` in every message | `"v0.9.1"` at top level |
| `surfaceId` in all post-create messages | Required |
| `catalogId` in `createSurface` | Required (LLMs drop it); Profile id is `urn:a2ui-profile:standard:v1` |
| `deleteSurface` before re-creating the same `surfaceId` | Duplicate `createSurface` is a protocol error |
| `data` field in a DataPart is an array | Even for one message |
| Sequential processing on failure | Continue the array on a per-message error; no bail-early |

### A3 — Component model

| Check | Pass condition |
|---|---|
| The surface's **first** `updateComponents` establishes exactly one `id:"root"` | Until a root exists nothing renders; later `updateComponents` MAY omit root (progressive upsert) |
| Component type names are **PascalCase** | `"KpiCard"` not `"kpi_card"`/`"kpicard"` |
| Component `id`s unique within the surface | Duplicate ids silently overwrite |
| Children referenced by `id`, not inline objects | Flat adjacency list |
| Binding form correct | `{"path":"/json/pointer"}` (absolute) or `{"path":"field"}` (relative, no leading `/`) |
| ChildList template form for dynamic lists | `{"path":..., "componentId":...}` — not a static array |

### A4 — Custom catalog wiring

| Check | Pass condition |
|---|---|
| Catalog freestanding | No external `$ref` except `common_types.json` |
| Child-id fields use `"$ref": "common_types.json#/$defs/ComponentId"` | Raw `"type":"string"` is invisible to the tree validator |
| ChildList fields use `"$ref": "common_types.json#/$defs/ChildList"` | Required for template form |
| `catalogId` is a stable URI, consistent across agent card + `createSurface` | Need not be hosted |
| Data-bearing custom types expose a `data: {$ref: Binding}` prop | Else Path-B extraction yields zero output |
| Catalog validates via `CatalogConfig.from_path()` | No load errors |

### A5 — A2A DataPart delivery (if applicable)

| Check | Pass condition |
|---|---|
| MIME type `application/a2ui+json` (canonical v0.9.1) | Not `application/json+a2ui` (legacy/deprecated) |
| Extension URI in agent card `capabilities.extensions[]` | `https://a2ui.org/a2a-extension/a2ui/v0.9.1` |
| `X-A2A-Extensions` header on agent-to-agent requests | Required to activate the extension |
| `DataPart.data` is a JSON array | Not a bare object |
| `DataPart.metadata.mimeType` set | Required for consumer dispatch |

### A6 — AG-UI CUSTOM delivery (if applicable)

| Check | Pass condition |
|---|---|
| `CUSTOM` event `name` is `"A2UI_UPDATE"` (or a documented equivalent) | Consistent + documented |
| `CUSTOM.value` carries the A2UI message array | `value.messages` (or `value`) is the array |
| `version` present inside each message in the array | Still required inside CUSTOM |
| Frontend routes CUSTOM by `name` | `if (event.name === "A2UI_UPDATE")` |
| AG-UI advertised via a run endpoint, not an agent-card URN | No invented `urn:agui:*` extension id |

### A7 — Conformance traps (the expensive ones)

- **v0.8 key-discriminator in v0.9 code** — `{"component":{"Text":{...}}}` vs `{"component":"Text",...}`. Silent failure.
- **Missing `root`** — client buffers indefinitely; nothing renders.
- **Unvalidated LLM output** — validate every emission; `"text"` vs `"Text"` is the most common error.
- **`data` not an array** — protocol error.
- **`catalogId` omitted** from `createSurface` — required; validate before sending.
- **Wrong MIME type** — `application/json+a2ui` for v0.9.1 is deprecated; flag medium.
- **Missing `version`** — fails schema validation.
- **Duplicate `createSurface`** without `deleteSurface` — protocol error.
- **`action` without extension activation** — agent never parses it.
- **Emitting an Extended type to a Core-only client** — must check capabilities and degrade.
- **Field-contract drift on a Profile type** — see A9.
- **Relying on a RESERVED type's field shape** — see A9.

### A8 — Frontend renderer (Path A, with `--renderer`)

| Check | Pass condition |
|---|---|
| `MessageProcessor` handles all 4 message types | createSurface/updateComponents/updateDataModel/deleteSurface |
| Surface updated atomically before repaint | No mid-array partial renders |
| JSON Pointer (RFC 6901) resolver: absolute + relative | `/a/b` vs `field` (no leading `/`) |
| ChildList template expansion | `{"path":..., "componentId":...}` |
| Two-way binding for inputs | Write on interact; read on data-model update |
| Inbound validation before state update | Log + continue remaining messages |
| `action` dispatch to server on interaction | Button → action message with required fields |
| `unsubscribe` on all observables | Prevents the surface-delete leak |
| `a2uiClientCapabilities` advertised in the correct per-transport location, **incl. tier** | A2A `Message.metadata`, AG-UI `RunAgentInput.forwardedProps`; object `{version, catalogs:[...], tier:"core"\|"core+extended"}`; emitter degrades Extended types when `tier="core"` (or capabilities absent) |
| No re-render mid-array | Batch all messages, paint once |

**Path B (backend extraction) instead of A8:** if the client is Path B, A8 does not apply — verify
instead that the backend folds the message sequence, resolves bindings, validates the resolved
payload against the Profile field contract (A9), and emits the project's own content blocks; the
frontend renders those with no surface model / JSON-Pointer logic of its own.

### A9 — A2UI Standard Profile v1 catalog conformance

The Profile defines **18 component types** — **Core (7)** every renderer MUST support, **Extended
(11)** gated by client capability. Full field contracts live in the `a2ui-advisor` agent; this
section audits an implementation against them. **Validation is STRUCTURAL ONLY**: required keys
present + correct container/primitive type — never value semantics (a `KpiCard` with garbage numbers
still passes structurally). Profile payloads ride under each component's **`data` binding** (resolved
from the data model via `{path}`) — validate the **resolved `data` object** against the contract, not
bare props on the component.

**Profile types** (PascalCase wire / snake_case data_type):

- **Core (7):** `TimeSeriesChart`/`time_series` · `ComparisonTable`/`comparison_table` · `KpiCard`/`kpi_card` · `BarChart`/`bar_chart` · `EntityList`/`entity_list` · `MarketBriefing`/`market_briefing` *(FROZEN prose — `data` is a markdown string)* · `TradeActivity`/`trade_activity` *(RESERVED)*
- **Extended (11):** `EmailList`/`email_list` · `CalendarEvents`/`calendar_events` · `UserProfile`/`user_profile` · `UserList`/`user_list` · `DocumentList`/`document_list` · `WaterfallChart`/`waterfall_chart` · `MultiCategoryChart`/`multi_category_chart` · `FundPerformance`/`fund_performance` · `CompanyInfo`/`company_info` *(RESERVED)* · `DealList`/`deal_list` *(RESERVED)* · `InvestorProfile`/`investor_profile` *(RESERVED)*

| Check | Pass condition |
|---|---|
| PascalCase on the wire, snake_case data_type | Translate exactly once at the boundary |
| Emitted **FROZEN** Profile payloads satisfy their field contract | Required keys present + right container types (per the agent's contracts) — e.g. `WaterfallChart.segments[]` each has `label`/`value`/`type`/`cumulative`; `KpiCard.metrics[]` each has `label`/`value` |
| Field names + casing match the frozen contract verbatim | Profile casing is not uniform; `time_series` uses `x_key`, `FundPerformance` uses camelCase wire aliases — match exactly |
| **RESERVED** types not emitted with an assumed shape, not audited on field structure | `TradeActivity`, `CompanyInfo`, `DealList`, `InvestorProfile` have no v1 field contract |
| `MarketBriefing` rendered as **prose**, not a card | No border, no surface background; its `data` resolves to a markdown string (no object contract) |
| Extended types gated on client capability | Emitter checks `a2uiClientCapabilities` tier; degrades to a Core type or prose when Extended unsupported |
| Unknown / non-Profile `data_type` → fallback prose, NOT a hard failure | The expected "raw / auto-detect" lane — never a violation |
| Profile + protocol versions pinned | protocol `v0.9.1` + Profile `urn:a2ui-profile:standard:v1` |

**Structural-validation reference — principal required keys per FROZEN type.** This is a
**quick-reference, NOT exhaustive**: each line names the principal required keys; a `...` marks where
more required keys exist. The `a2ui-advisor` field tables are the **authoritative** contract — audit
against them, not these abbreviations.

- `time_series` → `chart_type`, `title`, `x_key`, `y_key`, `data:[{date, value}]`, `total_count`
- `comparison_table` → `columns:[{key, label}]`, `rows:[object]`
- `kpi_card` → `metrics:[{label, value}]`
- `bar_chart` → `bars:[{category, value}]`
- `entity_list` → `entity_type`, `items:[{id, name}]`
- `email_list` → `messages:[{id, subject, preview, from, to_recipients, received_at, is_read, has_attachments, importance, web_link}]`, `total_count`, `has_more`
- `calendar_events` → `date_range:{start,end}`, `events:[{id, subject, start, end, is_all_day, is_cancelled, is_recurring, organizer, attendees_count, importance, show_as, web_link}]`, `total_count`, `has_more`
- `user_profile` → `id`, `display_name`, `email`, `business_phones`
- `user_list` → `users:[{id, display_name, email}]`, `total_count`, `has_more`
- `document_list` → `documents:[{id, name}]`
- `waterfall_chart` → `title`, `segments:[{label, value, type, cumulative}]`
- `multi_category_chart` → `title`, `periods:[{period, categories}]`, `summary:{by_category, period_count}`, `date_range:{first, last}`
- `fund_performance` → all fields optional camelCase aliases (`irr`, `tvpi`, `netIrr`, `nav:{amount,currency}`, …)
- `market_briefing` → `data` resolves to a **markdown string** (prose; no object contract to check)

(For the complete field tables incl. all additional fields, sub-objects, and enums, consult `a2ui-advisor` — the authoritative contract.)

## Live probes (`--live <url>`)

```bash
BASE="<url from args>"
AUTH="Authorization: Bearer <key>"

# 1. Query that should emit a rich artifact — inspect the emitted A2UI payload
curl -X POST "$BASE/v1/message:send" \
  -H "Content-Type: application/json" -H "$AUTH" \
  -d '{"jsonrpc":"2.0","id":1,"method":"message/send","params":{"message":{"kind":"message","role":"user","parts":[{"kind":"text","text":"<a query that should yield a chart/table>"}],"messageId":"<uuid>"}}}'
# Assert: a part with kind=="data" AND metadata.mimeType=="application/a2ui+json"
# Assert: data[] is an array; first message is createSurface with version, surfaceId, catalogId
# Assert: an updateComponents has a component id=="root"; component names are PascalCase
# Assert: any FROZEN Profile payload satisfies its A9 structural contract

# 2. MIME type — must be application/a2ui+json, not application/json+a2ui

# 3. Extension advertisement in the agent card
curl -sf "$BASE/.well-known/agent-card.json" | python3 -c "
import json,sys
c=json.load(sys.stdin)
uris=[e['uri'] for e in c.get('capabilities',{}).get('extensions',[])]
print('A2UI extension:', 'https://a2ui.org/a2a-extension/a2ui/v0.9.1' in uris)
print('Profile advertised:', any('a2ui-profile:standard' in str(e.get('params',{})) for e in c.get('capabilities',{}).get('extensions',[])))
"
```

## Steps

1. Step 0 discovery — SDK usage, catalog/Profile types, delivery, version, client architecture (Path A/B).
2. A1–A9 against the code with `file:line` evidence; mark PASS / PARTIAL / MISSING. An item you can't positively confirm is a **finding, not a pass** (fail closed).
3. If `--live`, run the probes and fold results in.
4. For each finding: state the spec/contract basis and the fix @ `file:line`.
5. For full field contracts, catalog design, or renderer architecture, **consult `a2ui-advisor`** rather than guessing — it is the authoritative source.

## Report format

```
## A2UI Conformance Audit — <date>
Protocol: <v0.8|v0.9|v0.9.1>   Profile: <urn:a2ui-profile:standard:v1 | other | none>
Delivery: <DataPart|CUSTOM|both>   Client: <Path A renderer | Path B extraction | N/A>   Mode: <static|live>

A1 SDK wiring:           [PASS] ... [MISSING] ... (fix @ file:line)
A2 Message types/order:  ...
A3 Component model:      ...
A4 Custom catalog:       ...
A5 A2A DataPart:         N/A | ...
A6 AG-UI CUSTOM:         N/A | ...
A7 Conformance traps:    ...
A8 Renderer (Path A):    N/A (Path B) | ...
A9 Profile catalog:      [PASS] FROZEN payloads conform ... [FLAG] RESERVED type emitted with shape ...

Findings: Critical → High → Medium → Low
Verdict: conformant to protocol v0.9.1? <y/n>   to Standard Profile v1? <y/n>
Remediation (cheapest-unblock-first): MIME type → version field → root component → createSurface-before-update → catalogId → field-contract drift → capability/tier gating → renderer binding
Next action: <or "consult a2ui-advisor for the full <Type> field contract">
```
