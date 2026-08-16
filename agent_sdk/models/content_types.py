"""A2UI Standard Profile v1 content models (FROZEN — DESIGN.md §5.4).

Wire-isomorphic Pydantic models for the 14 FROZEN Profile types plus the
registry that the translator, catalog and console all read (Standard Profile
v1 = 14 FROZEN + 4 RESERVED names at RESERVED_COMPONENTS — 18 total). Field
contracts
are frozen at catalog ``urn:a2ui-profile:standard:v1`` — do not "fix"
inconsistencies (e.g. the two different date_range key pair shapes); they are
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
import math
from typing import Annotated, Any, ClassVar, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializerFunctionWrapHandler,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from ..common.redact import (
    safe_block_text,
    safe_cell_text,
)

CATALOG_ID = "urn:a2ui-profile:standard:v1"
A2UI_VERSION = "v0.9.1"
A2UI_EXTENSION_URI = "https://a2ui.org/a2a-extension/a2ui/v0.9.1"
A2UI_MIME_TYPE = "application/a2ui+json"

RESERVED_COMPONENTS = ("TradeActivity", "CompanyInfo", "DealList", "InvestorProfile")

_ARROWS = {"up": "▲", "down": "▼", "flat": "→"}


# GH-130 / RT-002 — SEPARATOR ALPHABET, and the cell sanitiser that applies it,
# now live in the shared C-007 redaction family at agent_sdk/common/redact.py and
# are re-exported here.
#
# They were module-private (`_BARE_SEPARATORS`, `_SPACED_SEPARATORS`,
# `_SPACED_SEPARATOR_RE`, `_sanitize_cell`) while the delimiter-safety contract
# below declared them MANDATORY for third-party domain cards outside this module —
# a rule downstream code could satisfy only by hand-rebuilding the alphabet, which
# is exactly the divergent second copy C-007 exists to prevent, and which four
# consecutive review rounds proved nobody gets right by hand (each round found one
# more uncovered separator). The obligation and the helper that discharges it now
# ship together: `agent_sdk.safe_cell_text`.
#
# The names are re-imported above rather than redefined so this module and
# tests/test_content_types.py's completeness guards keep reading ONE alphabet.

# Punctuation the renderers emit that is deliberately NOT neutralised, with the
# reason it cannot fabricate a boundary. test_content_types.py asserts this set and
# the separator maps together account for every punctuation character appearing in a
# renderer template, so a future renderer that introduces a genuinely new separator
# fails the build instead of shipping. Stays here, not in redact.py: it describes
# THIS module's renderer templates, not the shared alphabet.
_NON_SEPARATOR_GLYPHS = frozenset("-+%./")


def _sanitize_cell(value: str) -> str:
    """Thin alias for the public :func:`agent_sdk.common.redact.safe_cell_text`
    (RT-002) — kept as the in-module name every renderer below calls, and as the
    token tests/test_content_types.py's per-renderer enforcement greps for.

    All behaviour, and the reasoning behind the separator alphabet, live on
    ``safe_cell_text``. Do not reimplement either here: a second copy is the exact
    failure this promotion removed. See the delimiter-safety contract on
    ``ContentModel``."""
    return safe_cell_text(value)


def _sanitize_block(value: str) -> str:
    """Neutralise control/escape characters inside an untrusted string that is
    rendered as a MULTI-LINE MARKDOWN BLOCK, preserving newlines and ``|``
    (RT-001).

    The counterpart to :func:`_sanitize_cell`, and the correct helper for
    exactly two fields: ``MarketBriefing.prose`` and ``TextSection.content``.
    Those are the only free-form strings in this module whose declared
    contract is a markdown *document* rather than a value interpolated into a
    delimited line — ``MarketBriefing`` is the SDK's sole prose-exception type
    and its ``to_markdown()`` output IS the wire value (a2ui/translator.py,
    routes/mcp.py). Running them through ``_sanitize_cell`` collapses every
    newline to a space and rewrites ``|`` to ``/``, which destroys headings,
    lists, paragraphs and markdown tables in the one payload that is supposed
    to carry them. Delimiter fabrication is not a threat for these fields:
    ``to_markdown()`` joins *sections*, and nothing downstream re-parses the
    rendered text positionally."""
    return safe_block_text(value)


_ASSERT_FINITE_MAX_DEPTH = 100


def _assert_finite(value: Any, _depth: int = 0) -> None:
    """Reject inf/-inf/nan anywhere in ``value``, recursing into dict/list/tuple
    and nested pydantic ``BaseModel`` instances. ``model_dump_json()`` serializes
    non-finite floats as JSON ``null`` while ``to_markdown()``/``to_plain_text()``
    render ``"inf"``/``"nan"`` literally — allowing them through would silently
    split a dual-part artifact into two different values.

    Scope (GH-95, MarketBriefing family only — see that issue's AC): callers
    are the field validators on ``BriefingKpiItem.value``/``.delta`` and
    ``ChartSection.data``/``TableSection.data``. It is not a general SDK-wide
    guard; other ``_Wire``/``ContentModel`` fields intentionally accept
    non-finite floats unless a future issue scopes them in explicitly.

    ``_depth`` bounds worst-case recursion (RT-003): a cyclic or pathologically
    deep dict/list/tuple/BaseModel structure surfaces as a clean ValueError
    (pydantic wraps it into a ValidationError) instead of an uncaught
    RecursionError, which is a RuntimeError pydantic does not convert."""
    if _depth > _ASSERT_FINITE_MAX_DEPTH:
        raise ValueError("value nesting too deep to validate (possible cyclic structure)")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError(f"non-finite float not allowed: {value!r}")
    if isinstance(value, BaseModel):
        for v in value.__dict__.values():
            _assert_finite(v, _depth + 1)
    elif isinstance(value, dict):
        for v in value.values():
            _assert_finite(v, _depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _assert_finite(v, _depth + 1)


class _Wire(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    def wire(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class ContentModel(_Wire, abc.ABC):
    """Base for renderable card payloads. ``wire()`` is the surface data
    model value; ``to_plain_text()`` is the mandatory text fallback sent to
    clients without A2UI capability (and used in tool-result folding).

    Delimiter-safety contract (GH-130). ``to_plain_text()``/``to_markdown()``
    interpolate untrusted field values into a delimited render — columns
    joined with ``" | "``, entries joined with ``"\\n"``, and a dozen
    renderer-owned separators besides (``": "``, ``", "``, ``"="``, the
    ``<email>``/``(type)``/``[unread]`` pairs, the ``" – "``/``" — "``/
    ``" @ "``/``" → "`` joiners). EVERY such value MUST go through
    ``_sanitize_cell`` (SDK renderers) or, for domain subclasses outside this
    module, the identical public helper it aliases:
    ``agent_sdk.safe_cell_text(value)`` (RT-002 — exported from the package
    root and from ``agent_sdk.common.redact``).

    Do NOT satisfy this with ``safe_error_text`` plus a hand-written separator
    translation. ``safe_error_text`` performs NO separator neutralisation at
    all — it only collapses line breaks and controls — so a domain card that
    follows that recipe is still wide open to the ``<``/``>``/``(``/``)``/
    ``=``/``|`` identity-fabrication attacks GH-130 closed, and a hand-written
    alphabet is the divergent second copy the component registry exists to
    prevent (four consecutive review rounds each missed one more separator
    doing exactly that). One call, one alphabet, one place to fix.

    Without it a single attacker-controlled cell fabricates a boundary and one
    field renders as two: a ``|`` invents a column, a ``str.splitlines()``
    break (not just CR/LF — also VT, FF, NEL, U+2028/U+2029) invents a row, a
    ``<`` invents a second ``name <email>`` identity, a ``,``/``=`` invents a
    second category/value pair. The reader — human or model — sees a record
    that does not exist. This applies to every untrusted free-form ``str``
    interpolated into a render, including a card's own ``title``/
    ``entity_type``/``as_of``, and to untrusted **dict keys** such as
    ``MultiCategoryPeriod.categories`` (a lookup key is still attacker-shaped
    text once rendered). Only ``Literal``-typed enum fields are exempt,
    because pydantic has already constrained them to a fixed alphabet.

    ACCEPTED RESIDUAL (RT-010): ``_sanitize_cell`` neutralises a compact
    (non-whitespace-adjacent) ``,``/``:``/``–``/``—``/``→`` unless it sits
    between two ASCII digits (preserving genuine numeric literals, ranges, and
    timestamps — ``"1,234"``, ``"09:30"``). ``@`` alone keeps a narrower,
    intentionally-not-closed exception: a compact ``@`` between letters survives
    unneutralised anywhere it appears, because that shape is indistinguishable
    at the value level from a real email address, which the SDK's own renderers
    depend on surviving intact. A hostile compact ``@`` planted in a field that
    is *not* an email (e.g. a location name) can therefore still read as the
    ``" @ "`` joiner to a naive reader — closing that would require per-field
    type information this value-level helper does not have. See
    ``agent_sdk.common.redact``'s module comment for the full rationale.

    COMPLETENESS IS ENFORCED, NOT DELEGATED. ``_sanitize_cell`` applies the
    entire separator alphabet (``_BARE_SEPARATORS`` plus the boundary-aware
    ``_SPACED_SEPARATORS``) unconditionally,
    so a renderer cannot be delimiter-unsafe by omission and a new renderer
    inherits the guarantee without its author knowing the rule exists. Two
    tests in ``tests/test_content_types.py`` keep that true from both
    directions, and they — not reviewer diligence — are what close this class:

    - ``test_every_renderer_separator_is_neutralised`` parses this module's
      renderer templates and fails if any punctuation they insert is neither
      in ``_STRUCTURAL_SEPARATORS`` nor in the documented
      ``_NON_SEPARATOR_GLYPHS`` allow-list. A future renderer that introduces
      a new separator breaks the build.
    - ``test_untrusted_value_cannot_alter_render_structure`` drives every
      registered ``ContentModel`` with a hostile payload in every string
      field and asserts the render's separator counts are identical to a
      benign render. A renderer that forgets ``_sanitize_cell`` on some field
      breaks the build.

    Do not reintroduce per-renderer opt-in. The earlier design, in which each
    renderer passed the subset of delimiters it used via ``extra=``, produced
    four consecutive review rounds that each found one more uncovered
    renderer/delimiter pair — the completeness obligation has to sit in one
    place a test can check, not at ~25 call sites.

    RT-001 carve-out — MULTI-LINE MARKDOWN FIELDS: the rule above is scoped to
    values interpolated into a *delimited single-line* render. A field whose
    declared contract is a markdown *document* must NOT be routed through
    ``safe_error_text``/``_sanitize_cell``: there a newline is the payload's
    own structure and ``|`` is table syntax, so collapsing them destroys the
    very content the field exists to carry, and no delimiter is fabricated
    because nothing re-parses the result positionally. Such fields use
    ``agent_sdk.common.redact.safe_block_text`` (the ``_sanitize_block``
    wrapper in this module), which preserves ``\\n``/``\\t``/``|`` while still
    neutralising ANSI/terminal escape introducers and the rest of C0/DEL/C1.
    In this module that is exactly ``MarketBriefing.prose`` and
    ``TextSection.content`` — the sole prose-exception type, whose
    ``to_markdown()`` output IS the A2A/AG-UI DataPart value and the MCP
    ``structuredContent`` markdown payload. Choose the helper by the FIELD's
    contract, never by the enclosing method's name."""

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

    @field_serializer("trend")
    def _serialize_trend(
        self, trend: "Literal['up', 'down', 'flat'] | KpiTrend | None"
    ) -> "str | None":
        """Wire contract: trend is always a direction string or absent — never a
        KpiTrend object dict. KpiTrend instances are collapsed to their direction
        field here so that third-party renderers following Standard Profile v1
        receive the frozen contract shape."""
        if isinstance(trend, KpiTrend):
            return trend.direction
        return trend

    @field_validator("value", mode="before")
    @classmethod
    def _reject_non_scalar(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError(
                "MetricItem.value does not accept bool (would silently coerce to 0/1). "
                "Use from_any() to skip non-scalar values gracefully."
            )
        if not isinstance(v, (int, float, str)):
            raise ValueError(
                f"MetricItem.value must be int, float, or str; got {type(v).__name__}. "
                "Use from_any() to skip non-scalar values gracefully."
            )
        return v

    @classmethod
    def from_any(
        cls,
        label: str,
        value: Any,
        *,
        unit: str | None = None,
        trend: Any = None,
        change_pct: float | None = None,
    ) -> "MetricItem | None":
        """Return None instead of raising when value is non-scalar or bool.

        Replaces the repetitive ``isinstance(v, (int, float, str)) and not
        isinstance(v, bool)`` guard that domain ``wire()`` methods would otherwise
        need at every projection site.
        """
        try:
            return cls(label=label, value=value, unit=unit, trend=trend, change_pct=change_pct)
        except (ValueError, TypeError):
            return None


class KpiCard(ContentModel):
    data_type: ClassVar[str] = "kpi_card"
    component: ClassVar[str] = "KpiCard"  # never "KPICard"

    metrics: list[MetricItem] = Field(min_length=1)
    title: str | None = None
    metadata: dict[str, Any] | None = None

    def to_plain_text(self) -> str:
        lines = [_sanitize_cell(self.title)] if self.title else []
        for m in self.metrics:
            unit = f" {_sanitize_cell(m.unit)}" if m.unit else ""
            lines.append(f"{_sanitize_cell(m.label)}: {_sanitize_cell(str(m.value))}{unit}")
            if isinstance(m.trend, KpiTrend):
                arrow = _ARROWS[m.trend.direction]
                bits = [arrow]
                if m.trend.delta_pct is not None:
                    bits.append(f"{m.trend.delta_pct:+.1f}%")
                elif m.trend.delta is not None:
                    bits.append(f"{m.trend.delta:+g}")
                if m.trend.period:
                    bits.append(_sanitize_cell(m.trend.period))
                lines.append(f"  trend: {' '.join(bits)}")
            elif isinstance(m.trend, str):
                lines.append(f"  trend: {_ARROWS[m.trend]}")
        return "\n".join(lines)


class TimeSeriesDataPoint(_Wire):
    date: str
    value: float | None
    label: str | None = None
    # series is intentionally NOT on the wire: Standard Profile v1 data points
    # are {date, value, label?} only. Store it for Python-side grouping only.
    series: str | None = Field(default=None, exclude=True)

    @model_serializer(mode="wrap")
    def _wire_value(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """``value`` is required-but-nullable on the frozen time_series contract
        (a data gap is a real point, not an absent one) — unlike ``label``, which
        is genuinely optional. ``_Wire.wire()``'s blanket ``exclude_none=True``
        can't distinguish the two, so re-insert ``value: null`` here when the
        field was actually ``None`` (LRN-110)."""
        data = handler(self)
        if self.value is None:
            data["value"] = None
        return data


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
    # series is NOT on the wire: Profile v1 time_series has no top-level series
    # field. Store it for Python-side multi-series grouping only.
    series: list[SeriesMeta] | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _fill_total_count(cls, values: Any) -> Any:
        if isinstance(values, dict) and "total_count" not in values and "data" in values:
            data = values.get("data") or []
            values = dict(values)
            values["total_count"] = len(data) if isinstance(data, list) else 0
        return values

    def to_plain_text(self) -> str:
        lines = [_sanitize_cell(self.title)]
        if self.data:
            first, last = self.data[0], self.data[-1]
            fv = first.value if first.value is not None else "N/A"
            lv = last.value if last.value is not None else "N/A"
            first_date = _sanitize_cell(first.date)
            last_date = _sanitize_cell(last.date)
            lines.append(
                f"  {fv} @ {first_date} → "
                f"{lv} @ {last_date} "
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
    metadata: dict[str, Any] | None = None

    def to_plain_text(self) -> str:
        header = " | ".join(_sanitize_cell(c.label) for c in self.columns)
        lines = (
            [_sanitize_cell(self.title), header, "-" * len(header)]
            if self.title
            else [header, "-" * len(header)]
        )
        for row in self.rows:
            lines.append(
                " | ".join(_sanitize_cell(str(row.get(c.key, ""))) for c in self.columns)
            )
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
    metadata: dict[str, Any] | None = None

    def to_plain_text(self) -> str:
        lines = [_sanitize_cell(self.title)] if self.title else []
        lines += [f"  {_sanitize_cell(b.category)}: {b.value:g}" for b in self.bars]
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
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _fill_total_count(self) -> "EntityList":
        if self.total_count is None:
            self.total_count = len(self.items)
        return self

    def to_plain_text(self) -> str:
        heading = (
            _sanitize_cell(self.title)
            if self.title
            else _sanitize_cell(f"{self.entity_type} list")
        )
        lines = [heading]
        lines.append(f"  showing {self.showing or len(self.items)} of {self.total_count}")
        for item in self.items:
            lines.append(f"  - {_sanitize_cell(item.name)}")
            if item.summary:
                lines.append(f"      {_sanitize_cell(item.summary)}")
        return "\n".join(lines)


class BriefingKpiItem(_Wire):
    title: str
    value: float | int | str
    unit: str | None = None
    trend: Literal["up", "down", "flat"] | None = None
    delta: float | None = None

    @field_validator("value", "delta")
    @classmethod
    def _reject_non_finite(cls, v: Any) -> Any:
        _assert_finite(v)
        return v


class KpiRowSection(_Wire):
    type: Literal["kpi_row"] = "kpi_row"
    items: list[BriefingKpiItem]


class ChartSection(_Wire):
    type: Literal["chart"] = "chart"
    chart_type: Literal["time_series", "bar_chart"]
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def _reject_non_finite_data(cls, v: dict[str, Any]) -> dict[str, Any]:
        _assert_finite(v)
        return v


class TableSection(_Wire):
    type: Literal["table"] = "table"
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def _reject_non_finite_data(cls, v: dict[str, Any]) -> dict[str, Any]:
        _assert_finite(v)
        return v


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
    metadata: dict[str, Any] | None = None

    def to_markdown(self) -> str:
        title = _sanitize_cell(self.title)
        as_of = _sanitize_cell(self.as_of)
        lines = [f"{title} ({as_of})"]
        if self.prose:
            lines.append(_sanitize_block(self.prose))
        for section in self.sections:
            if isinstance(section, KpiRowSection):
                for item in section.items:
                    bits = [f"  KPI {_sanitize_cell(item.title)}: {_sanitize_cell(str(item.value))}"]
                    if item.unit:
                        bits.append(_sanitize_cell(item.unit))
                    if item.trend:
                        bits.append(_ARROWS[item.trend])
                    if item.delta is not None:
                        bits.append(f"{item.delta:+g}")
                    lines.append(" ".join(bits))
            elif isinstance(section, TextSection):
                lines.append(f"  {_sanitize_block(section.content)}")
            elif isinstance(section, ChartSection):
                title = _sanitize_cell(str(section.data.get("title", "")))
                lines.append(f"  CHART ({section.chart_type}): {title}")
            elif isinstance(section, TableSection):
                title = _sanitize_cell(str(section.data.get("title", "")))
                lines.append(f"  TABLE: {title}")
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
    metadata: dict[str, Any] | None = None

    def to_plain_text(self) -> str:
        lines = [_sanitize_cell(self.title)]
        lines += [
            f"  {_sanitize_cell(s.label)}: "
            f"{s.value:+g} → {s.cumulative:g} ({s.type})"
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
    metadata: dict[str, Any] | None = None

    def to_plain_text(self) -> str:
        lines = [_sanitize_cell(self.title)]
        for p in self.periods:
            cats = ", ".join(
                f"{_sanitize_cell(k)}={v.value:g}" for k, v in p.categories.items()
            )
            lines.append(f"  {_sanitize_cell(p.period)}: {cats}")
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
    metadata: dict[str, Any] | None = None

    def to_plain_text(self) -> str:
        bits: list[str] = []
        if self.fund_name:
            bits.append(_sanitize_cell(self.fund_name))
        if self.irr is not None:
            bits.append(f"IRR={self.irr:.1%}")
        if self.tvpi is not None:
            bits.append(f"TVPI={self.tvpi:.2f}x")
        if self.dpi is not None:
            bits.append(f"DPI={self.dpi:.2f}x")
        if self.moic is not None:
            bits.append(f"MOIC={self.moic:.2f}x")
        if self.nav and self.nav.amount is not None:
            currency = _sanitize_cell(self.nav.currency or "USD")
            bits.append(f"NAV={self.nav.amount:,.0f} {currency}")
        if self.as_of_date:
            bits.append(f"as of {_sanitize_cell(self.as_of_date)}")
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
    metadata: dict[str, Any] | None = None

    def to_plain_text(self) -> str:
        lines = [f"{self.total_count} message(s)"]
        for m in self.messages:
            unread = "[unread] " if not m.is_read else ""
            lines.append(
                f"  {unread}{_sanitize_cell(m.received_at)} | "
                f"{_sanitize_cell(m.from_.email)} | {_sanitize_cell(m.subject)}"
            )
            if m.preview:
                lines.append(f"    {_sanitize_cell(m.preview)}")
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
    metadata: dict[str, Any] | None = None

    def to_plain_text(self) -> str:
        start = _sanitize_cell(self.date_range.start)
        end = _sanitize_cell(self.date_range.end)
        lines = [f"{self.total_count} event(s) {start} – {end}"]
        for e in self.events:
            loc = ""
            if e.location and e.location.display_name:
                loc_name = _sanitize_cell(
                    e.location.display_name
                )
                loc = f" @ {loc_name}"
            online = " [online]" if (e.is_online or (e.location and e.location.is_online)) else ""
            e_start = _sanitize_cell(e.start)
            e_end = _sanitize_cell(e.end)
            subject = _sanitize_cell(e.subject)
            lines.append(f"  {e_start} – {e_end}: {subject}{loc}{online}")
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
    metadata: dict[str, Any] | None = None

    def to_plain_text(self) -> str:
        name = _sanitize_cell(self.display_name)
        email = _sanitize_cell(self.email)
        lines = [f"{name} <{email}>"]
        if self.job_title:
            dept = (
                f", {_sanitize_cell(self.department)}"
                if self.department
                else ""
            )
            lines.append(
                f"  {_sanitize_cell(self.job_title)}{dept}"
            )
        if self.presence:
            lines.append(f"  presence: {self.presence.availability}")
        if self.manager:
            manager_name = _sanitize_cell(self.manager.display_name)
            manager_email = _sanitize_cell(self.manager.email)
            lines.append(f"  manager: {manager_name} <{manager_email}>")
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
    metadata: dict[str, Any] | None = None

    def to_plain_text(self) -> str:
        lines = [f"{self.total_count} user(s)"]
        for u in self.users:
            title = (
                f" — {_sanitize_cell(u.job_title)}"
                if u.job_title
                else ""
            )
            name = _sanitize_cell(u.display_name)
            email = _sanitize_cell(u.email)
            lines.append(f"  {name} <{email}>{title}")
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
    metadata: dict[str, Any] | None = None

    @model_validator(mode="after")
    def _fill_total_count(self) -> "DocumentList":
        if self.total_count is None:
            self.total_count = len(self.documents)
        return self

    def to_plain_text(self) -> str:
        lines = [f"{self.total_count} document(s)"]
        for d in self.documents:
            doc_type = _sanitize_cell(d.type) if d.type else ""
            type_suffix = f" ({doc_type})" if d.type else ""
            when = d.last_modified or d.modified
            date_suffix = (
                f"  {_sanitize_cell(when)}" if when else ""
            )
            name = _sanitize_cell(d.name)
            lines.append(f"  {name}{type_suffix}{date_suffix}")
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
