"""GH-173: non-finite floats on built-in content models.

Ruling: nullable numeric fields coerce nan/inf/-inf to None; non-nullable
numeric fields reject, naming the field and never echoing the value.
"""

from __future__ import annotations

import json
import re
import types
import typing
from typing import Any, Union, get_args, get_origin

import pytest
from pydantic import BaseModel, ValidationError

from agent_sdk.models import content_types as ct
from agent_sdk.models.content_types import (
    BarChart,
    BarItem,
    ContentModel,
    MetricItem,
    TimeSeriesDataPoint,
    _Wire,
)

_LITERAL = re.compile(r"\b(nan|-?inf(inity)?)\b", re.IGNORECASE)
NON_FINITE = [float("nan"), float("inf"), float("-inf")]

GH95_REJECTING: set[str] = set()


def _all_wire_models() -> list[type[BaseModel]]:
    found: dict[str, type[BaseModel]] = {}

    def visit(cls: type[BaseModel]) -> None:
        if cls.__name__ in found:
            return
        found[cls.__name__] = cls
        for info in cls.model_fields.values():
            for t in _flatten(info.annotation):
                if isinstance(t, type) and issubclass(t, BaseModel):
                    visit(t)

    for obj in vars(ct).values():
        if isinstance(obj, type) and issubclass(obj, _Wire) and obj.__module__ == ct.__name__:
            visit(obj)
    return list(found.values())


def _flatten(tp: Any) -> list[Any]:
    out = [tp]
    for a in get_args(tp):
        out.extend(_flatten(a))
    return out


def _float_fields(cls: type[BaseModel]) -> list[tuple[str, str, bool]]:
    """(field name, input key, nullable) for fields whose annotation holds float."""
    result = []
    for name, info in cls.model_fields.items():
        flat = _flatten(info.annotation)
        if float not in flat:
            continue
        nullable = type(None) in flat
        result.append((name, info.alias or name, nullable))
    return result


def _sample(cls: type[BaseModel], overrides: dict[str, Any]) -> BaseModel:
    """Build a valid instance by filling required fields from annotations."""
    data: dict[str, Any] = {}
    for name, info in cls.model_fields.items():
        if not info.is_required():
            continue
        data[info.alias or name] = _value_for(info.annotation)
    data.update(overrides)
    return cls(**data)


def _value_for(tp: Any) -> Any:
    origin = get_origin(tp)
    if origin in (Union, types.UnionType):
        args = [a for a in get_args(tp) if a is not type(None)]
        for pick in (float, int, str):
            if pick in args:
                return _value_for(pick)
        return _value_for(args[0])
    if origin is typing.Literal:
        return get_args(tp)[0]
    if origin is list:
        inner = get_args(tp)[0]
        return [_value_for(inner)]
    if origin is dict:
        return {}
    if tp is float:
        return 1.0
    if tp is int:
        return 1
    if tp is str:
        return "x"
    if tp is bool:
        return True
    if isinstance(tp, type) and issubclass(tp, BaseModel):
        return _sample(tp, {})
    if tp is Any:
        return "x"
    raise AssertionError(f"cannot sample {tp!r}")


MODELS = _all_wire_models()
CASES = [
    (cls, name, key, nullable)
    for cls in MODELS
    if cls.__name__ not in GH95_REJECTING
    for name, key, nullable in _float_fields(cls)
]


