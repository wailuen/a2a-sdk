---
name: add-tool
description: "Add a tool to an agent-sdk agent: a pydantic input model + an async @tools.tool function + a FakeModelClient test + a console sample, wiring tier and emits correctly. Enforces the SDK invariants — no raw httpx (call a SourceAdapter), no secrets in errors, path params via url_segment, emits must be a registered content type. Use when the user wants to add or change a tool/capability on an agent built with agent-sdk."
---

# /add-tool — add a tool to an agent-sdk agent

Adds one capability the model can call. A tool is a thin async function over a
`SourceAdapter`: the SDK turns it into an A2A skill, an MCP tool (tier 1), an
AG-UI run capability, and — if it `emits` a content type — an A2UI card. You write
the function, the input model, and the test; the SDK owns everything on the wire.

Run this from inside an agent repo (it edits `src/tools/…` and `tests/`). **No git
commit** unless the user asks.

## Usage

```
/add-tool [name] [--module <file>] [--tier 1|2] [--emits <ContentType>] [--new-card]
```
- `name` — tool name (snake_case); defaults to the function name.
- `--module` — `src/tools/<file>.py` to add to (create if absent; wire into `main.py`).
- `--tier` — `1` = query (exposed over **A2A + MCP**), `2` = composite (**A2A only**). Default 1.
- `--emits` — a registered content type the tool returns as a structured artifact.
- `--new-card` — the output needs a domain A2UI card that doesn't exist yet (sub-flow below).

## What good looks like (the contract)

```python
# src/tools/<module>.py
from pydantic import BaseModel, Field
from agent_sdk import ToolSet
from agent_sdk.models.content_types import KpiCard, MetricItem
from ..sources.<source> import <Source>Adapter

tools = ToolSet()                      # one ToolSet per module; main.py collects them

class <Name>Input(BaseModel):
    symbol: str = Field(description="Ticker symbol")   # described fields = better tool-calls

@tools.tool(tier=1, emits=KpiCard, sample={"symbol": "AAPL"})
async def <name>(inp: <Name>Input, *, api: <Source>Adapter) -> KpiCard:
    """One-line description the model sees."""          # docstring == tool description
    data = await api.<method>(inp.symbol)               # adapter does the HTTP, not the tool
    return KpiCard(title=..., metrics=[MetricItem(label=..., value=...)])
```

- **Input model** — exactly one positional pydantic model (omit it for a no-input
  tool). Give every field a `description`. **Path safety is the adapter's job, not the
  decorator's:** a `str` that gets interpolated into a URL **path** must be passed
  through `validation.url_segment()` *inside the `SourceAdapter` method* (identifiers
  through `safe_id()`). The `@tool` machinery does **not** validate path params — there
  is no `path_param` flag — so never f-string raw input into a URL and never assume the
  decorator sanitizes it. (See `template/src/sources/sample_api.py` for the pattern.)
- **Adapters are keyword-only params** annotated with the adapter class; the SDK
  injects one instance per registered class by **exact-class match**. Declare as many
  as the tool needs. There is no `source=` kwarg — the annotations are the only
  source of truth.
- **`tier`** — 1 unless the tool composes other tools / isn't safe as a raw MCP tool.
- **`emits`** — must be a content type already registered with the SDK (a FROZEN
  Standard Profile type, or a domain card registered via `register_content_type`).
  `build_app()` rejects an unknown `emits` at boot. Omit `emits` for a tool that
  returns plain data (`dict`); it still works, it just won't render a card.
- **`sample`** — a representative input dict; powers the console "Try" button.

### FROZEN content types available for `emits` (class name == wire name)

Core (Tier 1): `KpiCard`, `TimeSeriesChart`, `ComparisonTable`, `BarChart`,
`EntityList`, `MarketBriefing` (a **prose** type — its `data` resolves to a markdown
string, not an object; rendered as plain prose with no card chrome). Extended:
`WaterfallChart`, `MultiCategoryChart`, `FundPerformance`, `EmailList`,
`CalendarEvents`, `UserProfile`, `UserList`, `DocumentList`. (The 4 RESERVED types are
name-only, no field contract — **never `emits` them**: `TradeActivity` is the Core-tier
reserved allocation; `CompanyInfo`, `DealList`, `InvestorProfile` are Extended-tier.)
When unsure which type fits the shape, **ask `a2ui-advisor`** — don't guess a mapping.

