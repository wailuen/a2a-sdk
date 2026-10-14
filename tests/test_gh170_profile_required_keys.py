"""GH-170: keys the compact schema marks required must be keys the model always emits.

The required-key table below is the A2UI Standard Profile v1.1 field contract
(a2ui-advisor). A schema that marks a key optional while the Profile requires
it, or a model that drops a required key from ``wire()``, fails here.
"""
from __future__ import annotations

from typing import Any

import pytest

from agent_sdk.a2ui.catalog import _COMPACT_SCHEMAS
from tests._compact_schema import emitted_paths, parse_schema, required_paths
from agent_sdk.models.content_types import (
    BarChart,
    CalendarEvent,
    CalendarEvents,
    CategoryValue,
    ColumnDef,
    ComparisonTable,
    DateRange,
    DocumentItem,
    DocumentList,
    EmailList,
    EmailMessage,
    EntityItem,
    EntityList,
    EventLocation,
    FirstLastRange,
    FundPerformance,
    KpiCard,
    ManagerRef,
    MetricItem,
    Money,
    MultiCategoryChart,
    MultiCategoryPeriod,
    MultiCategorySummary,
    NameEmail,
    OutOfOfficeSettings,
    TimeSeriesChart,
    TimeSeriesDataPoint,
    UserList,
    UserPresence,
    UserProfile,
    UserSummary,
    WaterfallChart,
    WaterfallSegment,
    BarItem,
)

_NE = NameEmail(name="n", email="e")
_PRESENCE = UserPresence(availability="available", activity="Available")

# Standard Profile v1.1 required keys; nested object keys are listed even under
# an optional parent (they apply when the parent is present).
_PROFILE_REQUIRED: dict[str, set[str]] = {
    "KpiCard": {"metrics", "metrics[].label", "metrics[].value"},
    "TimeSeriesChart": {
        "chart_type", "title", "x_key", "y_key", "data", "data[].date",
        "data[].value", "total_count",
    },
    "ComparisonTable": {"columns", "columns[].key", "columns[].label", "rows"},
    "BarChart": {"bars", "bars[].category", "bars[].value"},
    "EntityList": {"entity_type", "items", "items[].id", "items[].name"},
    "WaterfallChart": {
        "title", "segments", "segments[].label", "segments[].value",
        "segments[].type", "segments[].cumulative", "date_range.start",
        "date_range.end",
    },
    "MultiCategoryChart": {
        "title", "periods", "periods[].period", "periods[].categories",
        "periods[].categories.name", "periods[].categories.name.value", "summary",
        "summary.by_category", "summary.by_category.name",
        "summary.by_category.name.value", "summary.period_count", "date_range",
        "date_range.first", "date_range.last",
    },
    "FundPerformance": set(),
    "EmailList": {
        "messages", "messages[].id", "messages[].subject", "messages[].preview",
        "messages[].from", "messages[].from.name", "messages[].from.email",
        "messages[].to_recipients", "messages[].to_recipients[].name",
        "messages[].to_recipients[].email", "messages[].received_at",
        "messages[].is_read", "messages[].has_attachments",
        "messages[].importance", "messages[].web_link", "total_count",
        "has_more",
    },
    "CalendarEvents": {
        "events", "events[].id", "events[].subject", "events[].start",
        "events[].end", "events[].is_all_day", "events[].is_cancelled",
        "events[].is_recurring", "events[].organizer",
        "events[].organizer.name", "events[].organizer.email",
        "events[].attendees_count", "events[].importance", "events[].show_as",
        "events[].web_link", "events[].location.display_name",
        "events[].location.is_online", "date_range", "date_range.start",
        "date_range.end", "total_count", "has_more",
    },
    "UserProfile": {
        "id", "display_name", "email", "business_phones", "manager.id",
        "manager.display_name", "manager.email", "presence.availability",
        "presence.activity", "out_of_office.is_enabled",
    },
    "UserList": {
        "users", "users[].id", "users[].display_name", "users[].email",
        "users[].presence.availability", "users[].presence.activity",
        "total_count", "has_more",
    },
    "DocumentList": {"documents", "documents[].id", "documents[].name"},
}


