"""GH-225: ``@tool(emits=(A, B))`` — tuple ``emits`` for dispatcher tools.

Ruling: https://github.com/wailuen/a2a-sdk/issues/225#issuecomment-6359382542
"""

import asyncio
import gc
import logging
from typing import Any, ClassVar

import httpx
import jsonschema
import pytest
from pydantic import BaseModel

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.deferred import DeferredResult
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.runner import new_task, run_task_worker
from agent_sdk.auth.identity import Identity
from agent_sdk.example.agent import make_agent
from agent_sdk.models.content_types import (
    _REGISTRY,
    ContentModel,
    KpiCard,
    MarketBriefing,
    MetricItem,
    TimeSeriesChart,
    TimeSeriesDataPoint,
    register_content_type,
)
from agent_sdk.routes.agent_card import build_agent_card
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.testing import FakeModelClient, reply, tool_call

from .conftest import sse_frames
from .test_ag_ui import run_body
from .test_mcp_conformance_w9 import _mcp_init

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)
_CAPS = A2uiCapabilities(tier="core", catalogs=[])


def _kpi() -> KpiCard:
    return KpiCard(title="k", metrics=[MetricItem(label="Rev", value="1")])


def _chart() -> TimeSeriesChart:
    return TimeSeriesChart(
        chart_type="line",
        title="c",
        data=[TimeSeriesDataPoint(date="2026-01-01", value=1.0)],
    )


class DispatchInput(BaseModel):
    kind: str


class PA(BaseModel):
    a: int


class PB(BaseModel):
    b: str


def _dispatcher_toolset() -> ToolSet:
    ts = ToolSet()

    @ts.tool(tier=1, emits=(KpiCard, TimeSeriesChart), sample={"kind": "kpi"})
    async def dispatch(inp: DispatchInput) -> KpiCard | TimeSeriesChart:
        """Return a KPI card or a chart, or a plain dict for any other kind."""
        if inp.kind == "kpi":
            return _kpi()
        if inp.kind == "chart":
            return _chart()
        return {"other": 1}  # type: ignore[return-value]

    return ts


def _raw_toolset() -> ToolSet:
    ts = ToolSet()

    @ts.tool(tier=1, emits=(PA, PB))
    async def raw_dispatch(inp: DispatchInput):
        """Return a raw dict that must coerce into one of PA/PB."""
        if inp.kind == "a":
            return {"a": 1}
        if inp.kind == "b":
            return {"b": "x"}
        return {"zzz": "MARKER-SECRET-VALUE"}

    return ts


def _app(settings, fake_model, *extra: ToolSet, **kw: Any):
    agent = make_agent(settings, model_client=fake_model, **kw)
    agent.toolsets = agent.toolsets + list(extra)
    return agent.build_app()


async def _authed(app):
    _, token = app.state.auth.api_keys.mint("test-admin", admin=True)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


async def _worker(registry: ToolRegistry, model: FakeModelClient):
    store = InMemoryTaskStore()
    record = store.create(new_task(), _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=registry,
        adapters={},
        skills=None,
        system="s",
        capabilities=_CAPS,
        policies=__import__("agent_sdk.agent.loop", fromlist=["LoopPolicies"]).LoopPolicies(),
    )
    return store, record


