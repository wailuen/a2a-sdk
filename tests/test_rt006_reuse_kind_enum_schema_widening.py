"""RT-006 regression (RT-B-004 follow-up): an Enum-typed ``ReuseKind`` field
must be REACHABLE through a schema-enforcing model provider, exactly like
the non-string scalar fields RT-B-004 covers.

``reuse_fields_for_model`` accepts a ``ReuseKind`` annotation on any
top-level scalar that is neither a container nor a ``BaseModel`` — an
``Enum`` qualifies. Pydantic renders an Enum-typed field as ``{"$ref":
"#/$defs/<Name>"}``, and ``_schema_permits_string`` previously treated ANY
unresolved ``$ref`` (and any ``allOf`` composition) as "already permits a
string" unconditionally, so the widening in
``input_schema(include_reuse_hint=True)`` never fired: the model was only
ever shown the enum's own members, with no way to emit the ``$ref:<kind>``
sentinel on a schema-enforcing provider (Bedrock Converse and similar) — the
mechanism silently no-opped on precisely the field shape (a closed,
provider-enforced value set) most likely to need the widening.

``_schema_permits_string`` now resolves the ``$ref`` against the schema's
own ``$defs`` before deciding, and treats any schema carrying an ``enum``
key (resolved or inline) as excluding the token even when every member is
itself a string — an enum's `type` may say "string" but its `enum` list
still doesn't include the sentinel.
"""

from __future__ import annotations

from enum import Enum, IntEnum
from typing import Annotated, Any

import pytest
from pydantic import BaseModel

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.reuse import Reusable, ReuseKind
from agent_sdk.testing import FakeModelClient, reply, tool_call


class AccountKind(str, Enum):
    CHECKING = "checking"
    SAVINGS = "savings"


class AccountStatus(IntEnum):
    OPEN = 1
    CLOSED = 2


class EnumAccountIn(BaseModel):
    account_kind: Annotated[AccountKind, ReuseKind("account_kind")]


class IntEnumAccountIn(BaseModel):
    account_status: Annotated[AccountStatus, ReuseKind("account_status")]


class ResolveIn(BaseModel):
    name: str


received_account_kinds: list[Any] = []

tools = ToolSet()


@tools.tool(tier=1)
async def resolve_account_kind(inp: ResolveIn) -> Any:
    """Resolve an account name to its kind."""
    return Reusable(value=AccountKind.CHECKING, kind="account_kind", label=inp.name)


@tools.tool(tier=1)
async def get_account_by_kind(inp: EnumAccountIn) -> str:
    """Fetch an account by kind."""
    received_account_kinds.append(inp.account_kind)
    return f"account-{inp.account_kind.value}"


@tools.tool(tier=1)
async def get_account_by_status(inp: IntEnumAccountIn) -> str:
    """Fetch an account by status (IntEnum — resolved schema excludes strings)."""
    return f"status-{inp.account_status.value}"


REGISTRY = ToolRegistry([tools], {})


def _prop(tool_name: str, field_name: str) -> dict[str, Any]:
    entry = REGISTRY.get(tool_name)
    assert entry is not None
    schema = entry.input_schema(include_reuse_hint=True)
    prop = schema["properties"][field_name]
    assert isinstance(prop, dict)
    return prop, schema


def _permits_string(prop: dict[str, Any]) -> bool:
    if prop.get("type") == "string" and "enum" not in prop:
        return True
    return any(
        isinstance(branch, dict) and branch.get("type") == "string"
        for branch in prop.get("anyOf") or []
    )


def test_str_enum_reuse_field_schema_admits_the_ref_token():
    """A str-mixin Enum's resolved schema DOES say `"type": "string"`, but
    it is still restricted to its enum members — the $ref:<kind> token is
    never one of them, so widening must still fire."""
    prop, _schema = _prop("get_account_by_kind", "account_kind")
    assert _permits_string(prop), f"$ref:<kind> must be representable: {prop!r}"
    # The original $ref branch must survive so the enum's own members are
    # still accepted too.
    assert any(
        isinstance(b, dict) and "$ref" in b for b in prop.get("anyOf") or []
    ), f"the original enum $ref must survive the widening: {prop!r}"
    assert "$ref:account_kind" in prop["description"]


def test_int_enum_reuse_field_schema_admits_the_ref_token():
    """An IntEnum's resolved schema has no 'string' type at all — the
    widening must still fire (this is the shape the pre-fix code silently
    no-opped on)."""
    prop, _schema = _prop("get_account_by_status", "account_status")
    assert _permits_string(prop), f"$ref:<kind> must be representable: {prop!r}"


def test_no_reuse_hint_leaves_enum_schema_untouched():
    entry = REGISTRY.get("get_account_by_kind")
    assert entry is not None
    plain = entry.input_schema()
    assert plain["properties"]["account_kind"] == {"$ref": "#/$defs/AccountKind"}


@pytest.mark.asyncio
async def test_enum_reuse_field_ref_token_substitutes_end_to_end():
    """The token the widened schema now permits must actually resolve, and
    the tool body must receive the field's real Enum member, not the token
    string."""
    received_account_kinds.clear()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve Acme's account kind, then fetch it"}]}
    ]
    model = FakeModelClient(
        [
            tool_call("resolve_account_kind", {"name": "Acme Corp"}),
            tool_call("get_account_by_kind", {"account_kind": "$ref:account_kind"}),
            reply("done"),
        ]
    )
    events: list[Any] = []
    async for ev in run_loop(
        model=model, registry=REGISTRY, adapters={}, system="test", messages=messages
    ):
        events.append(ev)

    results = [
        e for e in events if isinstance(e, ToolResultEvent) and e.tool_name == "get_account_by_kind"
    ]
    assert len(results) == 1
    assert results[0].ok, f"$ref on an Enum field must resolve, not fail: {results[0].error!r}"
    assert received_account_kinds == [AccountKind.CHECKING]


@pytest.mark.asyncio
async def test_enum_reuse_field_correct_raw_value_matches_end_to_end():
    """RT-002 (GH-148 follow-up): the CORRECT raw value — not a $ref token —
    supplied directly on an Enum-typed ReuseKind field must be accepted, not
    rejected as a mismatch. jsonable_reuse_value stores the resolved index
    entry JSON-safed (the enum's bare string value); without normalizing the
    coerced raw value the same way before comparing, this was rejected
    forever even though it is the value the field was already resolved to."""
    received_account_kinds.clear()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve Acme's account kind, then fetch it"}]}
    ]
    model = FakeModelClient(
        [
            tool_call("resolve_account_kind", {"name": "Acme Corp"}),
            tool_call("get_account_by_kind", {"account_kind": "checking"}),
            reply("done"),
        ]
    )
    events: list[Any] = []
    async for ev in run_loop(
        model=model, registry=REGISTRY, adapters={}, system="test", messages=messages
    ):
        events.append(ev)

    results = [
        e for e in events if isinstance(e, ToolResultEvent) and e.tool_name == "get_account_by_kind"
    ]
    assert len(results) == 1
    assert results[0].ok, (
        f"the CORRECT raw enum value must match the resolved value, not be "
        f"rejected: {results[0].error!r}"
    )
    assert received_account_kinds == [AccountKind.CHECKING]