### `--new-card` sub-flow (domain content type)

If no FROZEN type fits, create a domain card in `src/content.py` (see
`examples/alphageo/src/content.py`): subclass `ContentModel`, set `data_type`
(snake_case), `component` (PascalCase wire name), and `catalog_id` — your **own**
`urn:<domain>:<area>:v1`, never the Profile catalog id (reusing the Profile id for a
non-Profile component is a false conformance claim, and a renderer that validates
against the Profile catalog will reject the card). Implement `to_plain_text()` (the
REQUIRED A2A text fallback — the only thing a non-supporting client sees; the SDK
auto-assembles the dual-part artifact `TextPart(to_plain_text)` + `DataPart(payload)`,
so you implement only the method, not the wrapping), and call
`register_content_type(<Card>)`. Import the module in `main.py` so registration runs at
import. Choose a `component` name that does **not** collide with any Standard Profile
component name — `register_content_type` enforces global component-name uniqueness
and will raise at boot if there is a clash. **Loop in `a2ui-advisor`** on the card's field
shape and catalog id before finalizing — catalog/`component` mismatches silently break
rendering (seam S6).

## The test (required — never call Bedrock)

Add a test using `agent_sdk.testing`: script the model with `tool_call(...)` then
`reply(...)`, stub the adapter method with `monkeypatch`, drive it through
`/v1/message:send` (the A2A **HTTP+JSON** REST binding this SDK serves — JSON-RPC
agents would use `message/send`), and assert the artifact's `data_type`:

```python
from agent_sdk.testing import reply, tool_call
async def test_<name>_emits_card(client, fake_model, monkeypatch):
    monkeypatch.setattr(<Source>Adapter, "<method>", fake_<method>)
    fake_model.script(tool_call("<name>", {"symbol": "AAPL"}), reply("done"))
    r = await client.post("/v1/message:send", json=send_body("brief me"))
    done = await wait_for_state(client, r.json()["id"])
    assert done["status"]["state"] == "completed"
    assert done["artifacts"][0]["metadata"]["data_type"] == "<data_type>"   # if emits
```

Assert the **artifact-level** `metadata["data_type"]` (as the template test does) — the
SDK sets it for every emit type, so it's the portable assertion. Part-level metadata
differs by type: a **card** (`ContentModel`) emit ships the A2UI `DataPart` self-described
by `metadata = {"mimeType": "application/a2ui+json"}` (the component lives inside the A2UI
message; there is **no** `data_type` on that part), whereas a plain `BaseModel` emit copies
`data_type` onto its `DataPart`. Don't assert `data_type` on a card's DataPart — it won't
be there.

## Steps

1. Pick/create the module; if new, wire it into `main.py` `toolsets=[…]`.
2. Define the input model (described fields). Path safety is enforced in the adapter
   via `url_segment()` — not a tool flag; the decorator has no `path_param`.
3. Write the `@tools.tool` function — adapter call(s) only, docstring = description,
   set `tier`/`emits`/`sample`. For a new card, run the `--new-card` sub-flow first.
4. Write the test (FakeModelClient + stubbed adapter + artifact assertion).
5. Run `.venv/bin/python -m pytest -q tests/` — green before proceeding.
6. **Red-team with `sdk-advisor`** (convention/invariant review of the diff); if the
   tool emits or changes a card, also `a2ui-advisor`. Apply fixes.
7. Offer `/agent-verify` to confirm the surfaces still pass. No commit.

## Invariants enforced (reject the change if violated)

- **No raw `httpx`/`requests` in the tool.** New host ⇒ new/updated adapter, not an
  ad-hoc client.
- **No secrets or input values in errors/logs.** Raise `AgentError(category, message,
  source=…)` with a generic message; never f-string a credential or payload.
- **Path/URL params via `url_segment()`** *in the adapter method*; identifiers via
  `safe_id()`. Never f-string raw input into a URL. The `@tool` decorator does not
  sanitize path params (no `path_param` flag exists) — the adapter is the only
  enforcement point.
- **`emits` must be registered**; class name must equal the wire component exactly
  (case-sensitive — `KpiCard`, never `KPICard`).
- **Interrupts, not blocking.** A tool that needs user confirmation raises
  `ToolInterrupt(reason, message, response_schema=…, resume_handler=…)`; it never
  blocks waiting for input.
