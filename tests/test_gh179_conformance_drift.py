"""GH-179: pre-existing protocol drift items from the w049 audit."""

from __future__ import annotations

import gc
import json
import re
import weakref
from pathlib import Path
from typing import ClassVar, Literal

import pytest
from pydantic import ValidationError

from agent_sdk.a2ui import catalog
from agent_sdk.models import content_types as ct
from agent_sdk.models.content_types import (
    CategoryValue,
    ColumnDef,
    ComparisonTable,
    ContentModel,
    EntityList,
    MarketBriefing,
)

_LITERAL = re.compile(r"\b(nan|-?inf(inity)?)\b", re.IGNORECASE)
NON_FINITE = [float("nan"), float("inf"), float("-inf")]


# ── item 1: SDK extensions documented, wire unchanged ──


@pytest.mark.parametrize(
    "obj",
    [EntityList, ct.CalendarEvent, ColumnDef, ComparisonTable],
)
def test_sdk_extension_keys_are_documented_in_docstrings(obj):
    assert "SDK extension" in (obj.__doc__ or "")


def test_sdk_extension_docs_page_lists_every_key():
    text = Path("docs/content-types.md").read_text(encoding="utf-8")
    assert "SDK extension" in text
    for key in ("showing", "is_online", "highlight", "sort_by", "sort_order"):
        assert key in text


def test_sdk_extension_keys_stay_on_the_wire():
    table = ComparisonTable(
        columns=[ColumnDef(key="a", label="A", unit="USD", highlight="max")],
        rows=[{"a": 1}],
        sort_by="a",
        sort_order="asc",
    )
    wire = table.wire()
    assert wire["sort_by"] == "a" and wire["sort_order"] == "asc"
    assert wire["columns"][0]["unit"] == "USD"
    assert wire["columns"][0]["highlight"] == "max"
    lst = EntityList(entity_type="x", items=[], title="T", showing=3)
    assert lst.wire()["title"] == "T" and lst.wire()["showing"] == 3


# ── item 2: compact schemas ──


def test_compact_schema_kpi_card_lists_change_pct():
    assert "change_pct?" in catalog._COMPACT_SCHEMAS["KpiCard"]


def test_compact_schema_time_series_subtitle_and_nullable_value():
    schema = catalog._COMPACT_SCHEMAS["TimeSeriesChart"]
    assert '"subtitle?":str' in schema
    assert "value:num|null" in schema


# ── item 3: non-finite values in free-form rows / metadata ──


@pytest.mark.parametrize("bad", NON_FINITE)
def test_comparison_table_rejects_non_finite_row_value(bad):
    with pytest.raises(ValidationError) as exc:
        ComparisonTable(columns=[ColumnDef(key="v", label="V")], rows=[{"v": bad}])
    assert not _LITERAL.search(str(exc.value).split("For further")[0].replace("non-finite", ""))


@pytest.mark.parametrize("bad", NON_FINITE)
def test_comparison_table_rejects_nested_non_finite_row_value(bad):
    with pytest.raises(ValidationError):
        ComparisonTable(columns=[ColumnDef(key="v", label="V")], rows=[{"v": [1, {"x": bad}]}])


@pytest.mark.parametrize("bad", NON_FINITE)
def test_category_value_metadata_rejects_non_finite(bad):
    with pytest.raises(ValidationError):
        CategoryValue(value=1.0, metadata={"share": bad})


def test_finite_rows_and_metadata_unchanged():
    t = ComparisonTable(columns=[ColumnDef(key="v", label="V")], rows=[{"v": 1.5}])
    assert t.wire()["rows"] == [{"v": 1.5}]
    assert CategoryValue(value=1.0, metadata={"a": 2}).wire()["metadata"] == {"a": 2}


# ── item 5: MarketBriefing.wire() is the markdown string ──


def test_market_briefing_wire_is_markdown():
    mb = MarketBriefing(title="T", as_of="2026-01-01", prose="hello")
    assert mb.wire() == mb.to_markdown()
    assert isinstance(mb.wire(), str)


def test_market_briefing_translator_still_emits_markdown_value():
    from agent_sdk.a2ui.translator import A2uiCapabilities, translate

    mb = MarketBriefing(title="T", as_of="2026-01-01", prose="hello")
    msgs = translate(mb, capabilities=A2uiCapabilities())
    assert msgs is not None
    values = [
        m["updateDataModel"]["value"] for m in msgs if "updateDataModel" in m
    ]
    assert values == [mb.to_markdown()]


# ── item 6: few-shot examples show the resolved data object ──


def test_few_shot_examples_have_no_sibling_component_key():
    for name, ex in catalog._FEW_SHOT_EXAMPLES.items():
        assert "component" not in json.loads(ex), name


