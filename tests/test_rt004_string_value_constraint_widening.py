"""RT-004 regression: a ``ReuseKind`` field on a STRING scalar whose value
space is narrowed by ``pattern``/``const``/``format``/``minLength``/
``maxLength`` must still be REACHABLE through a schema-enforcing model
provider.

``_schema_permits_string`` (registry.py) already widened a non-string scalar
(RT-B-004) and a resolved ``enum``/``$ref``/``allOf`` shape (RT-006), but it
still returned ``True`` ("no widening needed") for a string-typed schema
carrying one of those five constraining keywords — the model can never emit
the literal ``$ref:<kind>``/``$raw:<value>`` sentinel on
``{"type": "string", "pattern": "^ENT_"}`` (or ``const``/``format``/
``minLength``/``maxLength``), so the description-only hint promised an
affordance the schema forbids.
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

import pytest
from pydantic import BaseModel, Field

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.reuse import ReuseKind
from agent_sdk.testing import FakeModelClient, reply, tool_call


class PatternEntityIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")] = Field(pattern="^ENT_")


class MaxLenEntityIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")] = Field(max_length=8)


class MinLenEntityIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")] = Field(min_length=4)


class FormatEntityIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")] = Field(
        json_schema_extra={"format": "uuid"}
    )


class ConstEntityIn(BaseModel):
    entity_id: Annotated[Literal["ENT_1"], ReuseKind("entity_id")]


class ResolveIn(BaseModel):
    name: str


tools = ToolSet()


@tools.tool(tier=1)
async def resolve_entity(inp: ResolveIn) -> Any:
    """Resolve an entity name to its id."""
    from agent_sdk.agent.reuse import Reusable

    return Reusable(value="ENT_4711", kind="entity_id", label=inp.name)


@tools.tool(tier=1)
async def get_pattern_entity(inp: PatternEntityIn) -> str:
    """Fetch an entity by pattern-constrained id."""
    return f"pattern-{inp.entity_id}"


@tools.tool(tier=1)
async def get_maxlen_entity(inp: MaxLenEntityIn) -> str:
    """Fetch an entity by max-length-constrained id."""
    return f"maxlen-{inp.entity_id}"


@tools.tool(tier=1)
async def get_minlen_entity(inp: MinLenEntityIn) -> str:
    """Fetch an entity by min-length-constrained id."""
    return f"minlen-{inp.entity_id}"


@tools.tool(tier=1)
async def get_const_entity(inp: ConstEntityIn) -> str:
    """Fetch an entity by const-constrained id."""
    return f"const-{inp.entity_id}"


@tools.tool(tier=1)
async def get_format_entity(inp: FormatEntityIn) -> str:
    """Fetch an entity by format-constrained id."""
    return f"format-{inp.entity_id}"


REGISTRY = ToolRegistry([tools], {})


def _prop(tool_name: str, field_name: str) -> dict[str, Any]:
    entry = REGISTRY.get(tool_name)
    assert entry is not None
    schema = entry.input_schema(include_reuse_hint=True)
    prop = schema["properties"][field_name]
    assert isinstance(prop, dict)
    return prop


def _has_token_branch(prop: dict[str, Any]) -> bool:
    """True when some ``anyOf`` branch is the widened sentinel branch that
    admits the ``$ref:``/``$raw:`` token — mirrors
    test_rt_b004_reuse_kind_nonstring_scalar_schema.py's ``_permits_string``.
    Actual resolvability is pinned end-to-end below, not by this shape check
    alone."""
    return any(
        isinstance(b, dict) and b.get("type") == "string" and b.get("pattern") == r"^\$"
        for b in prop.get("anyOf") or []
    )


# ── schema rendering ───────────────────────────────────────────────────────


def test_pattern_constrained_string_is_widened():
    prop = _prop("get_pattern_entity", "entity_id")
    assert _has_token_branch(prop), (
        f"pattern schema must gain an unconstrained string branch for the token: {prop!r}"
    )
    branches = prop["anyOf"]
    original = next(b for b in branches if b.get("pattern") == "^ENT_")
    assert original.get("type") == "string"


def test_maxlength_constrained_string_is_widened():
    prop = _prop("get_maxlen_entity", "entity_id")
    assert _has_token_branch(prop), f"maxLength schema must be widened: {prop!r}"
    original = next(b for b in prop["anyOf"] if b.get("maxLength") == 8)
    assert original.get("type") == "string"


def test_minlength_constrained_string_is_widened():
    prop = _prop("get_minlen_entity", "entity_id")
    assert _has_token_branch(prop), f"minLength schema must be widened: {prop!r}"
    original = next(b for b in prop["anyOf"] if b.get("minLength") == 4)
    assert original.get("type") == "string"


def test_const_constrained_string_is_widened():
    prop = _prop("get_const_entity", "entity_id")
    assert _has_token_branch(prop), f"const schema must be widened: {prop!r}"
    original = next(b for b in prop["anyOf"] if "const" in b)
    assert original.get("const") == "ENT_1"


def test_format_constrained_string_is_widened():
    prop = _prop("get_format_entity", "entity_id")
    assert _has_token_branch(prop), f"format schema must be widened: {prop!r}"
    original = next(b for b in prop["anyOf"] if b.get("format") == "uuid")
    assert original.get("type") == "string"


def test_widened_pattern_schema_preserves_title_and_hint():
    prop = _prop("get_pattern_entity", "entity_id")
    assert prop.get("title") == "Entity Id"
    assert "$ref:entity_id" in prop["description"]


# ── end-to-end through run_loop ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pattern_entity_ref_token_substitutes_end_to_end():
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve Acme, then fetch its entity"}]}
    ]
    model = FakeModelClient(
        [
            tool_call("resolve_entity", {"name": "Acme Corp"}),
            tool_call("get_pattern_entity", {"entity_id": "$ref:entity_id"}),
            reply("done"),
        ]
    )
    events: list[Any] = []
    async for ev in run_loop(
        model=model, registry=REGISTRY, adapters={}, system="test", messages=messages
    ):
        events.append(ev)

    results = [
        e for e in events if isinstance(e, ToolResultEvent) and e.tool_name == "get_pattern_entity"
    ]
    assert len(results) == 1
    assert results[0].ok, f"$ref on a pattern-constrained field must resolve: {results[0].error!r}"
    assert results[0].result == "pattern-ENT_4711"


def test_no_reuse_hint_leaves_pattern_schema_untouched():
    entry = REGISTRY.get("get_pattern_entity")
    assert entry is not None
    plain = entry.input_schema()
    assert plain["properties"]["entity_id"] == {
        "title": "Entity Id",
        "type": "string",
        "pattern": "^ENT_",
    }