def test_walk_finds_the_named_fields():
    names = {(c.__name__, n) for c, n, _, _ in CASES}
    for expected in [
        ("BarItem", "value"),
        ("MetricItem", "value"),
        ("MetricItem", "change_pct"),
        ("WaterfallSegment", "value"),
        ("WaterfallSegment", "cumulative"),
        ("CategoryValue", "value"),
        ("TimeSeriesDataPoint", "value"),
        ("MultiCategoryPeriod", "period_total"),
        ("FundPerformance", "irr"),
        ("FundPerformance", "tvpi"),
        ("Money", "amount"),
    ]:
        assert expected in names


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "inf", "-inf"])
@pytest.mark.parametrize(
    "cls,name,key,nullable", CASES, ids=[f"{c.__name__}.{n}" for c, n, _, _ in CASES]
)
def test_every_float_field_follows_ruling(cls, name, key, nullable, bad):
    if nullable:
        model = _sample(cls, {key: bad})
        assert getattr(model, name) is None
        json.dumps(model.model_dump(mode="json", by_alias=True), allow_nan=False)
        json.dumps(model.wire(), allow_nan=False)
        if isinstance(model, ContentModel):
            assert not _LITERAL.search(model.to_plain_text())
    else:
        with pytest.raises(ValidationError) as exc:
            _sample(cls, {key: bad})
        msg = str(exc.value)
        assert name in msg
        assert not _LITERAL.search(msg)


def test_nested_nullable_coerced_inside_content_model():
    point = TimeSeriesDataPoint(date="2026-01-01", value=float("nan"))
    chart = _sample(ct.TimeSeriesChart, {"data": [point]})
    wire = chart.wire()
    json.dumps(wire, allow_nan=False)
    assert wire["data"][0]["value"] is None
    assert not _LITERAL.search(chart.to_plain_text())
    assert json.loads(chart.model_dump_json())["data"][0]["value"] is None


def test_issue_repro_bar_chart_rejects():
    with pytest.raises(ValidationError) as exc:
        BarChart(bars=[BarItem(category="x", value=float("nan"))])
    assert "value" in str(exc.value)
    assert not _LITERAL.search(str(exc.value))


def test_metric_item_string_value_still_fine():
    assert MetricItem(label="a", value="n/a").value == "n/a"


def test_metric_item_non_finite_value_rejected_and_change_pct_coerced():
    with pytest.raises(ValidationError):
        MetricItem(label="a", value=float("inf"))
    assert MetricItem(label="a", value=1, change_pct=float("inf")).change_pct is None


def test_finite_values_untouched():
    assert BarItem(category="x", value=1.5).value == 1.5


def test_briefing_kpi_item_coerces_nullable_delta_and_rejects_value():
    assert ct.BriefingKpiItem(title="t", value=1.0, delta=float("nan")).delta is None
    with pytest.raises(ValidationError):
        ct.BriefingKpiItem(title="t", value=float("nan"))


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "inf", "-inf"])
@pytest.mark.parametrize(
    "build",
    [
        lambda b: ct.BriefingKpiItem(title="t", value=b),
        lambda b: ct.ChartSection(chart_type="bar_chart", data={"x": b}),
        lambda b: ct.TableSection(data={"x": [b]}),
        lambda b: ct.KpiCard(metrics=[MetricItem(label="a", value=1)], metadata={"a": b}),
    ],
    ids=["kpi.value", "chart.data", "table.data", "metadata"],
)
def test_validation_error_text_never_echoes_value(build, bad):
    with pytest.raises(ValidationError) as exc:
        build(bad)
    assert not _LITERAL.search(str(exc.value))
    assert not _LITERAL.search(json.dumps(exc.value.errors(include_input=False), default=str))
    assert not _LITERAL.search(exc.value.json(include_input=False))


import asyncio

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.loop import LoopPolicies
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, tool_call

_nan_tools = ToolSet()


@_nan_tools.tool(tier=1)
async def build_nan_kpi() -> ct.BriefingKpiItem:
    """Builds a KPI item from a bad upstream number."""
    return ct.BriefingKpiItem(title="t", value=float("nan"))


