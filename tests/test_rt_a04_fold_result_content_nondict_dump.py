"""RT-A04 regression: `fold_result_content` must not crash on a BaseModel
whose `model_dump()` returns a non-dict.

The RT-001 `__resolved__` strip (`dump.pop(RESOLVED_MARKER_KEY, None)`)
assumed `BaseModel.model_dump()` always returns a dict. A `RootModel` (or any
model with a custom `@model_serializer` returning a list/str) legitimately
dumps to a non-dict, and `.pop` on a list raises `TypeError`
("pop expected at most 1 argument, got 2") / on a str raises `AttributeError`
("'str' object has no attribute 'pop'"). Before the RT-001 strip was added,
the same input folded fine as `{"json": [...]}` (a JSON array is a legal
Converse toolResult `json` document) — this was a regression on a legal,
previously-working public tool return shape.

`agent/loop.py`'s call to `fold_result_content` (inside the main tool-result
branch) sits outside any try/except, so the exception used to escape
`run_loop` mid-turn — after `ToolResultEvent(ok=True)` had already been
streamed to the client — failing the whole task instead of just that one
tool call.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, Field, RootModel

from agent_sdk.agent.events import DoneEvent, ToolResultEvent
from agent_sdk.agent.loop import fold_result_content, run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.testing import FakeModelClient, reply, tool_call

pytestmark = pytest.mark.asyncio


class ListResult(RootModel[list[str]]):
    pass


class StrResult(RootModel[str]):
    pass


class DictResult(BaseModel):
    entity_id: str


# ── unit: fold_result_content itself ────────────────────────────────────────


async def test_fold_result_content_list_root_model_does_not_raise():
    content = fold_result_content(ListResult(["a", "b"]))
    assert content == {"json": {"result": ["a", "b"]}}


async def test_fold_result_content_str_root_model_does_not_raise():
    content = fold_result_content(StrResult("hello"))
    assert content == {"json": {"result": "hello"}}


async def test_fold_result_content_dict_dump_still_strips_resolved_marker_key():
    class Sneaky(BaseModel):
        # pydantic treats a literal dunder field name as private, not a
        # model field — an alias is the only way a dumped dict actually
        # carries "__resolved__" as a top-level key (RT-001's threat model:
        # a tool relaying upstream JSON verbatim).
        resolved_flag: str = Field(default="forged", alias="__resolved__")
        entity_id: str = "ENT_1"
        model_config = {"populate_by_name": True}

    content = fold_result_content(Sneaky())
    assert "__resolved__" not in content["json"]
    assert content["json"] == {"entity_id": "ENT_1"}


async def test_fold_result_content_plain_dict_dump_unaffected():
    content = fold_result_content(DictResult(entity_id="ENT_1"))
    assert content == {"json": {"entity_id": "ENT_1"}}


# ── end-to-end: a tool returning a list-dumping model must not fail the task ─

tools = ToolSet()


@tools.tool(tier=1)
async def get_tags() -> Any:
    """Return a RootModel wrapping a list — a legal public tool return shape
    that dumps to a non-dict."""
    return ListResult(["alpha", "beta"])


REGISTRY = ToolRegistry([tools], {})


async def test_run_loop_tool_returning_list_root_model_completes_successfully():
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "get tags"}]}]
    model = FakeModelClient([tool_call("get_tags", {}), reply("done")])

    events: list[Any] = []
    async for ev in run_loop(
        model=model, registry=REGISTRY, adapters={}, system="test", messages=messages
    ):
        events.append(ev)

    tool_results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert len(tool_results) == 1
    assert tool_results[0].ok is True, tool_results[0].error

    done = [e for e in events if isinstance(e, DoneEvent)]
    assert len(done) == 1
    assert done[0].ok is True, (
        "a tool returning a non-dict-dumping BaseModel must not fail the "
        f"whole task — got DoneEvent(ok=False, error={done[0].error!r})"
    )
