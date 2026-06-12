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
mapping. Every type implements `to_plain_text()` — the mandatory fallback
for clients without A2UI capability.

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

    def to_plain_text(self) -> str:
        return f"{self.headline} (risk score {self.score})"
```

`register_content_type` validates: `ContentModel` subclass, `data_type` +
`component` declared, component not reserved, `data_type` globally unique,
and rejects new types claiming the standard catalog. The agent card
advertises every catalog id in the A2UI extension `params.catalogIds`, so
clients know which catalogs they must render.

A tool then uses `emits=ClimateRiskReport` exactly like a Profile type.
A plain `BaseModel` (not registered) is also accepted for `emits` — it
yields the raw-data artifact and MCP `outputSchema` but no A2UI card.