def test_few_shot_heading_says_data_object_only():
    section = catalog.get_system_prompt_section()
    assert "no `component` key" in section


# ── item 7: fallback field summary ──


def test_field_summary_renders_literal_list_and_all_union_arms():
    class _Rich(ContentModel):
        data_type: ClassVar[str] = "gh179_rich"
        component: ClassVar[str] = "Gh179Rich"

        kind: str = "x"
        mode: Literal["a", "b"] = "a"
        tags: list[str] = []
        scores: list[int] | None = None
        either: int | str = 0

        def _body_text(self) -> str:
            return ""

    summary = catalog._field_summary(_Rich)
    assert 'mode?: "a|b"' in summary
    assert "tags?: [str]" in summary
    assert "scores?: [int]|null" in summary
    assert "either?: int|str" in summary


def test_legend_explains_null_marker():
    legend = next(
        line
        for line in catalog.get_system_prompt_section().splitlines()
        if line.startswith("Components tools can emit")
    )
    assert "|null" in legend


# ── item 8: weak-keyed class memos ──


def test_dynamic_subclass_is_garbage_collectable_after_wire_use():
    class _Dyn(ContentModel):
        data_type: ClassVar[str] = "gh179_dyn"
        component: ClassVar[str] = "Gh179Dyn"

        x: float | None = None
        n: int | None = None

        def _body_text(self) -> str:
            return ""

    _Dyn(x=float("nan"), n=1).wire()
    ref = weakref.ref(_Dyn)
    del _Dyn
    gc.collect()
    assert ref() is None


# ── item 9: strict serialization of non-stream A2A responses ──

_SEND = {
    "message": {
        "role": "user",
        "parts": [{"kind": "text", "text": "hi"}],
        "messageId": "m179",
    }
}


async def test_tasks_get_with_non_finite_value_is_fixed_32006(client, fake_model):
    from agent_sdk.testing import reply

    fake_model.script(reply("hi"))
    r = await client.post("/v1/message:send", json=_SEND)
    assert r.status_code == 200
    task_id = r.json()["id"]
    record = client.app.state.task_store.get(task_id)
    assert record is not None
    record.task.metadata = {"x": float("nan")}
    got = await client.get(f"/v1/tasks/{task_id}")
    assert got.status_code == 502
    assert got.json() == {"error": {"code": -32006, "message": "invalid agent response"}}
    assert not _LITERAL.search(got.text.replace("invalid agent response", ""))


async def test_message_send_with_non_finite_value_is_fixed_32006(client, fake_model, monkeypatch):
    from agent_sdk.routes import a2a as a2a_routes
    from agent_sdk.testing import reply

    real = a2a_routes._task_wire

    def _bad(record, history_length=None):
        wire = real(record, history_length)
        wire["metadata"] = {"x": float("inf")}
        return wire

    monkeypatch.setattr(a2a_routes, "_task_wire", _bad)
    fake_model.script(reply("hi"))
    r = await client.post("/v1/message:send", json=_SEND)
    assert r.status_code == 502
    assert r.json() == {"error": {"code": -32006, "message": "invalid agent response"}}


def test_strict_json_helper_exists():
    from agent_sdk.routes import a2a as a2a_routes

    ok = a2a_routes._strict_json_response({"a": 1})
    assert ok.status_code == 200
    bad = a2a_routes._strict_json_response({"a": float("nan")})
    assert bad.status_code == 502


# ── GH-178 code part: dead hook removed ──


def test_unused_rejects_non_finite_hook_removed():
    assert not hasattr(ct._Wire, "_rejects_non_finite")


def test_market_briefing_subclass_with_domain_catalog_passes_wire_check():
    from typing import ClassVar

    from agent_sdk.agent.runner import _validate_a2ui_wire
    from agent_sdk.models.content_types import MarketBriefing

    class _DomainBriefing(MarketBriefing):
        data_type: ClassVar[str] = "test_domain_briefing"
        component: ClassVar[str] = "TestDomainBriefing"
        catalog_id: ClassVar[str] = "urn:test-domain-briefing:v1"

    briefing = _DomainBriefing(title="T", as_of="2026-01-01", sections=[])
    _validate_a2ui_wire(briefing, [{"version": "v0.9"}])


# ── RT-001: AG-UI AGENT_ARTIFACT keeps the field-dict shape ──