@pytest.mark.asyncio
async def test_tool_error_text_has_no_non_finite_literal():
    store = InMemoryTaskStore()
    task = new_task()
    record = store.create(task, Identity(kind="api_key", subject="t", admin=True))
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    await run_task_worker(
        store=store,
        record=record,
        model=FakeModelClient().script(tool_call("build_nan_kpi", {})),
        registry=ToolRegistry([_nan_tools], {}),
        adapters={},
        skills=None,
        system="s",
        capabilities=A2uiCapabilities(tier="none", catalogs=[]),
        policies=LoopPolicies(),
    )
    for _ in range(250):
        rec = store.get(task.id)
        assert rec is not None
        if rec.task.status.state in ("completed", "failed"):
            break
        await asyncio.sleep(0.02)
    rec = store.get(task.id)
    assert rec is not None
    results = [
        b["toolResult"]
        for m in rec.messages
        if m.get("role") == "user"
        for b in m.get("content") or []
        if isinstance(b, dict) and "toolResult" in b
    ]
    assert results and results[0]["status"] == "error"
    text = json.dumps(results[0]["content"]) + rec.task.model_dump_json()
    assert not _LITERAL.search(text)


def _nullable_int_fields(cls: type[BaseModel]) -> list[tuple[str, str]]:
    result = []
    for name, info in cls.model_fields.items():
        flat = _flatten(info.annotation)
        if int in flat and float not in flat and type(None) in flat:
            result.append((name, info.alias or name))
    return result


INT_CASES = [
    (cls, name, key)
    for cls in MODELS
    if cls.__name__ not in GH95_REJECTING
    for name, key in _nullable_int_fields(cls)
]


def test_int_walk_finds_the_named_fields():
    names = {(c.__name__, n) for c, n, _ in INT_CASES}
    assert ("CategoryValue", "count") in names
    assert ("FundPerformance", "quartile") in names


@pytest.mark.parametrize("bad", NON_FINITE, ids=["nan", "inf", "-inf"])
@pytest.mark.parametrize(
    "cls,name,key", INT_CASES, ids=[f"{c.__name__}.{n}" for c, n, _ in INT_CASES]
)
def test_nullable_int_fields_coerce_non_finite_to_none(cls, name, key, bad):
    model = _sample(cls, {key: bad})
    value = getattr(model, name)
    assert value is None or (name == "total_count" and value == 1)
    json.dumps(model.wire(), allow_nan=False)


def test_category_value_count_nan_is_none():
    assert ct.CategoryValue(value=1.0, count=float("nan")).count is None


def test_sse_data_refuses_nan():
    from agent_sdk.common.sse import sse_data

    with pytest.raises(ValueError):
        sse_data({"value": float("nan")})


def test_build_artifact_refuses_nan_scalar_and_mutated_model():
    from agent_sdk.agent.runner import build_artifact
    from agent_sdk.a2ui.translator import A2uiCapabilities
    from agent_sdk.agent.events import ArtifactEvent

    bc = BarChart(bars=[BarItem(category="x", value=1.0)])
    bc.bars[0].value = float("nan")
    for payload in (bc, float("nan")):
        ev = ArtifactEvent(model=payload, data_type="t", tool_name="x")
        with pytest.raises(ValueError):
            build_artifact(ev, A2uiCapabilities())


async def test_ag_ui_body_with_nan_state_ends_in_one_terminal_frame(client, fake_model):
    from agent_sdk.testing import reply

    from .conftest import sse_frames

    fake_model.script(reply("hi"))
    raw = (
        '{"threadId":"t","runId":"r","messages":[{"id":"m1","role":"user","content":"hi"}],'
        '"state":{"x":NaN},"tools":[],"context":[],"forwardedProps":{}}'
    )
    r = await client.post("/ag-ui/run", content=raw, headers={"content-type": "application/json"})
    if r.status_code != 200:
        assert 400 <= r.status_code < 500
        return
    types = [f["type"] for f in sse_frames(r.text)]
    assert types[0] == "RUN_STARTED"
    assert sum(t in ("RUN_FINISHED", "RUN_ERROR") for t in types) == 1
    assert types[-1] in ("RUN_FINISHED", "RUN_ERROR")


# --- GH-173 round 4: every protocol ingress rejects bare NaN/Infinity ------

# RT-001 (round 6): the bare literals AND number literals that overflow a
# double (float("1e999") is inf) — both decode to a non-finite float.
_BARE = ["NaN", "Infinity", "-Infinity", "1e999", "-1e400", "1E400"]


