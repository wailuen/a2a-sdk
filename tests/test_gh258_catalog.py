"""GH-258: catalog required-ness, TimeSeriesChart key lock, low fixes."""

from __future__ import annotations

import enum
import inspect
from pathlib import Path
from typing import ClassVar, Literal

import pytest
from pydantic import BaseModel, Field, ValidationError

from agent_sdk.a2ui import catalog
from agent_sdk.a2ui.catalog import (
    _COMPACT_SCHEMAS,
    CATALOG_ID,
    _field_summary,
    get_system_prompt_section,
    supported_catalogs,
)
from agent_sdk.models.content_types import ContentModel, KpiCard, TimeSeriesChart
from tests._compact_schema import emitted_paths, parse_schema, required_paths


class _Mode(enum.Enum):
    FAST = "fast"
    SLOW = "slow"


class _Plain(ContentModel):
    data_type: ClassVar[str] = "gh258_plain"
    component: ClassVar[str] = "Gh258Plain"

    needed: str
    count: int = 0
    label: str = "x"
    tags: list[str] = Field(default_factory=list)
    note: str | None = None

    def _body_text(self) -> str:
        return ""


class _Wide(BaseModel):
    first_long_field_name: str
    second_long_field_name: str
    third_long_field_name: str
    fourth_long_field_name: str
    fifth_long_field_name: str
    sixth_long_field_name: str
    seventh_long_field_name: str
    eighth_long_field_name: str | None = None


class _Budget(ContentModel):
    data_type: ClassVar[str] = "gh258_budget"
    component: ClassVar[str] = "Gh258Budget"

    wide: _Wide
    other_wide: _Wide
    extra_optional: str | None = None

    def _body_text(self) -> str:
        return ""


class _Shapes(ContentModel):
    data_type: ClassVar[str] = "gh258_shapes"
    component: ClassVar[str] = "Gh258Shapes"

    lookup: dict[str, int]
    mode: _Mode
    kind: Literal["a", "b"]

    def _body_text(self) -> str:
        return ""


def _domain_cls() -> type[ContentModel]:
    class _Dom(ContentModel):
        catalog_id: ClassVar[str] = "urn:test-gh258:v1"
        data_type: ClassVar[str] = "gh258_dom"
        component: ClassVar[str] = "Gh258Dom"

        def _body_text(self) -> str:
            return ""

    return _Dom


def test_defaulted_fields_wire_always_writes_are_required() -> None:
    required = required_paths(parse_schema(_field_summary(_Plain)))
    assert required == {"needed", "count", "label", "tags"}


def test_wire_emits_what_summary_marks_required() -> None:
    wired = emitted_paths(_Plain(needed="n").wire())
    required = required_paths(parse_schema(_field_summary(_Plain)))
    assert required <= wired


def test_excluded_default_factory_field_is_absent_from_summary() -> None:
    class _Hidden(ContentModel):
        data_type: ClassVar[str] = "gh258_hidden"
        component: ClassVar[str] = "Gh258Hidden"

        shown: str
        hidden: list[str] = Field(default_factory=list, exclude=True)

        def _body_text(self) -> str:
            return ""

    summary = _field_summary(_Hidden)
    assert "hidden" not in summary
    wired = emitted_paths(_Hidden(shown="s").wire())
    assert required_paths(parse_schema(summary)) <= wired


def test_nested_expansion_stays_within_budget() -> None:
    summary = _field_summary(_Budget)
    assert len(summary) <= 250
    assert "wide" in summary and "other_wide" in summary


def test_nested_expansion_still_used_when_it_fits() -> None:
    class _Small(ContentModel):
        data_type: ClassVar[str] = "gh258_small"
        component: ClassVar[str] = "Gh258Small"

        leaf: _Leaf

        def _body_text(self) -> str:
            return ""

    assert "inner: str" in _field_summary(_Small)


class _Leaf(BaseModel):
    inner: str


def test_compact_schema_pins_timeseries_keys() -> None:
    assert '"x_key":"date","y_key":"value"' in _COMPACT_SCHEMAS["TimeSeriesChart"]
    assert '"x_key":"date","y_key":"value"' in get_system_prompt_section()


def _chart(**kw: object) -> TimeSeriesChart:
    return TimeSeriesChart(chart_type="line", title="t", data=[], **kw)  # type: ignore[arg-type]


def test_timeseries_accepts_default_keys() -> None:
    assert _chart(x_key="date", y_key="value").x_key == "date"
    assert _chart().y_key == "value"


@pytest.mark.parametrize("field", ["x_key", "y_key"])
def test_timeseries_rejects_other_keys_with_fixed_message(field: str) -> None:
    with pytest.raises(ValidationError) as exc:
        _chart(**{field: "SECRET-other"})
    text = str(exc.value)
    assert f"TimeSeriesChart {field} must be fixed" in text
    assert "SECRET-other" not in text


def test_dict_renders_as_key_value() -> None:
    assert "lookup: {key: int}" in _field_summary(_Shapes)


def test_enum_and_literal_list_values() -> None:
    summary = _field_summary(_Shapes)
    assert 'mode: "fast|slow"' in summary
    assert 'kind: "a|b"' in summary


def test_supported_catalogs_none_emits_needs_standard_type(monkeypatch: pytest.MonkeyPatch) -> None:
    dom = _domain_cls()
    monkeypatch.setattr(
        catalog, "registered_content_types", lambda: {"gh258_dom": dom, "kpi": KpiCard}
    )
    assert supported_catalogs(None) == [CATALOG_ID, dom.catalog_id]
    assert supported_catalogs([dom.component]) == [dom.catalog_id]
    assert supported_catalogs([KpiCard.component]) == [CATALOG_ID]


def test_emits_is_sequence_and_listed_once() -> None:
    ann = str(inspect.signature(supported_catalogs).parameters["emits"].annotation)
    assert "Sequence" in ann and "Iterable" not in ann
    assert supported_catalogs(None, (KpiCard, KpiCard)) == [CATALOG_ID]


def test_design_records_entity_list_extensions() -> None:
    text = (Path(__file__).resolve().parent.parent / "DESIGN.md").read_text()
    assert any(
        "EntityList" in ln and "title" in ln and "showing" in ln and "SDK extension" in ln and "ignore" in ln
        for ln in text.splitlines()
    )
