"""RT-B-004 regression: a ``ReuseKind`` field on a non-string scalar must be
REACHABLE through a schema-enforcing model provider.

``ReuseKind`` documents support for any top-level scalar ("str, int, or
<scalar> | None"), but ``input_schema(include_reuse_hint=True)`` only appended
the ``$ref:<kind>`` instruction to the property DESCRIPTION while leaving the
advertised type alone: an ``Annotated[int, ReuseKind("account_no")]`` field
rendered as ``{"type": "integer", "description": "... the token $ref:... "}``.
Bedrock Converse and every other provider that constrains tool arguments to
the declared JSON Schema will not let the model emit a string for an
integer-typed field, so the token was silently unusable there while
``reuse_fields_for_model`` accepted the annotation without complaint — the
same class of silent no-op the RT-007 ``TypeError`` guards exist to prevent
for containers and nested models.
"""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from pydantic import BaseModel, Field

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.reuse import Reusable, ReuseKind
from agent_sdk.testing import FakeModelClient, reply, tool_call


class AccountIn(BaseModel):
    account_no: Annotated[int, ReuseKind("account_no")]


class OptionalAccountIn(BaseModel):
    account_no: Annotated[int | None, ReuseKind("account_no")] = None


class DescribedAccountIn(BaseModel):
    account_no: Annotated[int, ReuseKind("account_no")] = Field(
        description="The ledger account number.", ge=1
    )


class EntityIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")]


class OptionalEntityIn(BaseModel):
    entity_id: Annotated[str | None, ReuseKind("entity_id")] = None


class ResolveIn(BaseModel):
    name: str


received_account_nos: list[int] = []

tools = ToolSet()


@tools.tool(tier=1)
async def resolve_account(inp: ResolveIn) -> Any:
    """Resolve an account name to its ledger number."""
    return Reusable(value=4711, kind="account_no", label=inp.name)


@tools.tool(tier=1)
async def get_account(inp: AccountIn) -> str:
    """Fetch an account by number."""
    received_account_nos.append(inp.account_no)
    return f"account-{inp.account_no}"


@tools.tool(tier=1)
async def get_optional_account(inp: OptionalAccountIn) -> str:
    """Fetch an account by optional number."""
    return f"optional-{inp.account_no}"


@tools.tool(tier=1)
async def get_described_account(inp: DescribedAccountIn) -> str:
    """Fetch an account by constrained, described number."""
    return f"described-{inp.account_no}"


@tools.tool(tier=1)
async def get_entity(inp: EntityIn) -> str:
    """Fetch an entity by id."""
    return f"entity-{inp.entity_id}"


@tools.tool(tier=1)
async def get_optional_entity(inp: OptionalEntityIn) -> str:
    """Fetch an entity by optional id."""
    return f"optional-entity-{inp.entity_id}"


REGISTRY = ToolRegistry([tools], {})


def _prop(tool_name: str, field_name: str) -> dict[str, Any]:
    entry = REGISTRY.get(tool_name)
    assert entry is not None
    schema = entry.input_schema(include_reuse_hint=True)
    prop = schema["properties"][field_name]
    assert isinstance(prop, dict)
    return prop


def _permits_string(prop: dict[str, Any]) -> bool:
    if prop.get("type") == "string":
        return True
    return any(
        isinstance(branch, dict) and branch.get("type") == "string"
        for branch in prop.get("anyOf") or []
    )


def _permits_integer(prop: dict[str, Any]) -> bool:
    if prop.get("type") == "integer":
        return True
    return any(
        isinstance(branch, dict) and branch.get("type") == "integer"
        for branch in prop.get("anyOf") or []
    )


# ── schema rendering ───────────────────────────────────────────────────────


def test_int_reuse_field_schema_admits_the_ref_token():
    """The advertised type must accept the string token, not just describe
    it in prose a schema-enforcing provider will override."""
    prop = _prop("get_account", "account_no")
    assert _permits_string(prop), (
        f"$ref:<kind> is a string token but the schema forbids strings: {prop!r}"
    )
    assert _permits_integer(prop), "the field's own integer type must still be accepted"
    assert "$ref:account_no" in prop["description"]


def test_optional_int_reuse_field_schema_admits_the_ref_token():
    prop = _prop("get_optional_account", "account_no")
    assert _permits_string(prop), f"int | None must be widened too: {prop!r}"
    assert _permits_integer(prop)