def test_market_briefing_agui_artifact_frame_matches_schema_and_keeps_metadata():
    from agent_sdk.a2ui.translator import A2uiCapabilities
    from agent_sdk.agent.events import ArtifactEvent
    from agent_sdk.routes.agent_card import _CUSTOM_EVENT_SCHEMAS
    from agent_sdk.routes.ag_ui import _RunMapper

    mb = MarketBriefing(
        title="T", as_of="2026-01-01", prose="hello",
        metadata={"coverage_note": "Partial: 5 of 20"},
    )
    frames = _RunMapper("t", "r", A2uiCapabilities()).map(
        ArtifactEvent(data_type="market_briefing", tool_name="x", model=mb)
    )
    frame = next(f for f in frames if f.get("name") == "AGENT_ARTIFACT")
    data = frame["value"]["data"]
    schema = next(s for s in _CUSTOM_EVENT_SCHEMAS if s["name"] == "AGENT_ARTIFACT")
    assert schema["valueSchema"]["properties"]["data"]["type"] == "object"
    assert isinstance(data, dict)
    assert data == mb.model_dump(mode="json", by_alias=True, exclude_none=True)
    assert data["metadata"] == {"coverage_note": "Partial: 5 of 20"}


# ── RT-001: every non-stream A2A route answers a non-finite value with the fixed body ──

_FIXED_32006 = {"error": {"code": -32006, "message": "invalid agent response"}}


def _assert_fixed_32006(resp, caplog):
    assert resp.status_code == 502
    assert resp.json() == _FIXED_32006
    assert not _LITERAL.search(resp.text.replace("invalid agent response", ""))
    assert not _LITERAL.search(caplog.text.replace("invalid agent response", ""))


async def _sent_task(client, fake_model):
    from agent_sdk.testing import reply

    fake_model.script(reply("hi"))
    r = await client.post("/v1/message:send", json=_SEND)
    assert r.status_code == 200
    task_id = r.json()["id"]
    record = client.app.state.task_store.get(task_id)
    assert record is not None
    return task_id, record


async def test_tasks_list_leaves_out_a_non_finite_task_never_500(
    client, fake_model, monkeypatch, caplog
):
    """w050 RT-001 (round 6): tasks/list serializes each task on its own, so
    one record that cannot be written (here a non-finite value that bypassed
    validation) is left out instead of failing the whole page for the
    identity with 502. Never HTTP 500, and the value is never echoed."""
    from agent_sdk.models.a2a import Task

    good_id, _ = await _sent_task(client, fake_model)
    bad_id, _ = await _sent_task(client, fake_model)
    real = Task.model_dump

    def _bad(self, *a, **k):
        dumped = real(self, *a, **k)
        if self.id == bad_id:
            dumped["metadata"] = {"x": float("nan")}
        return dumped

    monkeypatch.setattr(Task, "model_dump", _bad)
    got = await client.get("/v1/tasks")
    assert got.status_code == 200, got.text
    assert [t["id"] for t in got.json()["tasks"]] == [good_id]
    assert not _LITERAL.search(got.text)
    assert not _LITERAL.search(caplog.text)
    assert bad_id in caplog.text  # logged by id only


async def test_tasks_cancel_with_non_finite_value_is_fixed_32006(client, fake_model, caplog):
    from agent_sdk.models.a2a import TaskState

    task_id, record = await _sent_task(client, fake_model)
    record.task.status.state = TaskState.WORKING
    record.task.metadata = {"x": float("inf")}
    got = await client.post(f"/v1/tasks/{task_id}:cancel")
    _assert_fixed_32006(got, caplog)


async def test_resumed_task_with_non_finite_value_is_fixed_32006(
    client, fake_model, monkeypatch, caplog
):
    from agent_sdk.routes import a2a as a2a_routes

    task_id, record = await _sent_task(client, fake_model)
    record.task.metadata = {"x": float("nan")}
    monkeypatch.setattr(a2a_routes, "_resume_or_error", lambda *a, **k: record)
    body = {"message": {**_SEND["message"], "taskId": task_id, "messageId": "m179b"}}
    got = await client.post("/v1/message:send", json=body)
    _assert_fixed_32006(got, caplog)


async def test_sync_reply_bare_message_with_non_finite_value_is_fixed_32006(
    client, monkeypatch, caplog
):
    from agent_sdk.models.a2a import Message

    real = Message.wire

    def _bad(self, *a, **k):
        wire = real(self, *a, **k)
        wire["metadata"] = {"x": float("-inf")}
        return wire

    client.app.state.sync_reply = lambda msg: "pong"
    monkeypatch.setattr(Message, "wire", _bad)
    got = await client.post("/v1/message:send", json=_SEND)
    _assert_fixed_32006(got, caplog)


# ── RT-002: shared dumps_strict ──


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), float("-inf")])
def test_dumps_strict_rejects_non_finite(bad):
    from agent_sdk.common.json_strict import dumps_strict

    with pytest.raises(ValueError):
        dumps_strict({"a": [bad]})


def test_dumps_strict_compact_and_unicode():
    from agent_sdk.common.json_strict import dumps_strict

    assert dumps_strict({"a": 1, "b": "é"}) == '{"a":1,"b":"é"}'
