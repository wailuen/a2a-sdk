"""A2UI Standard Profile v1 content models (FROZEN — DESIGN.md §5.4).

Wire-isomorphic Pydantic models for the 14 FROZEN Profile types plus the
registry that the translator, catalog and console all read. Field contracts
are frozen at catalog ``urn:a2ui-profile:standard:v1`` — do not "fix"
inconsistencies (e.g. the three different date_range key pairs); they are
intentional and locked.

Reserved names (TradeActivity, CompanyInfo, DealList, InvestorProfile) have
no field contract in v1: no model exists and ``register_content_type``
refuses the component names.

Domain extension: agents register their own card types with
``register_content_type`` — subclass ``ContentModel``, declare ``data_type``
/ ``component``, implement ``to_plain_text()``.
"""

from __future__ import annotations

import abc
from typing import Annotated, Any, ClassVar, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

CATALOG_ID = "urn:a2ui-profile:standard:v1"
A2UI_VERSION = "v0.9.1"
A2UI_EXTENSION_URI = "https://a2ui.org/a2a-extension/a2ui/v0.9.1"
A2UI_MIME_TYPE = "application/a2ui+json"

RESERVED_COMPONENTS = ("TradeActivity", "CompanyInfo", "DealList", "InvestorProfile")

_ARROWS = {"up": "▲", "down": "▼", "flat": "→"}


