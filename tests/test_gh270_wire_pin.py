"""GH-270 item 3: pin ``wire()`` output so moving the omission rule into
``_Wire`` cannot change a single byte. Written green BEFORE the refactor."""

from __future__ import annotations

import json
from typing import Any

import pytest

from agent_sdk.models.content_types import (
    TRANSCRIPT_DUMP_CONTEXT,
    ColumnDef,
    ComparisonTable,
    DocumentItem,
    DocumentList,
    MarketBriefing,
    PROFILE_TYPES,
    TimeSeriesChart,
    TimeSeriesDataPoint,
)
from tests.test_gh170_profile_required_keys import _minimal_instances


def _instances() -> dict[str, Any]:
    out = _minimal_instances()
    out["MarketBriefing"] = MarketBriefing(title="t", as_of="2025-01-01", prose="p")
    out["TimeSeriesChart"] = TimeSeriesChart(
        chart_type="line",
        title="t",
        data=[
            TimeSeriesDataPoint(date="d1", value=None),
            TimeSeriesDataPoint(date="d2", value=2.0, label="l", series="s"),
        ],
    )
    out["ComparisonTable"] = ComparisonTable(
        columns=[
            ColumnDef(key="a", label="A"),
            ColumnDef(key="b", label="B", is_id=True, unit="u"),
        ],
        rows=[{"a": 1, "b": "x"}],
    )
    out["DocumentList"] = DocumentList(
        documents=[
            DocumentItem(id="1", name="n", web_url="u", last_modified="m"),
            DocumentItem(id="2", name="n2", link="L", modified="M", web_url="u", last_modified="m"),
            DocumentItem(id="3", name="n3"),
        ]
    )
    return out


def _extras() -> dict[str, Any]:
    return {
        "point_none": TimeSeriesDataPoint(date="d", value=None),
        "point_value": TimeSeriesDataPoint(date="d", value=1.5, label="x"),
        "col_default": ColumnDef(key="k", label="K"),
        "col_id": ColumnDef(key="k", label="K", is_id=True),
        "doc_alias": DocumentItem(id="1", name="n", web_url="u", last_modified="m"),
        "doc_plain": DocumentItem(id="1", name="n", size=3.0),
    }


def _pin(value: Any) -> str:
    return json.dumps(value, sort_keys=False)


def _observed() -> dict[str, str]:
    out: dict[str, str] = {}
    for name, inst in _instances().items():
        out[f"wire:{name}"] = _pin(inst.wire())
        out[f"dump:{name}"] = _pin(inst.model_dump(mode="json"))
        out[f"json:{name}"] = inst.model_dump_json()
    for name, inst in _extras().items():
        out[f"wire:{name}"] = _pin(inst.wire())
        out[f"dump:{name}"] = _pin(inst.model_dump())
        out[f"json:{name}"] = inst.model_dump_json()
        out[f"transcript:{name}"] = _pin(
            inst.model_dump(mode="json", context={TRANSCRIPT_DUMP_CONTEXT: True})
        )
    return out