def _minimal_instances() -> dict[str, Any]:
    cat = {"name": CategoryValue(value=1.0)}
    return {
        "KpiCard": KpiCard(metrics=[MetricItem(label="l", value=1)]),
        "TimeSeriesChart": TimeSeriesChart(
            chart_type="line", title="t",
            data=[TimeSeriesDataPoint(date="2025-01-01", value=1.0)],
        ),
        "ComparisonTable": ComparisonTable(
            columns=[ColumnDef(key="k", label="L")], rows=[{"k": 1}]
        ),
        "BarChart": BarChart(bars=[BarItem(category="c", value=1.0)]),
        "EntityList": EntityList(
            entity_type="company", items=[EntityItem(id="1", name="n")]
        ),
        "WaterfallChart": WaterfallChart(
            title="t",
            segments=[
                WaterfallSegment(label="l", value=1.0, type="initial", cumulative=1.0)
            ],
            date_range=DateRange(start="a", end="b"),
        ),
        "MultiCategoryChart": MultiCategoryChart(
            title="t",
            periods=[MultiCategoryPeriod(period="p", categories=cat)],
            summary=MultiCategorySummary(by_category=cat, period_count=1),
            date_range=FirstLastRange(first="a", last="b"),
        ),
        "FundPerformance": FundPerformance(nav=Money()),
        "EmailList": EmailList(
            messages=[
                EmailMessage(
                    id="1", subject="s", preview="p", **{"from": _NE},
                    to_recipients=[_NE], received_at="2025-01-01T00:00:00Z",
                    is_read=True, web_link="w",
                )
            ],
            total_count=1, has_more=False,
        ),
        "CalendarEvents": CalendarEvents(
            events=[
                CalendarEvent(
                    id="1", subject="s", start="2025-01-01T00:00:00Z",
                    end="2025-01-01T01:00:00Z", organizer=_NE, web_link="w",
                    location=EventLocation(join_url="u"),
                )
            ],
            date_range=DateRange(start="a", end="b"), total_count=1,
            has_more=False,
        ),
        "UserProfile": UserProfile(
            id="1", display_name="d", email="e",
            manager=ManagerRef(id="2", display_name="m", email="me"),
            presence=_PRESENCE,
            out_of_office=OutOfOfficeSettings(is_enabled=False),
        ),
        "UserList": UserList(
            users=[
                UserSummary(id="1", display_name="d", email="e", presence=_PRESENCE)
            ],
            total_count=1, has_more=False,
        ),
        "DocumentList": DocumentList(documents=[DocumentItem(id="1", name="n")]),
    }


_INSTANCES = _minimal_instances()


def test_table_covers_every_frozen_object_profile_type() -> None:
    assert set(_PROFILE_REQUIRED) == set(_INSTANCES)
    assert set(_PROFILE_REQUIRED) <= set(_COMPACT_SCHEMAS)


@pytest.mark.parametrize("component", sorted(_PROFILE_REQUIRED))
def test_compact_schema_required_keys_match_profile(component: str) -> None:
    parsed = parse_schema(_COMPACT_SCHEMAS[component])
    assert required_paths(parsed) == _PROFILE_REQUIRED[component]


@pytest.mark.parametrize("component", sorted(_PROFILE_REQUIRED))
def test_wire_always_emits_profile_required_keys(component: str) -> None:
    emitted = emitted_paths(_INSTANCES[component].wire())
    missing = _PROFILE_REQUIRED[component] - emitted
    assert not missing, f"{component} wire() omits required keys: {sorted(missing)}"


def test_event_location_defaults_emit_required_keys() -> None:
    assert EventLocation(join_url="u").wire() == {
        "display_name": "", "is_online": False, "join_url": "u",
    }
    assert EventLocation().wire() == {"display_name": "", "is_online": False}


def test_calendar_plain_text_unchanged_for_default_location() -> None:
    def text(location: EventLocation) -> str:
        return CalendarEvents(
            events=[
                CalendarEvent(
                    id="1", subject="s", start="2025-01-01T00:00:00Z",
                    end="2025-01-01T01:00:00Z", organizer=_NE, web_link="w",
                    location=location,
                )
            ],
            date_range=DateRange(start="a", end="b"), total_count=1,
            has_more=False,
        ).to_plain_text()

    out = text(EventLocation(join_url="u"))
    assert " @ " not in out
    assert "[online]" not in out
    assert " @ Room 1" in text(EventLocation(display_name="Room 1"))
    assert "[online]" in text(EventLocation(is_online=True))


def test_event_location_explicit_null_means_default() -> None:
    assert EventLocation(display_name=None, is_online=None).wire() == {  # type: ignore[arg-type]
        "display_name": "", "is_online": False,
    }
    assert EventLocation.model_validate({"display_name": None}).display_name == ""
