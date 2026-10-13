# Content types and A2UI cards

A content type is a pydantic model describing one renderable artifact. The
SDK owns **A2UI Standard Profile v1** — 14 frozen types — and exposes an
extension API for domain cards.

## Standard Profile v1 (frozen)

| `data_type` | Class |
|---|---|
| `kpi_card` | `KpiCard` |
| `time_series` | `TimeSeriesChart` |
| `comparison_table` | `ComparisonTable` |
| `bar_chart` | `BarChart` |
| `entity_list` | `EntityList` |
| `market_briefing` | `MarketBriefing` |
| `waterfall_chart` | `WaterfallChart` |
| `multi_category_chart` | `MultiCategoryChart` |
| `fund_performance` | `FundPerformance` |
| `email_list` | `EmailList` |
| `calendar_events` | `CalendarEvents` |
| `user_profile` | `UserProfile` |
| `user_list` | `UserList` |
| `document_list` | `DocumentList` |

Import from `agent_sdk.models.content_types`. The standard catalog is
**closed**: you cannot add types to it, and the reserved component names
(`TradeActivity`, `CompanyInfo`, `DealList`, `InvestorProfile`) cannot be
claimed by domain cards either — no field contract exists for them.

Field contracts are frozen wire shapes; construct with the typed fragments
(`MetricItem`, `TimeSeriesDataPoint`, …) and the SDK guarantees the A2UI
mapping. Every type implements `_body_text()` — the hook behind
`to_plain_text()`, the mandatory fallback for clients without A2UI
capability.

## What `emits=` produces

When a tool returns its `emits` instance, the SDK translates it into the
4-message self-cleaning A2UI sequence (`createSurface`,
`updateComponents`, `updateDataModel`, `deleteSurface`), capability-gated
per client (`a2uiClientCapabilities` in A2A message metadata / AG-UI
`forwardedProps`). Clients without the capability get the plain-text
fallback — nothing is silently dropped.

## Domain cards (extension API)

Agents may define their own card types under their **own catalog id** —
surfaces never mix catalogs, and the standard catalog stays frozen:

```python
from typing import ClassVar
from agent_sdk.models.content_types import ContentModel, register_content_type

@register_content_type
class ClimateRiskReport(ContentModel):
    data_type: ClassVar[str] = "climate_risk_report"
    component: ClassVar[str] = "ClimateRiskReport"
    catalog_id: ClassVar[str] = "urn:a2ui-catalog:acme:climate:v1"

    headline: str
    score: float

    # Implement _body_text(), NOT to_plain_text(). to_plain_text() is concrete
    # on ContentModel and is what appends the `metadata` suffix (below).
    def _body_text(self) -> str:
        return f"{self.headline} (risk score {self.score})"
```

`register_content_type` validates: `ContentModel` subclass, `data_type` +
`component` declared, component not reserved, `data_type` globally unique,
and rejects new types claiming the standard catalog. The agent card
advertises every catalog id in the A2UI extension `params.catalogIds`, so
clients know which catalogs they must render.

### The `metadata` envelope — you get it for free

`ContentModel` declares one SDK-wide field, `metadata: dict[str, Any] | None`
(GH-63): an out-of-band disclosure envelope such as
`metadata={"coverage_note": "Partial: 5 of 20 funds"}`, distinct from the
frozen per-type fields. Because it is declared once on the base class, every
rule about it is enforced once on the base class too — your card gets all
three without writing any code, and cannot silently skip one:

- `wire()` emits it when set.
- `to_plain_text()` appends it as a trailing `key=value` suffix. **This is why
  you implement `_body_text()` and not `to_plain_text()`** — before this
  split, `metadata` reached `wire()` but no card, built-in or domain, ever
  appended it to its text fallback. Rather than make every card append the
  suffix by hand at its own call site (and risk one silently skipping it, so
  a disclosure annotation reaches the A2UI card but vanishes from the text
  fallback no-capability clients see), the base class now renders it once
  for all of them.
- Non-finite floats (`inf`/`nan`) anywhere inside it are rejected at
  construction, so the DataPart's JSON `null` and the text fallback's `inf`
  can never disagree.

The admin console renders it too, as a dimmed footnote row under the card —
no per-component renderer work needed.