GOLDEN: dict[str, str] = {
    'dump:BarChart': '{"metadata": null, "bars": [{"category": "c", "value": 1.0}], "title": null, "x_key": null, "y_key": null}',
    'dump:CalendarEvents': '{"metadata": null, "events": [{"id": "1", "subject": "s", "start": "2025-01-01T00:00:00Z", "end": "2025-01-01T01:00:00Z", "is_all_day": false, "is_cancelled": false, "is_recurring": false, "organizer": {"name": "n", "email": "e"}, "location": {"display_name": "", "is_online": false, "join_url": "u"}, "attendees_count": 0, "response_status": null, "importance": "normal", "show_as": "unknown", "web_link": "w", "is_online": null}], "date_range": {"start": "a", "end": "b"}, "total_count": 1, "has_more": false}',
    'dump:ComparisonTable': '{"metadata": null, "title": null, "columns": [{"key": "a", "label": "A", "type": null, "unit": null, "highlight": null}, {"key": "b", "label": "B", "type": null, "unit": "u", "highlight": null, "is_id": true}], "rows": [{"a": 1, "b": "x"}], "sort_by": null, "sort_order": null}',
    'dump:DocumentList': '{"metadata": null, "documents": [{"id": "1", "name": "n", "type": null, "modified": "m", "link": "u", "size": null, "modified_by": null}, {"id": "2", "name": "n2", "type": null, "modified": "M", "link": "L", "size": null, "modified_by": null}, {"id": "3", "name": "n3", "type": null, "modified": null, "link": null, "size": null, "modified_by": null}], "total_count": 3, "has_more": null}',
    'dump:EmailList': '{"metadata": null, "messages": [{"id": "1", "conversation_id": null, "subject": "s", "preview": "p", "from_": {"name": "n", "email": "e"}, "to_recipients": [{"name": "n", "email": "e"}], "received_at": "2025-01-01T00:00:00Z", "is_read": true, "has_attachments": false, "importance": "normal", "flag_status": null, "web_link": "w"}], "total_count": 1, "has_more": false, "folder": null, "query": null}',
    'dump:EntityList': '{"metadata": null, "entity_type": "company", "items": [{"id": "1", "name": "n", "summary": null}], "total_count": 1, "has_more": null, "title": null, "showing": null}',
    'dump:FundPerformance': '{"metadata": null, "pb_id": null, "as_of_date": null, "irr": null, "tvpi": null, "dpi": null, "rvpi": null, "net_irr": null, "gross_irr": null, "moic": null, "quartile": null, "nav": {"amount": null, "currency": null}, "as_of_quarter": null, "as_of_year": null, "called_down_pct": null, "dry_powder": null, "dry_powder_pct": null, "distributed": null, "remaining_value": null, "distributed_plus_remaining": null}',
    'dump:KpiCard': '{"metadata": null, "metrics": [{"label": "l", "value": 1, "unit": null, "trend": null, "change_pct": null}], "title": null}',
    'dump:MarketBriefing': '{"metadata": null, "title": "t", "as_of": "2025-01-01", "prose": "p", "sections": []}',
    'dump:MultiCategoryChart': '{"metadata": null, "title": "t", "periods": [{"period": "p", "categories": {"name": {"value": 1.0, "count": null, "metadata": null}}, "period_total": null}], "summary": {"by_category": {"name": {"value": 1.0, "count": null, "metadata": null}}, "grand_total": null, "period_count": 1}, "date_range": {"first": "a", "last": "b"}, "subtitle": null, "unit_label": null, "currency": null, "entity_name": null, "item_count": null, "chart_config": null}',
    'dump:TimeSeriesChart': '{"metadata": null, "chart_type": "line", "title": "t", "subtitle": null, "x_key": "date", "y_key": "value", "x_label": null, "y_label": null, "data": [{"date": "d1", "value": null, "label": null}, {"date": "d2", "value": 2.0, "label": "l"}], "total_count": 2, "summary": null}',
    'dump:UserList': '{"metadata": null, "users": [{"id": "1", "display_name": "d", "email": "e", "job_title": null, "department": null, "presence": {"availability": "available", "activity": "Available", "status_message": null}}], "total_count": 1, "has_more": false, "query": null}',
    'dump:UserProfile': '{"metadata": null, "id": "1", "display_name": "d", "email": "e", "given_name": null, "surname": null, "job_title": null, "department": null, "office_location": null, "mobile_phone": null, "business_phones": [], "manager": {"id": "2", "display_name": "m", "email": "me", "job_title": null}, "presence": {"availability": "available", "activity": "Available", "status_message": null}, "photo_url": null, "out_of_office": {"is_enabled": false, "start_date": null, "end_date": null, "internal_message": null, "external_message": null}}',
    'dump:WaterfallChart': '{"metadata": null, "title": "t", "segments": [{"label": "l", "value": 1.0, "type": "initial", "cumulative": 1.0, "tooltip": null}], "subtitle": null, "currency": null, "entity_name": null, "as_of_date": null, "date_range": {"start": "a", "end": "b"}}',
    'dump:col_default': '{"key": "k", "label": "K", "type": null, "unit": null, "highlight": null}',
    'dump:col_id': '{"key": "k", "label": "K", "type": null, "unit": null, "highlight": null, "is_id": true}',
    'dump:doc_alias': '{"id": "1", "name": "n", "type": null, "modified": "m", "link": "u", "size": null, "modified_by": null}',
    'dump:doc_plain': '{"id": "1", "name": "n", "type": null, "modified": null, "link": null, "size": 3.0, "modified_by": null}',
    'dump:point_none': '{"date": "d", "value": null, "label": null}',
    'dump:point_value': '{"date": "d", "value": 1.5, "label": "x"}',
    'json:BarChart': '{"metadata":null,"bars":[{"category":"c","value":1.0}],"title":null,"x_key":null,"y_key":null}',
    'json:CalendarEvents': '{"metadata":null,"events":[{"id":"1","subject":"s","start":"2025-01-01T00:00:00Z","end":"2025-01-01T01:00:00Z","is_all_day":false,"is_cancelled":false,"is_recurring":false,"organizer":{"name":"n","email":"e"},"location":{"display_name":"","is_online":false,"join_url":"u"},"attendees_count":0,"response_status":null,"importance":"normal","show_as":"unknown","web_link":"w","is_online":null}],"date_range":{"start":"a","end":"b"},"total_count":1,"has_more":false}',
    'json:ComparisonTable': '{"metadata":null,"title":null,"columns":[{"key":"a","label":"A","type":null,"unit":null,"highlight":null},{"key":"b","label":"B","type":null,"unit":"u","highlight":null,"is_id":true}],"rows":[{"a":1,"b":"x"}],"sort_by":null,"sort_order":null}',
    'json:DocumentList': '{"metadata":null,"documents":[{"id":"1","name":"n","type":null,"modified":"m","link":"u","size":null,"modified_by":null},{"id":"2","name":"n2","type":null,"modified":"M","link":"L","size":null,"modified_by":null},{"id":"3","name":"n3","type":null,"modified":null,"link":null,"size":null,"modified_by":null}],"total_count":3,"has_more":null}',
    'json:EmailList': '{"metadata":null,"messages":[{"id":"1","conversation_id":null,"subject":"s","preview":"p","from_":{"name":"n","email":"e"},"to_recipients":[{"name":"n","email":"e"}],"received_at":"2025-01-01T00:00:00Z","is_read":true,"has_attachments":false,"importance":"normal","flag_status":null,"web_link":"w"}],"total_count":1,"has_more":false,"folder":null,"query":null}',
    'json:EntityList': '{"metadata":null,"entity_type":"company","items":[{"id":"1","name":"n","summary":null}],"total_count":1,"has_more":null,"title":null,"showing":null}',
    'json:FundPerformance': '{"metadata":null,"pb_id":null,"as_of_date":null,"irr":null,"tvpi":null,"dpi":null,"rvpi":null,"net_irr":null,"gross_irr":null,"moic":null,"quartile":null,"nav":{"amount":null,"currency":null},"as_of_quarter":null,"as_of_year":null,"called_down_pct":null,"dry_powder":null,"dry_powder_pct":null,"distributed":null,"remaining_value":null,"distributed_plus_remaining":null}',
    'json:KpiCard': '{"metadata":null,"metrics":[{"label":"l","value":1,"unit":null,"trend":null,"change_pct":null}],"title":null}',
    'json:MarketBriefing': '{"metadata":null,"title":"t","as_of":"2025-01-01","prose":"p","sections":[]}',
    'json:MultiCategoryChart': '{"metadata":null,"title":"t","periods":[{"period":"p","categories":{"name":{"value":1.0,"count":null,"metadata":null}},"period_total":null}],"summary":{"by_category":{"name":{"value":1.0,"count":null,"metadata":null}},"grand_total":null,"period_count":1},"date_range":{"first":"a","last":"b"},"subtitle":null,"unit_label":null,"currency":null,"entity_name":null,"item_count":null,"chart_config":null}',
    'json:TimeSeriesChart': '{"metadata":null,"chart_type":"line","title":"t","subtitle":null,"x_key":"date","y_key":"value","x_label":null,"y_label":null,"data":[{"date":"d1","value":null,"label":null},{"date":"d2","value":2.0,"label":"l"}],"total_count":2,"summary":null}',
    'json:UserList': '{"metadata":null,"users":[{"id":"1","display_name":"d","email":"e","job_title":null,"department":null,"presence":{"availability":"available","activity":"Available","status_message":null}}],"total_count":1,"has_more":false,"query":null}',
    'json:UserProfile': '{"metadata":null,"id":"1","display_name":"d","email":"e","given_name":null,"surname":null,"job_title":null,"department":null,"office_location":null,"mobile_phone":null,"business_phones":[],"manager":{"id":"2","display_name":"m","email":"me","job_title":null},"presence":{"availability":"available","activity":"Available","status_message":null},"photo_url":null,"out_of_office":{"is_enabled":false,"start_date":null,"end_date":null,"internal_message":null,"external_message":null}}',
    'json:WaterfallChart': '{"metadata":null,"title":"t","segments":[{"label":"l","value":1.0,"type":"initial","cumulative":1.0,"tooltip":null}],"subtitle":null,"currency":null,"entity_name":null,"as_of_date":null,"date_range":{"start":"a","end":"b"}}',
    'json:col_default': '{"key":"k","label":"K","type":null,"unit":null,"highlight":null}',
    'json:col_id': '{"key":"k","label":"K","type":null,"unit":null,"highlight":null,"is_id":true}',
    'json:doc_alias': '{"id":"1","name":"n","type":null,"modified":"m","link":"u","size":null,"modified_by":null}',
    'json:doc_plain': '{"id":"1","name":"n","type":null,"modified":null,"link":null,"size":3.0,"modified_by":null}',
    'json:point_none': '{"date":"d","value":null,"label":null}',
    'json:point_value': '{"date":"d","value":1.5,"label":"x"}',
    'transcript:col_default': '{"key": "k", "label": "K", "type": null, "unit": null, "highlight": null}',
    'transcript:col_id': '{"key": "k", "label": "K", "type": null, "unit": null, "highlight": null, "is_id": true}',
    'transcript:doc_alias': '{"id": "1", "name": "n", "type": null, "modified": null, "link": null, "size": null, "web_url": "u", "last_modified": "m", "modified_by": null}',
    'transcript:doc_plain': '{"id": "1", "name": "n", "type": null, "modified": null, "link": null, "size": 3.0, "web_url": null, "last_modified": null, "modified_by": null}',
    'transcript:point_none': '{"date": "d", "value": null, "label": null}',
    'transcript:point_value': '{"date": "d", "value": 1.5, "label": "x"}',
    'wire:BarChart': '{"bars": [{"category": "c", "value": 1.0}]}',
    'wire:CalendarEvents': '{"events": [{"id": "1", "subject": "s", "start": "2025-01-01T00:00:00Z", "end": "2025-01-01T01:00:00Z", "is_all_day": false, "is_cancelled": false, "is_recurring": false, "organizer": {"name": "n", "email": "e"}, "location": {"display_name": "", "is_online": false, "join_url": "u"}, "attendees_count": 0, "importance": "normal", "show_as": "unknown", "web_link": "w"}], "date_range": {"start": "a", "end": "b"}, "total_count": 1, "has_more": false}',
    'wire:ComparisonTable': '{"columns": [{"key": "a", "label": "A"}, {"key": "b", "label": "B", "unit": "u", "is_id": true}], "rows": [{"a": 1, "b": "x"}]}',
    'wire:DocumentList': '{"documents": [{"id": "1", "name": "n", "link": "u", "modified": "m"}, {"id": "2", "name": "n2", "modified": "M", "link": "L"}, {"id": "3", "name": "n3"}], "total_count": 3}',
    'wire:EmailList': '{"messages": [{"id": "1", "subject": "s", "preview": "p", "from": {"name": "n", "email": "e"}, "to_recipients": [{"name": "n", "email": "e"}], "received_at": "2025-01-01T00:00:00Z", "is_read": true, "has_attachments": false, "importance": "normal", "web_link": "w"}], "total_count": 1, "has_more": false}',
    'wire:EntityList': '{"entity_type": "company", "items": [{"id": "1", "name": "n"}], "total_count": 1}',
    'wire:FundPerformance': '{"nav": {}}',
    'wire:KpiCard': '{"metrics": [{"label": "l", "value": 1}]}',
    'wire:MarketBriefing': '"t\\nas of: 2025-01-01\\np"',
    'wire:MultiCategoryChart': '{"title": "t", "periods": [{"period": "p", "categories": {"name": {"value": 1.0}}}], "summary": {"by_category": {"name": {"value": 1.0}}, "period_count": 1}, "date_range": {"first": "a", "last": "b"}}',
    'wire:TimeSeriesChart': '{"chart_type": "line", "title": "t", "x_key": "date", "y_key": "value", "data": [{"date": "d1", "value": null}, {"date": "d2", "value": 2.0, "label": "l"}], "total_count": 2}',
    'wire:UserList': '{"users": [{"id": "1", "display_name": "d", "email": "e", "presence": {"availability": "available", "activity": "Available"}}], "total_count": 1, "has_more": false}',
    'wire:UserProfile': '{"id": "1", "display_name": "d", "email": "e", "business_phones": [], "manager": {"id": "2", "display_name": "m", "email": "me"}, "presence": {"availability": "available", "activity": "Available"}, "out_of_office": {"is_enabled": false}}',
    'wire:WaterfallChart': '{"title": "t", "segments": [{"label": "l", "value": 1.0, "type": "initial", "cumulative": 1.0}], "date_range": {"start": "a", "end": "b"}}',
    'wire:col_default': '{"key": "k", "label": "K"}',
    'wire:col_id': '{"key": "k", "label": "K", "is_id": true}',
    'wire:doc_alias': '{"id": "1", "name": "n", "link": "u", "modified": "m"}',
    'wire:doc_plain': '{"id": "1", "name": "n", "size": 3.0}',
    'wire:point_none': '{"date": "d", "value": null}',
    'wire:point_value': '{"date": "d", "value": 1.5, "label": "x"}',
}


def test_every_profile_type_is_pinned() -> None:
    pinned = {k.split(":", 1)[1] for k in GOLDEN if k.startswith("wire:")}
    assert {c.component for c in PROFILE_TYPES} <= pinned


@pytest.mark.parametrize("key", sorted(GOLDEN))
def test_wire_output_is_byte_identical(key: str) -> None:
    assert _observed()[key] == GOLDEN[key]


def test_no_unpinned_output() -> None:
    assert set(_observed()) == set(GOLDEN)