class _Wire(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    def wire(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class ContentModel(_Wire, abc.ABC):
    """Base for renderable card payloads. ``wire()`` is the surface data
    model value; ``to_plain_text()`` is the mandatory text fallback sent to
    clients without A2UI capability (and used in tool-result folding)."""

    data_type: ClassVar[str]
    component: ClassVar[str]
    extended: ClassVar[bool] = False
    # Domain cards override with their own catalog id; surfaces never mix
    # catalogs (§5.4). The standard catalog is closed to new types.
    catalog_id: ClassVar[str] = CATALOG_ID

    @abc.abstractmethod
    def to_plain_text(self) -> str: ...


# ── shared fragments ──


class NameEmail(_Wire):
    name: str
    email: str


class DateRange(_Wire):
    """start/end keys — used by WaterfallChart and CalendarEvents.
    MultiCategoryChart uses first/last (FirstLastRange); frozen divergence."""

    start: str
    end: str


class FirstLastRange(_Wire):
    first: str
    last: str


# ── Core tier ──


class KpiTrend(_Wire):
    direction: Literal["up", "down", "flat"]
    delta: float | None = None
    delta_pct: float | None = None
    period: str | None = None


class MetricItem(_Wire):
    label: str
    value: float | int | str
    unit: str | None = None
    trend: Literal["up", "down", "flat"] | KpiTrend | None = None
    change_pct: float | None = None


class KpiCard(ContentModel):
    data_type: ClassVar[str] = "kpi_card"
    component: ClassVar[str] = "KpiCard"  # never "KPICard"

    metrics: list[MetricItem] = Field(min_length=1)
    title: str | None = None

    def to_plain_text(self) -> str:
        lines = [self.title] if self.title else []
        for m in self.metrics:
            unit = f" {m.unit}" if m.unit else ""
            lines.append(f"{m.label}: {m.value}{unit}")
            if isinstance(m.trend, KpiTrend):
                arrow = _ARROWS[m.trend.direction]
                bits = [arrow]
                if m.trend.delta_pct is not None:
                    bits.append(f"{m.trend.delta_pct:+.1f}%")
                elif m.trend.delta is not None:
                    bits.append(f"{m.trend.delta:+g}")
                if m.trend.period:
                    bits.append(m.trend.period)
                lines.append(f"  trend: {' '.join(bits)}")
            elif isinstance(m.trend, str):
                lines.append(f"  trend: {_ARROWS[m.trend]}")
        return "\n".join(lines)


class TimeSeriesDataPoint(_Wire):
    date: str
    value: float | None
    label: str | None = None
    series: str | None = None


class TimeSeriesSummary(_Wire):
    min: float | None = None
    max: float | None = None
    first: float | None = None
    last: float | None = None
    change_percent: float | None = None
    average: float | None = None


class SeriesMeta(_Wire):
    name: str
    points: list[dict[str, Any]] = Field(default_factory=list)


class TimeSeriesChart(ContentModel):
    data_type: ClassVar[str] = "time_series"
    component: ClassVar[str] = "TimeSeriesChart"

    chart_type: Literal["line", "area", "bar"]
    title: str
    subtitle: str | None = None
    x_key: str = "date"
    y_key: str = "value"
    x_label: str | None = None
    y_label: str | None = None
    data: list[TimeSeriesDataPoint]
    total_count: int = 0  # set by model_validator below
    summary: TimeSeriesSummary | None = None
    metadata: dict[str, Any] | None = None
    series: list[SeriesMeta] | None = None

    @model_validator(mode="before")
    @classmethod
    def _fill_total_count(cls, values: Any) -> Any:
        if isinstance(values, dict) and "total_count" not in values and "data" in values:
            data = values.get("data") or []
            values = dict(values)
            values["total_count"] = len(data) if isinstance(data, list) else 0
        return values

    def to_plain_text(self) -> str:
        lines = [self.title]
        if self.data:
            first, last = self.data[0], self.data[-1]
            lines.append(
                f"  {first.value} @ {first.date} → {last.value} @ {last.date} "
                f"({len(self.data)} points)"
            )
        return "\n".join(lines)


class ColumnDef(_Wire):
    key: str
    label: str
    type: str | None = None
    unit: str | None = None
    highlight: str | None = None


class ComparisonTable(ContentModel):
    data_type: ClassVar[str] = "comparison_table"
    component: ClassVar[str] = "ComparisonTable"

    title: str | None = None
    columns: list[ColumnDef]
    rows: list[dict[str, Any]]
    sort_by: str | None = None
    sort_order: Literal["asc", "desc"] | None = None

    def to_plain_text(self) -> str:
        header = " | ".join(c.label for c in self.columns)
        lines = [self.title, header, "-" * len(header)] if self.title else [header, "-" * len(header)]
        for row in self.rows:
            lines.append(" | ".join(str(row.get(c.key, "")) for c in self.columns))
        return "\n".join(lines)


class BarItem(_Wire):
    category: str
    value: float


class BarChart(ContentModel):
    data_type: ClassVar[str] = "bar_chart"
    component: ClassVar[str] = "BarChart"

    bars: list[BarItem]
    title: str | None = None
    x_key: str | None = None
    y_key: str | None = None

    def to_plain_text(self) -> str:
        lines = [self.title] if self.title else []
        lines += [f"  {b.category}: {b.value:g}" for b in self.bars]
        return "\n".join(lines)


class EntityItem(_Wire):
    id: str
    name: str
    summary: str | None = None


class EntityList(ContentModel):
    data_type: ClassVar[str] = "entity_list"
    component: ClassVar[str] = "EntityList"

    entity_type: str
    items: list[EntityItem]
    total_count: int | None = None
    has_more: bool | None = None
    title: str | None = None
    showing: int | None = None

    @model_validator(mode="after")
    def _fill_total_count(self) -> "EntityList":
        if self.total_count is None:
            self.total_count = len(self.items)
        return self

    def to_plain_text(self) -> str:
        lines = [self.title or f"{self.entity_type} list"]
        lines.append(f"  showing {self.showing or len(self.items)} of {self.total_count}")
        for item in self.items:
            lines.append(f"  - {item.name}")
            if item.summary:
                lines.append(f"      {item.summary}")
        return "\n".join(lines)


class BriefingKpiItem(_Wire):
    title: str
    value: float | int | str
    unit: str | None = None
    trend: Literal["up", "down", "flat"] | None = None
    delta: float | None = None


class KpiRowSection(_Wire):
    type: Literal["kpi_row"] = "kpi_row"
    items: list[BriefingKpiItem]


class ChartSection(_Wire):
    type: Literal["chart"] = "chart"
    chart_type: Literal["time_series", "bar_chart"]
    data: dict[str, Any] = Field(default_factory=dict)


class TableSection(_Wire):
    type: Literal["table"] = "table"
    data: dict[str, Any] = Field(default_factory=dict)


class TextSection(_Wire):
    type: Literal["text"] = "text"
    content: str


BriefingSection = Annotated[
    Union[KpiRowSection, ChartSection, TableSection, TextSection],
    Field(discriminator="type"),
]


class MarketBriefing(ContentModel):
    """Sole prose-exception type: the wire value is ``to_markdown()`` output
    (a markdown string), not this model's field dump. Renders without card
    chrome."""

    data_type: ClassVar[str] = "market_briefing"
    component: ClassVar[str] = "MarketBriefing"

    title: str
    as_of: str
    prose: str = ""
    sections: list[BriefingSection] = Field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [f"{self.title} ({self.as_of})"]
        if self.prose:
            lines.append(self.prose)
        for section in self.sections:
            if isinstance(section, KpiRowSection):
                for item in section.items:
                    bits = [f"  KPI {item.title}: {item.value}"]
                    if item.unit:
                        bits.append(item.unit)
                    if item.trend:
                        bits.append(_ARROWS[item.trend])
                    if item.delta is not None:
                        bits.append(f"{item.delta:+g}")
                    lines.append(" ".join(bits))
            elif isinstance(section, TextSection):
                lines.append(f"  {section.content}")
            elif isinstance(section, ChartSection):
                lines.append(f"  CHART ({section.chart_type}): {section.data.get('title', '')}")
            elif isinstance(section, TableSection):
                lines.append(f"  TABLE: {section.data.get('title', '')}")
        return "\n".join(lines)

    def to_plain_text(self) -> str:
        return self.to_markdown()


# ── Extended tier ──


class WaterfallSegment(_Wire):
    label: str
    value: float
    type: Literal["initial", "final", "inflow", "outflow", "gain", "loss", "subtotal"]
    cumulative: float
    tooltip: str | None = None


class WaterfallChart(ContentModel):
    data_type: ClassVar[str] = "waterfall_chart"
    component: ClassVar[str] = "WaterfallChart"
    extended: ClassVar[bool] = True

    title: str
    segments: list[WaterfallSegment]
    subtitle: str | None = None
    currency: str | None = None
    entity_name: str | None = None
    as_of_date: str | None = None
    date_range: DateRange | None = None  # start/end — frozen; not first/last

    def to_plain_text(self) -> str:
        lines = [self.title]
        lines += [
            f"  {s.label}: {s.value:+g} → {s.cumulative:g} ({s.type})"
            for s in self.segments
        ]
        return "\n".join(lines)


class CategoryValue(_Wire):
    value: float
    count: int | None = None
    metadata: dict[str, Any] | None = None


class MultiCategoryPeriod(_Wire):
    period: str
    categories: dict[str, CategoryValue]
    period_total: float | None = None


class MultiCategorySummary(_Wire):
    by_category: dict[str, CategoryValue]
    grand_total: float | None = None
    period_count: int


class MultiCategoryChartConfig(_Wire):
    show_total_line: bool | None = None
    stack_bars: bool | None = None
    show_cumulative: bool | None = None
    category_colors: dict[str, str] | None = None


class MultiCategoryChart(ContentModel):
    data_type: ClassVar[str] = "multi_category_chart"
    component: ClassVar[str] = "MultiCategoryChart"
    extended: ClassVar[bool] = True

    title: str
    periods: list[MultiCategoryPeriod]
    summary: MultiCategorySummary
    date_range: FirstLastRange  # first/last — frozen; not start/end
    subtitle: str | None = None
    unit_label: str | None = None
    currency: str | None = None
    entity_name: str | None = None
    item_count: int | None = None
    chart_config: MultiCategoryChartConfig | None = None

    def to_plain_text(self) -> str:
        lines = [self.title]
        for p in self.periods:
            cats = ", ".join(f"{k}={v.value:g}" for k, v in p.categories.items())
            lines.append(f"  {p.period}: {cats}")
        return "\n".join(lines)


class Money(_Wire):
    amount: float | None = None
    currency: str | None = None  # renderer defaults to USD when absent


class FundPerformance(ContentModel):
    """Sole camelCase-wire type. Attributes are snake_case with camelCase
    aliases; ``wire()`` (by_alias + exclude_none) is the only conformant
    serialization — snake_case keys must never reach the wire."""

    data_type: ClassVar[str] = "fund_performance"
    component: ClassVar[str] = "FundPerformance"
    extended: ClassVar[bool] = True

    fund_name: str | None = Field(default=None, alias="fundName")
    pb_id: str | None = Field(default=None, alias="pbId")
    as_of_date: str | None = Field(default=None, alias="asOfDate")
    irr: float | None = None
    tvpi: float | None = None
    dpi: float | None = None
    rvpi: float | None = None
    net_irr: float | None = Field(default=None, alias="netIrr")
    gross_irr: float | None = Field(default=None, alias="grossIrr")
    moic: float | None = None
    quartile: int | None = None
    nav: Money | None = None
    as_of_quarter: int | None = Field(default=None, alias="asOfQuarter")
    as_of_year: int | None = Field(default=None, alias="asOfYear")
    called_down_pct: float | None = Field(default=None, alias="calledDownPct")
    dry_powder: Money | None = Field(default=None, alias="dryPowder")
    dry_powder_pct: float | None = Field(default=None, alias="dryPowderPct")
    distributed: Money | None = None
    remaining_value: Money | None = Field(default=None, alias="remainingValue")
    distributed_plus_remaining: Money | None = Field(
        default=None, alias="distributedPlusRemaining"
    )

    def to_plain_text(self) -> str:
        bits: list[str] = []
        if self.fund_name:
            bits.append(self.fund_name)
        if self.irr is not None:
            bits.append(f"IRR={self.irr:.1%}")
        if self.tvpi is not None:
            bits.append(f"TVPI={self.tvpi:.2f}x")
        if self.dpi is not None:
            bits.append(f"DPI={self.dpi:.2f}x")
        if self.moic is not None:
            bits.append(f"MOIC={self.moic:.2f}x")
        if self.nav and self.nav.amount is not None:
            bits.append(f"NAV={self.nav.amount:,.0f} {self.nav.currency or 'USD'}")
        if self.as_of_date:
            bits.append(f"as of {self.as_of_date}")
        return " | ".join(bits) or "fund performance (no data)"


class EmailMessage(_Wire):
    id: str
    conversation_id: str | None = None
    subject: str
    preview: str
    from_: NameEmail = Field(alias="from")
    to_recipients: list[NameEmail]
    received_at: str  # ISO 8601 UTC, trailing Z
    is_read: bool
    has_attachments: bool = False
    importance: Literal["low", "normal", "high"] = "normal"
    flag_status: Literal["notFlagged", "flagged", "complete"] | None = None
    web_link: str


class EmailList(ContentModel):
    data_type: ClassVar[str] = "email_list"
    component: ClassVar[str] = "EmailList"
    extended: ClassVar[bool] = True

    messages: list[EmailMessage]
    total_count: int
    has_more: bool
    folder: str | None = None
    query: str | None = None

    def to_plain_text(self) -> str:
        lines = [f"{self.total_count} message(s)"]
        for m in self.messages:
            unread = "[unread] " if not m.is_read else ""
            lines.append(f"  {unread}{m.received_at} | {m.from_.email} | {m.subject}")
            if m.preview:
                lines.append(f"    {m.preview}")
        return "\n".join(lines)


class EventLocation(_Wire):
    display_name: str | None = None
    is_online: bool | None = None
    join_url: str | None = None


class CalendarEvent(_Wire):
    id: str
    subject: str
    start: str  # UTC ISO 8601, trailing Z; renderer owns locale
    end: str
    is_all_day: bool = False
    is_cancelled: bool = False
    is_recurring: bool = False
    organizer: NameEmail
    location: EventLocation | None = None
    attendees_count: int = 0
    response_status: Literal["accepted", "tentative", "declined", "none"] | None = None
    importance: Literal["low", "normal", "high"] = "normal"
    show_as: Literal[
        "free", "tentative", "busy", "oof", "workingElsewhere", "unknown"
    ] = "unknown"
    web_link: str
    is_online: bool | None = None


class CalendarEvents(ContentModel):
    data_type: ClassVar[str] = "calendar_events"
    component: ClassVar[str] = "CalendarEvents"
    extended: ClassVar[bool] = True

    events: list[CalendarEvent]
    date_range: DateRange  # start/end — frozen
    total_count: int
    has_more: bool

    def to_plain_text(self) -> str:
        lines = [f"{self.total_count} event(s) {self.date_range.start} – {self.date_range.end}"]
        for e in self.events:
            loc = ""
            if e.location and e.location.display_name:
                loc = f" @ {e.location.display_name}"
            online = " [online]" if (e.is_online or (e.location and e.location.is_online)) else ""
            lines.append(f"  {e.start} – {e.end}: {e.subject}{loc}{online}")
        return "\n".join(lines)


_AVAILABILITY = Literal[
    "available", "busy", "doNotDisturb", "beRightBack", "away", "offline",
    "presenceunknown", "outofoffice", "inacall", "inapresentationoracall",
    "presenting", "focusing", "urgentinterruptionsonly",
]


class UserPresence(_Wire):
    availability: _AVAILABILITY
    activity: str
    status_message: str | None = None


class OutOfOfficeSettings(_Wire):
    is_enabled: bool
    start_date: str | None = None
    end_date: str | None = None
    internal_message: str | None = None
    external_message: str | None = None


class ManagerRef(_Wire):
    id: str
    display_name: str
    email: str
    job_title: str | None = None


class UserProfile(ContentModel):
    data_type: ClassVar[str] = "user_profile"
    component: ClassVar[str] = "UserProfile"
    extended: ClassVar[bool] = True

    id: str
    display_name: str
    email: str
    given_name: str | None = None
    surname: str | None = None
    job_title: str | None = None
    department: str | None = None
    office_location: str | None = None
    mobile_phone: str | None = None
    business_phones: list[str] = Field(default_factory=list)
    manager: ManagerRef | None = None
    presence: UserPresence | None = None
    photo_url: str | None = None
    out_of_office: OutOfOfficeSettings | None = None

    def to_plain_text(self) -> str:
        lines = [f"{self.display_name} <{self.email}>"]
        if self.job_title:
            lines.append(f"  {self.job_title}" + (f", {self.department}" if self.department else ""))
        if self.presence:
            lines.append(f"  presence: {self.presence.availability}")
        if self.manager:
            lines.append(f"  manager: {self.manager.display_name} <{self.manager.email}>")
        return "\n".join(lines)


class UserSummary(_Wire):
    id: str
    display_name: str
    email: str
    job_title: str | None = None
    department: str | None = None
    presence: UserPresence | None = None


class UserList(ContentModel):
    data_type: ClassVar[str] = "user_list"
    component: ClassVar[str] = "UserList"
    extended: ClassVar[bool] = True

    users: list[UserSummary]
    total_count: int
    has_more: bool
    query: str | None = None

    def to_plain_text(self) -> str:
        lines = [f"{self.total_count} user(s)"]
        for u in self.users:
            title = f" — {u.job_title}" if u.job_title else ""
            lines.append(f"  {u.display_name} <{u.email}>{title}")
        return "\n".join(lines)


class DocumentItem(_Wire):
    id: str
    name: str
    type: str | None = None
    modified: str | None = None
    link: str | None = None
    size: float | None = None
    web_url: str | None = None
    last_modified: str | None = None
    modified_by: str | None = None


class DocumentList(ContentModel):
    data_type: ClassVar[str] = "document_list"
    component: ClassVar[str] = "DocumentList"
    extended: ClassVar[bool] = True

    documents: list[DocumentItem]
    total_count: int | None = None
    has_more: bool | None = None

    @model_validator(mode="after")
    def _fill_total_count(self) -> "DocumentList":
        if self.total_count is None:
            self.total_count = len(self.documents)
        return self

    def to_plain_text(self) -> str:
        lines = [f"{self.total_count} document(s)"]
        for d in self.documents:
            when = d.last_modified or d.modified
            suffix = f" (modified {when})" if when else ""
            lines.append(f"  {d.name}{suffix}")
        return "\n".join(lines)


# ── registry ──

_REGISTRY: dict[str, type[ContentModel]] = {}
_PROFILE_SEALED = False


def register_content_type(cls: type[ContentModel]) -> type[ContentModel]:
    """Register a card type (SDK profile types at import; agents for domain
    cards). Validates the frozen-name and uniqueness rules."""
    if not (isinstance(cls, type) and issubclass(cls, ContentModel)):
        raise TypeError("content type must subclass ContentModel")
    data_type = getattr(cls, "data_type", None)
    component = getattr(cls, "component", None)
    if not data_type or not component:
        raise TypeError(f"{cls.__name__} must declare data_type and component")
    if component in RESERVED_COMPONENTS:
        raise ValueError(
            f"component name {component!r} is RESERVED in Standard Profile v1 "
            f"(no field contract exists; do not emit a presumed shape)"
        )
    if cls.catalog_id == CATALOG_ID and _PROFILE_SEALED and cls not in PROFILE_TYPES:
        raise ValueError(
            "the standard catalog is FROZEN — domain cards must declare their "
            "own catalog_id (see the extension docs)"
        )
    # Wire component names must be GLOBALLY unique: A2UI resolves a component by
    # its bare PascalCase name with no catalog qualifier, so two types sharing a
    # name would silently shadow on the wire. Same-class re-registration is a
    # no-op (identity check), matching the data_type rule below.
    component_owner = next(
        (owner for owner in _REGISTRY.values() if owner.component == component),
        None,
    )
    if component_owner is not None and component_owner is not cls:
        raise ValueError(
            f"component name {component!r} already registered by "
            f"{component_owner.__name__} — wire component names must be globally "
            f"unique (A2UI resolves by bare componentType, not by catalogId)"
        )
    existing = _REGISTRY.get(data_type)
    if existing is not None and existing is not cls:
        raise ValueError(f"data_type {data_type!r} already registered by {existing.__name__}")
    _REGISTRY[data_type] = cls
    return cls


def content_type_for(data_type: str) -> type[ContentModel] | None:
    return _REGISTRY.get(data_type)


def registered_content_types() -> dict[str, type[ContentModel]]:
    return dict(_REGISTRY)


PROFILE_TYPES: tuple[type[ContentModel], ...] = (
    KpiCard,
    TimeSeriesChart,
    ComparisonTable,
    BarChart,
    EntityList,
    MarketBriefing,
    WaterfallChart,
    MultiCategoryChart,
    FundPerformance,
    EmailList,
    CalendarEvents,
    UserProfile,
    UserList,
    DocumentList,
)

for _cls in PROFILE_TYPES:
    register_content_type(_cls)
_PROFILE_SEALED = True