@pytest.mark.parametrize("lit", _BARE)
def test_loads_strict_rejects_bare_non_finite(lit):
    from agent_sdk.common.json_strict import loads_strict

    with pytest.raises(json.JSONDecodeError) as exc:
        loads_strict('{"x":' + lit + "}")
    assert not _LITERAL.search(str(exc.value))
    assert loads_strict('{"x":1.5,"y":"NaN"}') == {"x": 1.5, "y": "NaN"}


def _a2a_raw(lit: str) -> str:
    return (
        '{"message":{"role":"user","parts":[{"kind":"text","text":"hi"}],'
        '"messageId":"m1","metadata":{"x":' + lit + "}}}"
    )


@pytest.mark.parametrize("lit", _BARE)
@pytest.mark.parametrize("path", ["/v1/message:stream", "/v1/message:send"])
async def test_a2a_body_with_non_finite_is_parse_error(client, fake_model, path, lit):
    r = await client.post(
        path, content=_a2a_raw(lit), headers={"content-type": "application/json"}
    )
    assert 400 <= r.status_code < 500
    assert r.json()["error"]["code"] == -32700
    assert not _LITERAL.search(r.text)


async def test_a2a_stream_unserializable_frame_ends_with_one_final_frame(
    client, fake_model
):
    """Defence in depth: a frame that slips past validation with a NaN must
    still close the stream with exactly one final:true frame."""
    from agent_sdk.agent.runner import StreamItem
    from agent_sdk.models.a2a import TaskStatusUpdateEvent
    from agent_sdk.testing import reply

    from .conftest import sse_frames

    fake_model.script(reply("hi"))
    store = client.app.state.task_store
    published: list[str] = []
    real_publish = store.publish

    def _publish(task_id, item):
        if not published:
            published.append(task_id)
            bad = TaskStatusUpdateEvent(
                taskId=task_id, contextId="c",
                status=store.get(task_id).task.status, final=False,
            ).wire()
            bad["metadata"] = {"x": float("nan")}
            real_publish(task_id, StreamItem(frame=bad, event=None))
            return
        real_publish(task_id, item)

    store.publish = _publish
    try:
        r = await client.post(
            "/v1/message:stream",
            content=_a2a_raw("1"),
            headers={"content-type": "application/json"},
        )
    finally:
        store.publish = real_publish
    assert r.status_code == 200
    frames = sse_frames(r.text)
    finals = [f for f in frames if f.get("final") is True]
    assert len(finals) == 1 and frames[-1] is finals[0]
    assert frames[-1]["status"]["state"] == "failed"
    assert "NaN" not in r.text


async def _mcp_init(client) -> dict[str, str]:
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0", "id": 1, "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    assert r.status_code == 200, r.text
    return {
        "mcp-session-id": r.headers["mcp-session-id"],
        "mcp-protocol-version": "2025-06-18",
        "content-type": "application/json",
    }


@pytest.mark.parametrize("lit", _BARE)
async def test_mcp_body_with_non_finite_is_parse_error(client, lit):
    headers = await _mcp_init(client)
    raw = '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"x","arguments":{"v":' + lit + "}}}"
    r = await client.post("/mcp", content=raw, headers=headers)
    assert r.json()["error"]["code"] == -32700
    assert not _LITERAL.search(r.text)


@pytest.mark.parametrize("lit", _BARE)
async def test_oauth_register_with_non_finite_is_rejected(client, lit):
    raw = '{"redirect_uris":["https://c.example.com/cb"],"client_name":' + lit + "}"
    r = await client.post(
        "/oauth/register", content=raw, headers={"content-type": "application/json"}
    )
    if r.status_code == 404:
        pytest.skip("OAuth registration not enabled in the default fixture")
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_client_metadata"