A card written before this split, which overrides `to_plain_text()` directly,
keeps working **unless it also already declares its own `_body_text`** (see the
exception below): `ContentModel.__init_subclass__` adopts the override as the
class's `_body_text()`, so it renders identically and additionally picks up the
suffix — including a card that subclasses a CONCRETE built-in (e.g. `KpiCard`)
and extends its rendering with `super().to_plain_text()`, a pattern that was
fully legal against the pre-split API. That call is safely redirected to the
parent's own rendering rather than re-entering the subclass's override, so it
does not recurse. New code should implement `_body_text()` directly.

From a NEW `_body_text()` override, prefer `super()._body_text()`. Both it and
`super().to_plain_text()` resolve to the same parent rendering — the SDK
frames every `_body_text()` implementation, new-style and adopted-legacy
alike, so a `super().to_plain_text()` call from any level in the chain
resolves exactly one step up instead of re-entering the same override — but
only the outermost call appends the metadata suffix, so
`super().to_plain_text()` adds nothing `super()._body_text()` doesn't already
give you, at the cost of one extra indirection.

**Exception — migration required:** `_body_text` had no reserved meaning
before this split, so a pre-split card may already declare a *private helper*
of that name alongside its `to_plain_text()` override, unrelated to this
mechanism. Adoption is skipped whenever the subclass declares its own
`_body_text` — silently leaving the stale `to_plain_text()` override in place
would shadow the concrete base method and drop the `metadata` suffix, so the
class raises `TypeError` at import time instead. **Before upgrading, grep your
`ContentModel` subclasses for `_body_text`.** If a subclass defines both
`_body_text` and `to_plain_text`, rename the existing `_body_text` member
(e.g. to `_render_body`) and move the body of `to_plain_text()` into a new
`_body_text()` override. A subclass declaring only one of the two names needs
no change.

A tool then uses `emits=ClimateRiskReport` exactly like a Profile type.
A plain `BaseModel` (not registered) is also accepted for `emits` — it
yields the raw-data artifact and MCP `outputSchema` but no A2UI card.

### Delimiter safety (GH-130)

`to_plain_text()` is not a debug aid — it is the mandatory fallback sent
to clients without A2UI capability, and it is also what the model itself
reads (`agent_sdk/agent/runner.py`) and what MCP callers receive as
`structuredContent` (`agent_sdk/routes/mcp.py`). Every untrusted
free-form `str` field on your card — including a title/label/summary
field, not just list or table entries — reaches that surface raw unless
you sanitise it yourself. The SDK's own Profile renderers enforce this
contract on themselves (see the docstring on
`agent_sdk.models.content_types.ContentModel.to_plain_text`); domain
cards get no free ride and must apply the same rule — with the same
helper the SDK's own renderers use:

**Route every untrusted free-form `str` through
`agent_sdk.safe_cell_text(value)`** (also importable as
`agent_sdk.common.redact.safe_cell_text`). One call per value, applied to
every one of them. It collapses the full `str.splitlines()` break set —
not just `\n`/`\r`, also VT, FF, NEL, U+2028/U+2029 — plus the remaining
control characters, and then neutralises the entire separator alphabet.
Only `Literal`-typed enum fields and non-`str` scalars are exempt, because
pydantic has already constrained them.

`safe_error_text` is **not** a substitute: it performs no separator
neutralisation at all, so a value it returns can still fabricate a field
boundary. Use `safe_cell_text` for anything interpolated into a rendered
line.

**Standalone slots (GH-167).** A value that sits alone on its own line, with
nothing joined after it (a title, a name, a summary), does not need the
separator swap. Use `agent_sdk.common.redact.safe_line_text(value)` there: it
collapses line breaks and control characters and caps the length at 256
characters, but keeps `( ) [ ] < > = , :` as written, so `Toshiba (Tokyo)` and
`Smith, John` read correctly. If anything is joined on the same line (a
column, `label: value`, `name <email>`, `k=v`), keep `safe_cell_text`. Exception: if sibling lines are single
delimited rows with ids (e.g. `EmailList` rows and their `preview`), keep
`safe_cell_text`, or the value can mimic a row. If a standalone title sits
above delimited rows (`label: value`, ` | ` columns), keep `safe_line_text` for
the title and indent the rows instead: `safe_line_text` strips leading
whitespace, so the title always starts at column 0 and cannot pass for an
indented row. The SDK's `KpiCard` (`  label: value`) and `ComparisonTable`
(`  header`, `  ---`, `  a | b`) render this way. Put
identifiers on their own labelled line (`id: ...`) rather than joining them
to a name, and move other joined details (email, type, date) to their own
lines too so the name stands alone. The SDK's `UserList`, `UserProfile`,
`DocumentList` and `CalendarEvents` render this way.

