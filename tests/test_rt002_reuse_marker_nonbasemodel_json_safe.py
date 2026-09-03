"""RT-002 regression: a `Reusable` wrapping a non-BaseModel, non-JSON-native
value (UUID, datetime, ...) must not plant a live Python object inside
`messages`.

`agent/loop.py::_jsonable_reuse_value` previously special-cased `BaseModel`
only (RT-005's fix), leaving every other non-JSON-native `Reusable.value` —
a `UUID`, `datetime`, `Decimal`, `Enum`, a dataclass, or any other domain
object — planted raw into the `__resolved__` marker folded into `messages`.
The sibling `fold_result_content` block in the SAME toolResult correctly
stringifies such a value; the marker block did not. `json.dumps(messages)`
then raises on the very next model call.
"""

from __future__ import annotations

import dataclasses
import datetime
import enum
import json
import uuid
from typing import Annotated, Any

import pytest

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.reuse import Reusable, ReuseKind
from agent_sdk.testing import FakeModelClient, reply, tool_call
from pydantic import BaseModel

pytestmark = pytest.mark.asyncio


class Status(enum.Enum):
    ACTIVE = "active"


@dataclasses.dataclass
class Coordinates:
    lat: float
    lon: float


class ResolveIn(BaseModel):
    name: str


class DetailIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")]


ENTITY_UUID = uuid.UUID("12345678-1234-5678-1234-567812345678")
RESOLVED_AT = datetime.datetime(2026, 9, 2, 12, 0, 0)

tools = ToolSet()


@tools.tool(tier=1)
async def resolve_uuid(inp: ResolveIn) -> Any:
    """Resolve a name to a UUID entity id, wrapped Reusable."""
    return Reusable(value=ENTITY_UUID, kind="entity_id", label=inp.name)


@tools.tool(tier=1)
async def resolve_datetime(inp: ResolveIn) -> Any:
    """Resolve a name to a datetime, wrapped Reusable."""
    return Reusable(value=RESOLVED_AT, kind="resolved_at", label=inp.name)


@tools.tool(tier=1)
async def resolve_enum(inp: ResolveIn) -> Any:
    """Resolve a name to an Enum status, wrapped Reusable."""
    return Reusable(value=Status.ACTIVE, kind="status", label=inp.name)


@tools.tool(tier=1)
async def resolve_dataclass(inp: ResolveIn) -> Any:
    """Resolve a name to a dataclass, wrapped Reusable."""
    return Reusable(value=Coordinates(lat=1.5, lon=2.5), kind="coords", label=inp.name)


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


def _marker_value(messages: list[dict[str, Any]]) -> Any:
    tool_result_msg = messages[-2]
    content = tool_result_msg["content"][0]["toolResult"]["content"]
    marker = next(
        block["json"]["__resolved__"]
        for block in content
        if isinstance(block.get("json"), dict) and "__resolved__" in block["json"]
    )
    return marker["value"]


@pytest.mark.parametrize(
    "tool_name, expected_value",
    [
        ("resolve_uuid", str(ENTITY_UUID)),
        ("resolve_datetime", RESOLVED_AT.isoformat()),
        ("resolve_enum", "active"),
        ("resolve_dataclass", {"lat": 1.5, "lon": 2.5}),
    ],
)
async def test_reusable_nonbasemodel_value_json_safe_in_messages(
    tool_name: str, expected_value: Any
) -> None:
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve Acme"}]}
    ]
    model = FakeModelClient([tool_call(tool_name, {"name": "Acme"}), reply("done")])

    await _run(model, messages)

    # The whole point: messages must round-trip through json.dumps exactly
    # as it is serialized for the next model call / wire transport.
    json.dumps(messages)

    assert _marker_value(messages) == expected_value


async def test_reusable_uuid_value_still_matches_raw_argument_same_turn() -> None:
    """A UUID Reusable value must still round-trip through the reuse
    match/substitution check within the same turn: the raw argument supplied
    to a downstream tool call is the stringified UUID, matching what the
    model actually saw as the tool's result."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]
    model = FakeModelClient(
        [
            tool_call("resolve_uuid", {"name": "Acme"}, tool_call_id="c1"),
            tool_call(
                "get_detail", {"entity_id": str(ENTITY_UUID)}, tool_call_id="c2"
            ),
            reply("done"),
        ]
    )

    events = await _run(model, messages)

    results = [e for e in events if isinstance(e, ToolResultEvent)]
    detail_result = next(r for r in results if r.tool_name == "get_detail")
    assert detail_result.ok, detail_result.error
    assert detail_result.result == f"detail-{ENTITY_UUID}"