def test_loads_strict_rejects_oversized_integer_as_parse_error():
    from agent_sdk.common.json_strict import loads_strict

    digits = "9" * 5000
    with pytest.raises(json.JSONDecodeError) as exc:
        loads_strict("[" + digits + "]")
    assert digits[:50] not in str(exc.value)
    assert loads_strict("[1e-999, 12, -3.5]") == [0.0, 12, -3.5]


async def test_mcp_id_overflowing_number_is_parse_error(client):
    headers = await _mcp_init(client)
    raw = '{"jsonrpc":"2.0","id":1e999,"method":"tools/list","params":{}}'
    r = await client.post("/mcp", content=raw, headers=headers)
    assert r.status_code < 500
    assert r.json()["error"]["code"] == -32700


async def test_mcp_oversized_integer_is_parse_error(client):
    headers = await _mcp_init(client)
    raw = '{"jsonrpc":"2.0","id":' + "9" * 5000 + ',"method":"tools/list","params":{}}'
    r = await client.post("/mcp", content=raw, headers=headers)
    assert r.status_code < 500
    assert r.json()["error"]["code"] == -32700


def _agui_raw(state_value: str) -> str:
    return (
        '{"threadId":"t","runId":"r","messages":[{"id":"m1","role":"user","content":"hi"}],'
        '"state":{"x":' + state_value + '},"tools":[],"context":[],"forwardedProps":{}}'
    )


def _assert_one_terminal(text: str) -> list[str]:
    from .conftest import sse_frames

    types = [f["type"] for f in sse_frames(text)]
    assert types[0] == "RUN_STARTED"
    assert sum(t in ("RUN_FINISHED", "RUN_ERROR") for t in types) == 1
    assert types[-1] in ("RUN_FINISHED", "RUN_ERROR")
    assert not _LITERAL.search(text)
    return types


@pytest.mark.parametrize("lit", _BARE)
async def test_ag_ui_state_with_non_finite_ends_in_one_terminal_frame(
    client, fake_model, lit
):
    from agent_sdk.testing import reply

    fake_model.script(reply("hi"))
    r = await client.post(
        "/ag-ui/run", content=_agui_raw(lit), headers={"content-type": "application/json"}
    )
    if r.status_code != 200:
        assert 400 <= r.status_code < 500
        return
    _assert_one_terminal(r.text)


async def test_ag_ui_state_snapshot_unserializable_closes_with_run_error(
    client, fake_model, monkeypatch
):
    """Defence in depth (RT-002): a non-finite state value that got past
    ingress must not cut the stream after RUN_STARTED with no terminal."""
    from agent_sdk.routes import ag_ui
    from agent_sdk.testing import reply

    fake_model.script(reply("hi"))
    monkeypatch.setattr(ag_ui, "loads_strict", json.loads)  # lenient ingress
    r = await client.post(
        "/ag-ui/run", content=_agui_raw("1e999"), headers={"content-type": "application/json"}
    )
    assert r.status_code == 200
    types = _assert_one_terminal(r.text)
    assert types == ["RUN_STARTED", "RUN_ERROR"]


async def test_ag_ui_unserializable_terminal_frame_becomes_run_error(
    client, fake_model, monkeypatch
):
    """A RUN_FINISHED carrying a NaN must be replaced by one RUN_ERROR, not
    leave the stream with no terminal frame (terminal_sent already True)."""
    from agent_sdk.routes import ag_ui
    from agent_sdk.testing import reply

    fake_model.script(reply("hi"))
    real = ag_ui._RunMapper.run_finished

    def _bad_finished(self, outcome=None):
        frames = real(self, outcome)
        frames[-1]["x"] = float("nan")
        return frames

    monkeypatch.setattr(ag_ui._RunMapper, "run_finished", _bad_finished)
    r = await client.post(
        "/ag-ui/run", content=_agui_raw("1"), headers={"content-type": "application/json"}
    )
    assert r.status_code == 200
    types = _assert_one_terminal(r.text)
    assert types[-1] == "RUN_ERROR"
    assert "STEP_FINISHED" in types or "STEP_STARTED" not in types
