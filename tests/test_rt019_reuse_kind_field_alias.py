"""RT-019 regression (GH-148 follow-up): ``ReuseKind`` must key on the WIRE
name of a field, not the python attribute name, when the field declares a
pydantic alias.

``reuse_fields_for_model`` / ``reuse_strict_for_model`` /
``reuse_raw_override_for_model`` keyed their returned maps on
``input_model.model_fields``'s dict keys — the python field name. But
``model_json_schema()`` advertises the field under its alias (whenever one is
declared), and ``model_validate`` requires the SAME alias as the input key
(verified: ``Field(alias=...)`` populates ``validation_alias`` to match, and
``model_validate`` rejects the plain field name outright). The model only
ever sees and sends the alias-keyed argument, so
``resolve_reuse_fields``'s ``field_name not in arguments`` was always true
for an aliased field — the whole GH-148 gate silently fails open: no
substitution, no mismatch rejection, and a raw ``$ref:<kind>`` token reaches
the tool body verbatim as a literal string. ``ToolEntry.input_schema``'s
``$ref`` hint (RT-010) was silently omitted for the same reason (its
``properties.get(field_name)`` lookup missed, keyed on the wrong name).

Fix: key all three maps, and the ``input_schema`` hint lookup, on the wire
name pydantic actually uses (``field_info.validation_alias`` if a plain
string, else ``field_info.alias``, else the field name).
"""

from __future__ import annotations

from typing import Annotated, Any

from pydantic import BaseModel, Field

from agent_sdk.agent.events import AuditEvent, ToolResultEvent
from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolDecl, ToolEntry, ToolRegistry, ToolSet
from agent_sdk.agent.reuse import (
    ReuseKind,
    Reusable,
    reuse_fields_for_model,
    reuse_raw_override_for_model,
    reuse_strict_for_model,
)
from agent_sdk.testing import FakeModelClient, reply, tool_call

# ---------------------------------------------------------------------------
# Unit: the field-name -> kind/strict/raw_override maps key on the wire name
# ---------------------------------------------------------------------------


class _AliasedIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id", allow_raw_override=True)] = Field(
        alias="entityId"
    )


def test_reuse_fields_for_model_keys_on_alias_not_field_name():
    assert reuse_fields_for_model(_AliasedIn) == {"entityId": "entity_id"}


def test_reuse_strict_for_model_keys_on_alias_not_field_name():
    assert reuse_strict_for_model(_AliasedIn) == {"entityId": True}


def test_reuse_raw_override_for_model_keys_on_alias_not_field_name():
    assert reuse_raw_override_for_model(_AliasedIn) == {"entityId": True}


def test_unaliased_field_still_keys_on_field_name():
    class Plain(BaseModel):
        entity_id: Annotated[str, ReuseKind("entity_id")]

    assert reuse_fields_for_model(Plain) == {"entity_id": "entity_id"}


# ---------------------------------------------------------------------------
# Unit: ToolEntry.input_schema's $ref hint (RT-010) reaches the aliased prop
# ---------------------------------------------------------------------------


def test_input_schema_reuse_hint_reaches_aliased_property():
    async def _fn(inp: _AliasedIn) -> None:  # pragma: no cover - not invoked
        """no-op"""

    decl = ToolDecl(
        fn=_fn,
        name="reuse_tool",
        description="no-op",
        tier=1,
        emits=None,
        sample=None,
        input_model=_AliasedIn,
        adapter_params={},
        reuse_fields=reuse_fields_for_model(_AliasedIn),
    )
    schema = ToolEntry(decl=decl).input_schema(include_reuse_hint=True)
    assert "entityId" in schema["properties"], schema["properties"]
    description = schema["properties"]["entityId"].get("description", "")
    assert "$ref:entity_id" in description, description


# ---------------------------------------------------------------------------
# End-to-end: mismatch rejection + $ref substitution fire for an aliased field
# ---------------------------------------------------------------------------

_ENTITY_IDS = {"PT IMC Pelita Logistik": "ENT_5831"}

alias_tools = ToolSet()
received_entity_ids: list[str] = []


class _ResolveIn(BaseModel):
    name: str


@alias_tools.tool(tier=1)
async def resolve_entity_alias(inp: _ResolveIn) -> Any:
    """Resolve a company name to its canonical entity id."""
    return Reusable(value=_ENTITY_IDS[inp.name], kind="entity_id", label=inp.name)


@alias_tools.tool(tier=1)
async def get_entity_detail_alias(inp: _AliasedIn) -> str:
    """Fetch details for a resolved entity id (aliased input field)."""
    received_entity_ids.append(inp.entity_id)
    return f"detail-for-{inp.entity_id}"


ALIAS_REGISTRY = ToolRegistry([alias_tools], {})


async def _run(model: FakeModelClient, messages: list[dict[str, Any]]) -> list[Any]:
    events: list[Any] = []
    async for ev in run_loop(
        model=model, registry=ALIAS_REGISTRY, adapters={}, system="test", messages=messages
    ):
        events.append(ev)
    return events


def _tool_results(events: list[Any]) -> list[ToolResultEvent]:
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert results, "expected at least one ToolResultEvent"
    return results


async def test_aliased_field_wrong_raw_id_rejected_then_ref_substitution_succeeds():
    received_entity_ids.clear()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve PT IMC Pelita Logistik"}]}
    ]

    model1 = FakeModelClient(
        [
            tool_call("resolve_entity_alias", {"name": "PT IMC Pelita Logistik"}),
            reply("resolved"),
        ]
    )
    events1 = await _run(model1, messages)
    result1 = _tool_results(events1)[0]
    assert result1.ok
    assert result1.result == "ENT_5831"

    # Turn 2: the model sends the alias-keyed argument (as its schema
    # advertises) with a WRONG raw id — must be rejected, not silently run.
    messages.append({"role": "user", "content": [{"text": "get details"}]})
    model2 = FakeModelClient(
        [tool_call("get_entity_detail_alias", {"entityId": "ENT_6236"}), reply("ack")]
    )
    events2 = await _run(model2, messages)
    result2 = _tool_results(events2)[0]
    assert not result2.ok, "wrong raw id on an aliased field must not be silently executed"
    assert received_entity_ids == [], "tool body must never run on a rejected call"
    assert result2.error is not None
    assert "ENT_6236" not in result2.error
    assert "ENT_5831" not in result2.error

    # Turn 3: same tool via $ref:entity_id on the alias-keyed field — the
    # token must actually be substituted, not passed through verbatim.
    messages.append({"role": "user", "content": [{"text": "try again with ref"}]})
    model3 = FakeModelClient(
        [tool_call("get_entity_detail_alias", {"entityId": "$ref:entity_id"}), reply("done")]
    )
    events3 = await _run(model3, messages)
    result3 = _tool_results(events3)[0]
    assert result3.ok, result3.error
    assert received_entity_ids == ["ENT_5831"], (
        f"expected $ref substitution to resolve entityId, got {received_entity_ids!r} "
        "(the literal '$ref:entity_id' token reaching the tool body means the "
        "alias/field-name key mismatch is still unfixed)"
    )
    assert result3.result == "detail-for-ENT_5831"

    audits = [e for e in events3 if isinstance(e, AuditEvent)]
    assert audits, "substitution must be recorded as an auditable event"
    assert audits[0].code == "reuse_substitution"