async def _wait_done(store, task_id, timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while True:
        rec = store.get(task_id)
        if rec.task.status.state in ("completed", "failed"):
            return rec
        assert asyncio.get_running_loop().time() < deadline, "task stuck"
        await asyncio.sleep(0.02)


# ── decorator / normalization ──


def test_single_type_unchanged():
    ts = ToolSet()

    @ts.tool(tier=1, emits=KpiCard)
    async def one(inp: DispatchInput) -> KpiCard:
        """one"""
        return _kpi()

    decl = ts.decls[0]
    assert decl.emits is KpiCard
    assert decl.emits_types == (KpiCard,)
    assert ToolRegistry([ts], {}).get("one").output_schema() == KpiCard.model_json_schema()


def test_tuple_normalized():
    decl = _dispatcher_toolset().decls[0]
    assert decl.emits_types == (KpiCard, TimeSeriesChart)


def test_empty_tuple_rejected_at_decoration():
    ts = ToolSet()
    with pytest.raises(ValueError, match="empty"):

        @ts.tool(tier=1, emits=())
        async def t(inp: DispatchInput):
            """t"""


def test_duplicate_members_rejected():
    ts = ToolSet()
    with pytest.raises(ValueError, match="duplicate"):

        @ts.tool(tier=1, emits=(KpiCard, KpiCard))
        async def t(inp: DispatchInput):
            """t"""


# ── boot checks ──


def _boot(settings, fake_model, ts: ToolSet, **kw):
    app = _app(settings, fake_model, ts, **kw)
    app.state.credential_store.close()
    gc.collect()


def test_boot_accepts_union_covering_tuple(settings, fake_model):
    _boot(settings, fake_model, _dispatcher_toolset())


def test_boot_accepts_unannotated_any_and_common_superclass(settings, fake_model):
    ts = ToolSet()

    @ts.tool(tier=1, emits=(KpiCard, TimeSeriesChart))
    async def unannotated(inp: DispatchInput):
        """u"""

    @ts.tool(tier=1, emits=(KpiCard, TimeSeriesChart))
    async def anyret(inp: DispatchInput) -> Any:
        """a"""

    @ts.tool(tier=1, emits=(KpiCard, TimeSeriesChart))
    async def base(inp: DispatchInput) -> ContentModel:
        """b"""

    _boot(settings, fake_model, ts)


def test_boot_rejects_uncovered_union(settings, fake_model):
    ts = ToolSet()

    @ts.tool(tier=1, emits=(KpiCard, TimeSeriesChart))
    async def bad(inp: DispatchInput) -> KpiCard | None:
        """bad"""

    with pytest.raises(ValueError, match="does not match"):
        _boot(settings, fake_model, ts)


def test_boot_rejects_wrong_concrete_annotation(settings, fake_model):
    ts = ToolSet()

    @ts.tool(tier=1, emits=(KpiCard, TimeSeriesChart))
    async def bad(inp: DispatchInput) -> KpiCard:
        """bad"""

    with pytest.raises(ValueError, match="does not match"):
        _boot(settings, fake_model, ts)


def test_boot_rejects_market_briefing_member(settings, fake_model):
    ts = ToolSet()

    @ts.tool(tier=1, emits=(KpiCard, MarketBriefing))
    async def bad(inp: DispatchInput):
        """bad"""

    with pytest.raises(ValueError, match="MarketBriefing"):
        _boot(settings, fake_model, ts)


def test_boot_rejects_unregistered_content_type(settings, fake_model):
    class Unregistered(ContentModel):
        data_type: ClassVar[str] = "gh225_unregistered"
        component: ClassVar[str] = "Gh225Unregistered"

        def to_plain_text(self) -> str:
            return ""

    ts = ToolSet()

    @ts.tool(tier=1, emits=(KpiCard, Unregistered))
    async def bad(inp: DispatchInput):
        """bad"""

    with pytest.raises(ValueError, match="registered"):
        _boot(settings, fake_model, ts)


def test_boot_rejects_member_outside_allowlist(settings, fake_model):
    agent = make_agent(settings, model_client=fake_model)
    registry = ToolRegistry([_dispatcher_toolset()], {})
    agent._validate_emits(registry, allowed_components=["KpiCard", "TimeSeriesChart"])
    with pytest.raises(ValueError, match="TimeSeriesChart.*a2ui_allowed_components"):
        agent._validate_emits(registry, allowed_components=["KpiCard"])


def _inner(field: str) -> type[BaseModel]:
    return type("Inner", (BaseModel,), {"__annotations__": {field: int}})


def test_boot_rejects_defs_collision(settings, fake_model):
    class X(BaseModel):
        inner: _inner("p")  # type: ignore[valid-type]

    class Y(BaseModel):
        inner: _inner("q")  # type: ignore[valid-type]

    ts = ToolSet()

    @ts.tool(tier=1, emits=(X, Y))
    async def bad(inp: DispatchInput):
        """bad"""

    with pytest.raises(ValueError, match=r"\$defs"):
        _boot(settings, fake_model, ts)


def test_boot_accepts_async_generator_union_yield(settings, fake_model):
    from typing import AsyncIterator

    ts = ToolSet()

    @ts.tool(tier=1, emits=(KpiCard, TimeSeriesChart))
    async def gen(inp: DispatchInput) -> AsyncIterator[KpiCard | TimeSeriesChart]:
        """g"""
        yield _kpi()

    _boot(settings, fake_model, ts)


# ── A2A + AG-UI + deferred cards ──


@pytest.mark.parametrize(
    "kind,data_type", [("kpi", "kpi_card"), ("chart", "time_series")]
)
async def test_a2a_card_labelled_with_result_type(kind, data_type):
    registry = ToolRegistry([_dispatcher_toolset()], {})
    model = FakeModelClient().script(tool_call("dispatch", {"kind": kind}), reply("done"))
    store, record = await _worker(registry, model)
    rec = await _wait_done(store, record.task.id)
    assert [a.metadata["data_type"] for a in rec.task.artifacts] == [data_type]


async def test_a2a_unmatched_result_gets_no_card():
    registry = ToolRegistry([_dispatcher_toolset()], {})
    model = FakeModelClient().script(tool_call("dispatch", {"kind": "zzz"}), reply("done"))
    store, record = await _worker(registry, model)
    rec = await _wait_done(store, record.task.id)
    assert rec.task.artifacts == []


@pytest.mark.parametrize(
    "kind,data_type", [("kpi", "kpi_card"), ("chart", "time_series")]
)
async def test_ag_ui_card_labelled_with_result_type(settings, fake_model, kind, data_type):
    app = _app(settings, fake_model, _dispatcher_toolset())
    try:
        async with app.router.lifespan_context(app):
            async with await _authed(app) as c:
                fake_model.script(tool_call("dispatch", {"kind": kind}), reply("done"))
                r = await c.post("/ag-ui/run", json=run_body("go"))
                frames = sse_frames(r.text)
                arts = [
                    f for f in frames if f["type"] == "CUSTOM" and f["name"] == "AGENT_ARTIFACT"
                ]
                assert [f["value"]["dataType"] for f in arts] == [data_type]
    finally:
        app.state.credential_store.close()
        gc.collect()


async def test_ag_ui_unmatched_result_gets_no_card(settings, fake_model):
    app = _app(settings, fake_model, _dispatcher_toolset())
    try:
        async with app.router.lifespan_context(app):
            async with await _authed(app) as c:
                fake_model.script(tool_call("dispatch", {"kind": "zzz"}), reply("done"))
                r = await c.post("/ag-ui/run", json=run_body("go"))
                frames = sse_frames(r.text)
                assert not [
                    f for f in frames if f["type"] == "CUSTOM" and f["name"] == "AGENT_ARTIFACT"
                ]
    finally:
        app.state.credential_store.close()
        gc.collect()


def _deferred_toolset(emits, value) -> ToolSet:
    ts = ToolSet()

    async def job():
        await asyncio.sleep(0)
        return value

    kwargs: dict[str, Any] = {"tier": 1, "long_running": True, "tool_timeout_override": 10.0}
    if emits is not None:
        kwargs["emits"] = emits

    @ts.tool(**kwargs)
    async def deferred_tool() -> DeferredResult:
        """deferred"""
        return DeferredResult(handle=job())

    return ts


async def _deferred_artifact(emits, value):
    registry = ToolRegistry([_deferred_toolset(emits, value)], {})
    model = FakeModelClient().script(tool_call("deferred_tool", {}))
    store, record = await _worker(registry, model)
    rec = await _wait_done(store, record.task.id)
    assert rec.task.status.state == "completed"
    assert len(rec.task.artifacts) == 1
    return rec.task.artifacts[0]


def _is_text_only(artifact) -> bool:
    return [p.kind for p in artifact.parts] == ["text"]


@pytest.mark.parametrize(
    "value,data_type", [(_kpi, "kpi_card"), (_chart, "time_series")]
)
async def test_deferred_tuple_labelled_with_matching_member(value, data_type):
    art = await _deferred_artifact((KpiCard, TimeSeriesChart), value())
    assert art.metadata["data_type"] == data_type
    assert art.name == data_type
    assert not _is_text_only(art)


async def test_deferred_tuple_no_match_is_text_only():
    art = await _deferred_artifact((KpiCard, TimeSeriesChart), {"x": 1})
    assert _is_text_only(art)
    assert art.name == "deferred_tool"
    assert art.metadata["data_type"] == "deferred_tool"


async def test_deferred_single_type_non_member_is_text_only():
    art = await _deferred_artifact(KpiCard, _chart())
    assert _is_text_only(art)
    assert art.name == "deferred_tool"


async def test_deferred_single_type_member_unchanged():
    art = await _deferred_artifact(KpiCard, _kpi())
    assert art.metadata["data_type"] == "kpi_card"
    assert not _is_text_only(art)


async def test_deferred_emits_none_unchanged():
    art = await _deferred_artifact(None, _chart())
    assert art.name == "deferred_tool"
    assert not _is_text_only(art)


async def _deferred_ag_ui_frames(emits, value):
    from agent_sdk.routes.ag_ui import _RunMapper

    store = InMemoryTaskStore()
    record = store.create(new_task(), _IDENTITY)
    record.messages.append({"role": "user", "content": [{"text": "go"}]})
    sub = store.subscribe(record.task.id)
    registry = ToolRegistry([_deferred_toolset(emits, value)], {})
    model = FakeModelClient().script(tool_call("deferred_tool", {}))
    from agent_sdk.agent.loop import LoopPolicies

    await run_task_worker(
        store=store,
        record=record,
        model=model,
        registry=registry,
        adapters={},
        skills=None,
        system="s",
        capabilities=_CAPS,
        policies=LoopPolicies(),
    )
    await _wait_done(store, record.task.id)
    mapper = _RunMapper("t", "r", _CAPS)
    frames: list[dict[str, Any]] = []
    while True:
        item = await asyncio.wait_for(sub.get(), timeout=3.0)
        if item is None:
            break
        frames.extend(mapper.map(item.event))
    return frames


async def test_deferred_no_match_ag_ui_has_no_card():
    frames = await _deferred_ag_ui_frames((KpiCard, TimeSeriesChart), {"x": 1})
    assert not [f for f in frames if f.get("name") == "AGENT_ARTIFACT"]
    assert not [f for f in frames if f.get("type") == "A2UI_UPDATE" or f.get("name") == "A2UI_UPDATE"]


async def test_deferred_single_type_non_member_content_model_ag_ui_has_no_card():
    frames = await _deferred_ag_ui_frames(KpiCard, _chart())
    assert not [f for f in frames if f.get("name") == "AGENT_ARTIFACT"]
    assert not [f for f in frames if "A2UI" in str(f.get("name", "")) + str(f.get("type", ""))]


async def test_deferred_tuple_member_ag_ui_labelled_with_member_type():
    frames = await _deferred_ag_ui_frames((KpiCard, TimeSeriesChart), _chart())
    arts = [f for f in frames if f.get("name") == "AGENT_ARTIFACT"]
    assert [f["value"]["dataType"] for f in arts] == ["time_series"]


# ── MCP ──


def _call(i: int, name: str, args: dict) -> dict:
    return {
        "jsonrpc": "2.0",
        "id": i,
        "method": "tools/call",
        "params": {"name": name, "arguments": args},
    }


async def test_mcp_output_schema_anyof_validates_both_shapes(settings, fake_model):
    app = _app(settings, fake_model, _dispatcher_toolset())
    try:
        async with app.router.lifespan_context(app):
            async with await _authed(app) as c:
                h = await _mcp_init(c)
                r = await c.post(
                    "/mcp",
                    json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
                    headers=h,
                )
                tool = next(t for t in r.json()["result"]["tools"] if t["name"] == "dispatch")
                schema = tool["outputSchema"]
                assert schema["type"] == "object"
                assert len(schema["anyOf"]) == 2
                assert all("$defs" not in m for m in schema["anyOf"])

                def titles(node: Any) -> list[str]:
                    found: list[str] = []
                    if isinstance(node, dict):
                        for k, v in node.items():
                            if k == "title" and isinstance(v, str):
                                found.append(v)
                            elif k in ("properties", "$defs"):
                                for sub in v.values():
                                    found += titles(sub)
                            else:
                                found += titles(v)
                    elif isinstance(node, list):
                        for item in node:
                            found += titles(item)
                    return found

                assert titles(schema["anyOf"]) == []
                assert titles(schema.get("$defs", {})) == []
                jsonschema.Draft202012Validator.check_schema(schema)

                for i, kind in enumerate(("kpi", "chart")):
                    resp = await c.post("/mcp", json=_call(10 + i, "dispatch", {"kind": kind}), headers=h)
                    res = resp.json()["result"]
                    assert res["isError"] is False
                    jsonschema.validate(res["structuredContent"], schema)
    finally:
        app.state.credential_store.close()
        gc.collect()


async def test_mcp_raw_dict_coerces_first_valid_member_and_hides_values(
    settings, fake_model, caplog
):
    app = _app(settings, fake_model, _raw_toolset())
    try:
        async with app.router.lifespan_context(app):
            async with await _authed(app) as c:
                h = await _mcp_init(c)
                for i, (kind, expected) in enumerate((("a", {"a": 1}), ("b", {"b": "x"}))):
                    resp = await c.post("/mcp", json=_call(20 + i, "raw_dispatch", {"kind": kind}), headers=h)
                    res = resp.json()["result"]
                    assert res["isError"] is False
                    assert res["structuredContent"] == expected
                with caplog.at_level(logging.DEBUG):
                    resp = await c.post("/mcp", json=_call(30, "raw_dispatch", {"kind": "zzz"}), headers=h)
                res = resp.json()["result"]
                assert res["isError"] is True
                assert res["content"][0]["text"] == "tool output coercion failed"
                assert "MARKER-SECRET-VALUE" not in resp.text
                assert "MARKER-SECRET-VALUE" not in caplog.text
                assert "ValidationError" in caplog.text
    finally:
        app.state.credential_store.close()
        gc.collect()


# ── agent card ──


class _DomA(ContentModel):
    catalog_id: ClassVar[str] = "urn:test-gh225-a:v1"
    data_type: ClassVar[str] = "gh225_a"
    component: ClassVar[str] = "Gh225A"

    def to_plain_text(self) -> str:
        return ""


class _DomB(ContentModel):
    catalog_id: ClassVar[str] = "urn:test-gh225-b:v1"
    data_type: ClassVar[str] = "gh225_b"
    component: ClassVar[str] = "Gh225B"

    def to_plain_text(self) -> str:
        return ""


def test_card_x_sdk_emits_list_and_catalogs(settings):
    register_content_type(_DomA)
    register_content_type(_DomB)
    try:
        ts = ToolSet()

        @ts.tool(tier=1, emits=(_DomA, _DomB))
        async def dom(inp: DispatchInput) -> _DomA | _DomB:
            """d"""
            return _DomA()

        @ts.tool(tier=1, emits=KpiCard)
        async def single(inp: DispatchInput) -> KpiCard:
            """s"""
            return _kpi()

        card = build_agent_card(settings, ToolRegistry([ts], {}))
        skills = {s["id"]: s for s in card["skills"]}
        assert skills["dom"]["x-sdk"]["emits"] == ["gh225_a", "gh225_b"]
        assert skills["single"]["x-sdk"]["emits"] == "kpi_card"
        a2ui = next(e for e in card["capabilities"]["extensions"] if e["uri"].endswith("a2ui/v0.9.1"))
        ids = a2ui["params"]["supportedCatalogIds"]
        assert "urn:test-gh225-a:v1" in ids and "urn:test-gh225-b:v1" in ids
    finally:
        _REGISTRY.pop("gh225_a", None)
        _REGISTRY.pop("gh225_b", None)



# --- LRN-469 (w061 protocol audit, release-gate fix) -------------------------


class _Other(BaseModel):
    c: int = 1


def _mismatch_toolset() -> ToolSet:
    ts = ToolSet()

    @ts.tool(tier=1, emits=(KpiCard, TimeSeriesChart))
    async def lrn469_multi():
        """Returns a model outside its declared tuple."""
        return _Other()

    @ts.tool(tier=1, emits=KpiCard)
    async def lrn469_single():
        """Returns a model other than its single declared type."""
        return _Other()

    return ts


async def test_lrn469_undeclared_model_type_is_mcp_tool_error(settings, fake_model):
    """Under an advertised outputSchema, a model of an undeclared type can
    neither carry conforming structuredContent nor succeed without it."""
    app = _app(settings, fake_model, _mismatch_toolset())
    try:
        async with app.router.lifespan_context(app):
            async with await _authed(app) as c:
                h = await _mcp_init(c)
                for i, name in enumerate(("lrn469_multi", "lrn469_single")):
                    resp = await c.post("/mcp", json=_call(40 + i, name, {}), headers=h)
                    res = resp.json()["result"]
                    assert res["isError"] is True, name
                    assert "structuredContent" not in res
                    assert res["content"][0]["text"] == "tool output does not match its declared type"
                    assert "_Other" not in res["content"][0]["text"]
    finally:
        app.state.credential_store.close()
        gc.collect()
