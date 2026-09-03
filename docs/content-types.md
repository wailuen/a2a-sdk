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