The one exception is a **multi-line markdown *document* field** — where
the field's own contract is a block of markdown, not a delimited cell
(free-form prose that intentionally carries headings/lists/paragraphs).
Do not run those through `safe_cell_text`: flattening every newline to a
space and rewriting `|` destroys the content the field exists to carry.
Use `agent_sdk.safe_block_text(value)` instead — it strips ANSI/terminal
escape introducers and other control characters while preserving
`\n`/`\t`/`|` as legitimate content.

### Why one helper, and not a per-renderer opt-in

Each of these is a real boundary an unsanitised value fabricates, and
each was found in a *separate* review round of the SDK's own renderers:

- **Entries joined on `"\n"`** (one row/item per line): a value carrying
  any `str.splitlines()` break invents an extra row.
- **Columns joined on `" | "`**: a value containing `|` — or its visual
  confusables `│` (U+2502) and `｜` (U+FF5C) — invents an extra column.
- **Renderer-specific punctuation**: the `<`/`>` pair `UserProfile`/
  `UserList` wrap an email in, the `(`/`)` pair `DocumentList` wraps a
  type in, the `[unread]` marker `EmailList` prefixes, the `k=v` and
  `", "` joins `MultiCategoryChart` uses, the `": "` label separator most
  renderers use, and the `" – "`/`" — "`/`" @ "`/`" → "` joiners. For
  example, `UserProfile.to_plain_text()` renders `f"{name} <{email}>"`; a
  `display_name` of `"a> <ceo@corp.com"` next to the real `email`
  `"attacker@evil.com"` renders unsanitised as
  `a> <ceo@corp.com <attacker@evil.com>` — a second, forged
  `name <email>` pair a reader can mistake for the real identity.

**Do not hand-maintain this per renderer, and do not write your own
sanitiser for your card module.** That is how the SDK's own renderers
were originally written — each opting into the subset of delimiters it
happened to use — and four consecutive review rounds each found one more
uncovered renderer/delimiter pair. The SDK now applies the whole
alphabet in one place, so a renderer is delimiter-safe by construction
rather than by its author remembering, and `safe_cell_text` is that one
place, exported so your cards share it instead of growing a second copy
that drifts.

Three properties of that alphabet are worth knowing, since they explain
why your values survive it intact — and where one narrow, deliberate
exception remains (RT-010).

Separators used **bare** (`<`, `>`, `(`, `)`, `[`, `]`, `=`, `|`) are
replaced everywhere, unconditionally, and no replacement is itself a
separator, so a neutralised character can never re-fabricate the
delimiter downstream.

Separators that only ever appear **spaced** split into two groups.
`,`, `:`, `–`, `—`, `→` are neutralised everywhere EXCEPT where the
character sits between two ASCII digits — the shape of a genuine numeric
literal, range, or timestamp (`"1,234"`, `"09:30"`, `"9–5"`, `"5→10"`).
A compact occurrence anywhere else — between letters, punctuation, or at
the value's own boundary — is neutralised too, closing the gap an
earlier, purely whitespace-adjacency-based rule left open: `"a,b"` has no
adjacent whitespace on either side, so it used to survive untouched and a
category-key value shaped like `"a,b"` rendered as two categories where
the true count was one.

`@` alone keeps the original, narrower whitespace-adjacency rule: a
compact `a@b` cannot match a `" @ "` join, so it is left alone, which is
what keeps a real email address (`alice@corp.com`) intact. This is a
knowingly ACCEPTED RESIDUAL, not an oversight — a digit-flanked rule can't
apply here (an email's `@` is letter-flanked, not digit-flanked), and
`safe_cell_text` sanitises one value at a time with no field-level type
information, so it cannot distinguish a genuine compact email from a
hostile compact `@` planted in a field that isn't one (e.g. a location
name) — that field's `@` survives too, and a naive reader can still
mistake it for the real `" @ "` joiner. Closing it fully would require
per-field type information this value-level helper deliberately does
not have.

Choose the helper by what the *field* is declared to hold, never by
which method you're writing it in. A single-value field like
`ClimateRiskReport.headline` above still goes through `safe_cell_text`
even though nothing is joined next to it — it reaches the same
model-facing and MCP-facing surface as a delimited render and can still
carry control/escape characters.
