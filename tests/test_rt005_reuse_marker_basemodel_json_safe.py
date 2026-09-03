"""RT-005 regression: a `Reusable` wrapping a BaseModel/ContentModel value
must not plant a live pydantic object inside `messages`.

`agent/reuse.py::Reusable`'s own docstring says `ToolDecl.emits` matching is
checked against the *unwrapped* value — i.e. a `BaseModel` return is an
explicitly supported shape. `agent/loop.py` folded `result.value` into the
`__resolved__` marker raw, unlike the sibling result block
(`_fold_result_content`), which normalizes a `BaseModel` via
`model_dump(mode="json")`. A `Reusable(value=SomeContentModel(...))`
therefore planted a live pydantic object inside `messages`, and the next
model call serializes that list — `json.dumps(messages)` raised
`TypeError: Object of type <Model> is not JSON serializable`, breaking the
whole conversation, not just that tool.
"""

from __future__ import annotations

import json
from typing import Annotated, Any

import pytest
from pydantic import BaseModel

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.reuse import Reusable, ReuseKind
from agent_sdk.testing import FakeModelClient, reply, tool_call

pytestmark = pytest.mark.asyncio


class EntityModel(BaseModel):
    entity_id: str
    name: str


class ResolveIn(BaseModel):
    name: str


class DetailIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")]


tools = ToolSet()


@tools.tool(tier=1)
async def resolve_entity_model(inp: ResolveIn) -> Any:
    """Resolve a name to a BaseModel entity, wrapped Reusable."""
    return Reusable(
        value=EntityModel(entity_id="ENT_1", name=inp.name),
        kind="entity",
        label=inp.name,
    )


@tools.tool(tier=1)
async def resolve_id(inp: ResolveIn) -> Any:
    """Resolve a name to a plain id string, wrapped Reusable."""
    return Reusable(value="ENT_5831", kind="entity_id", label=inp.name)


@tools.tool(tier=1)
async def get_detail(inp: DetailIn) -> str:
    """Fetch details for a resolved entity id."""
    return f"detail-{inp.entity_id}"


REGISTRY = ToolRegistry([tools], {})


async def _run(model: FakeModelClient, messages: list[dict[str, Any]]) -> list[Any]:
    events: list[Any] = []
    async for ev in run_loop(
        model=model,
        registry=REGISTRY,
        adapters={},
        system="test",
        messages=messages,
    ):
        events.append(ev)
    return events


async def test_reusable_basemodel_value_json_safe_in_messages():
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve Acme"}]}
    ]
    model = FakeModelClient(
        [tool_call("resolve_entity_model", {"name": "Acme"}), reply("done")]
    )

    await _run(model, messages)

    # The whole point: messages must round-trip through json.dumps exactly
    # as it is serialized for the next model call / wire transport.
    json.dumps(messages)

    tool_result_msg = messages[-2]
    content = tool_result_msg["content"][0]["toolResult"]["content"]
    marker_block = next(
        block["json"]["__resolved__"]
        for block in content
        if isinstance(block.get("json"), dict) and "__resolved__" in block["json"]
    )
    assert marker_block["value"] == {"entity_id": "ENT_1", "name": "Acme"}


async def test_reusable_plain_value_still_matches_raw_argument_same_turn():
    """Non-BaseModel Reusable values (the common case — an id string) must
    keep matching a raw argument in a downstream call within the same turn,
    unaffected by the JSON-normalization added for the BaseModel case."""

    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]
    model = FakeModelClient(
        [
            tool_call("resolve_id", {"name": "Acme"}, tool_call_id="c1"),
            tool_call("get_detail", {"entity_id": "ENT_5831"}, tool_call_id="c2"),
            reply("done"),
        ]
    )

    events = await _run(model, messages)

    results = [e for e in events if isinstance(e, ToolResultEvent)]
    detail_result = next(r for r in results if r.tool_name == "get_detail")
    assert detail_result.ok, detail_result.error
    assert detail_result.result == "detail-ENT_5831"