def test_widening_preserves_annotations_and_constraints():
    """Rewriting the property must not drop the field's own constraints or
    move its title/description out of the model's reach."""
    prop = _prop("get_described_account", "account_no")
    assert prop.get("title") == "Account No", "annotation keywords stay at the top level"
    assert prop["description"].startswith("The ledger account number.")
    assert "$ref:account_no" in prop["description"]
    branches = prop["anyOf"]
    original = branches[0]
    assert original.get("type") == "integer"
    assert original.get("ge") == 1 or original.get("minimum") == 1, (
        f"the field's own constraint must survive the widening: {original!r}"
    )
    assert "description" not in original, "the description is not duplicated into the branch"


def test_string_reuse_field_schema_is_untouched():
    """A str-typed field can already carry the token — its schema must be
    byte-identical to the pre-fix rendering (description hint only)."""
    prop = _prop("get_entity", "entity_id")
    assert prop.get("type") == "string"
    assert "anyOf" not in prop
    assert "$ref:entity_id" in prop["description"]

    optional = _prop("get_optional_entity", "entity_id")
    assert "pattern" not in repr(optional), "str | None already admits a string; do not widen"
    assert [b.get("type") for b in optional["anyOf"]] == ["string", "null"]


def test_no_reuse_hint_leaves_every_schema_untouched():
    """Every non-loop surface (MCP tools/list, agent card, admin console)
    asks for the schema WITHOUT the hint and must never see the widening."""
    entry = REGISTRY.get("get_account")
    assert entry is not None
    plain = entry.input_schema()
    assert plain["properties"]["account_no"] == {"title": "Account No", "type": "integer"}


def test_reuse_token_is_not_named_in_the_widened_pattern():
    """RT-002: the ``$raw:`` bypass must never be advertised to the model,
    including in a schema pattern — but a field opted into it must still be
    able to carry the token."""
    prop = _prop("get_account", "account_no")
    string_branch = next(b for b in prop["anyOf"] if b.get("type") == "string")
    assert "raw" not in string_branch.get("pattern", "")
    import re

    pattern = re.compile(string_branch["pattern"])
    assert pattern.search("$ref:account_no")
    assert pattern.search("$raw:4712")
    assert not pattern.search("4711"), "a bare number is carried by the integer branch"


# ── end-to-end through run_loop ────────────────────────────────────────────


@pytest.mark.asyncio
async def test_int_reuse_field_ref_token_substitutes_end_to_end():
    """The token the widened schema now permits must actually resolve, and
    the tool body must receive the field's real (integer) type."""
    received_account_nos.clear()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve Acme's account, then fetch it"}]}
    ]
    model = FakeModelClient(
        [
            tool_call("resolve_account", {"name": "Acme Corp"}),
            tool_call("get_account", {"account_no": "$ref:account_no"}),
            reply("done"),
        ]
    )
    events: list[Any] = []
    async for ev in run_loop(
        model=model, registry=REGISTRY, adapters={}, system="test", messages=messages
    ):
        events.append(ev)

    results = [
        e for e in events if isinstance(e, ToolResultEvent) and e.tool_name == "get_account"
    ]
    assert len(results) == 1
    assert results[0].ok, f"$ref on an int field must resolve, not fail: {results[0].error!r}"
    assert results[0].result == "account-4711"
    assert received_account_nos == [4711]
    assert isinstance(received_account_nos[0], int), (
        "the tool body must receive the field's declared type, not the token string"
    )


@pytest.mark.asyncio
async def test_int_reuse_field_still_rejects_a_mismatched_raw_value():
    """Widening the advertised type must not weaken the GH-148 correctness
    gate the mechanism exists for."""
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve Acme's account, then fetch 9999"}]}
    ]
    model = FakeModelClient(
        [
            tool_call("resolve_account", {"name": "Acme Corp"}),
            tool_call("get_account", {"account_no": 9999}),
            reply("done"),
        ]
    )
    events: list[Any] = []
    async for ev in run_loop(
        model=model, registry=REGISTRY, adapters={}, system="test", messages=messages
    ):
        events.append(ev)

    results = [
        e for e in events if isinstance(e, ToolResultEvent) and e.tool_name == "get_account"
    ]
    assert len(results) == 1
    assert results[0].ok is False
    assert results[0].error is not None
    assert "9999" not in results[0].error, "SI-2: the rejected value is never echoed"
