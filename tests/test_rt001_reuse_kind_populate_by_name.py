"""RT-001 regression (GH-148 follow-up #2): a ``ReuseKind`` field on a model
that declares ``populate_by_name=True`` alongside its alias must be
substituted/validated identically whether a tool call is keyed by the wire
alias or the bare python field name — pydantic's ``model_validate`` accepts
either on such a model, so the GH-148 gate must intercept either.

Before this fix every ``ReuseKind`` map (``reuse_fields``/``reuse_strict``/
``reuse_raw_override``/``reuse_field_types``) was keyed by the alias alone
(``_wire_field_name``), so a call keyed by the python field name silently
skipped BOTH substitution/mismatch-rejection (``agent/loop.py``) and the
``invoke_any`` RT-A-009 rejection (``agent/registry.py``) while
``model_validate`` still accepted it without complaint — the exact silent
wrong-but-successful GH-148 substitution bug, reopened on precisely the
model shape (an alias declared together with ``populate_by_name=True`` — or
an ``alias_generator`` plus that same opt-in) most likely to want
``ReuseKind`` in the first place (A2UI-facing tools commonly use camelCase
wire fields). ``_wire_field_name``'s own docstring used to assert the
opposite of the observed behaviour ("model_validate rejects the plain field
name outright, even with populate_by_name=True") — verified false live.

A model with an alias but WITHOUT ``populate_by_name=True`` (every existing
``ReuseKind`` model before this fix, see ``test_rt019_reuse_kind_field_alias
.py``) is unaffected: ``model_validate`` only ever accepts the alias there,
so keying by it alone remains correct and complete — this file exists
specifically to cover the case those tests do not.
"""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolEntry, ToolRegistry, ToolSet
from agent_sdk.agent.reuse import (
    Reusable,
    ReuseKind,
    reuse_fields_for_model,
    reuse_raw_override_for_model,
    reuse_strict_for_model,
)
from agent_sdk.models.errors import AgentError, ErrorCategory
from agent_sdk.testing import FakeModelClient, reply, tool_call

pytestmark = pytest.mark.asyncio


class EntityDetailPopulateByNameIn(BaseModel):
    """A ReuseKind field with BOTH a declared alias (via alias_generator)
    AND populate_by_name=True — pydantic then accepts a call keyed by
    EITHER 'entityId' or 'entity_id'."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)

    entity_id: Annotated[str, ReuseKind("entity_id")]


# ── unit: the reuse maps carry both keys ────────────────────────────────────


async def test_reuse_maps_keyed_by_both_alias_and_field_name_when_populate_by_name():
    fields = reuse_fields_for_model(EntityDetailPopulateByNameIn)
    assert fields == {"entityId": "entity_id", "entity_id": "entity_id"}

    strict = reuse_strict_for_model(EntityDetailPopulateByNameIn)
    assert strict == {"entityId": True, "entity_id": True}

    raw_override = reuse_raw_override_for_model(EntityDetailPopulateByNameIn)
    assert raw_override == {"entityId": False, "entity_id": False}


async def test_model_actually_accepts_both_keys_confirming_the_premise():
    """Sanity check on the premise the rest of this file relies on: pydantic
    really does accept either key on this model."""
    a = EntityDetailPopulateByNameIn.model_validate({"entityId": "ENT_1"})
    b = EntityDetailPopulateByNameIn.model_validate({"entity_id": "ENT_1"})
    assert a.entity_id == b.entity_id == "ENT_1"


# ── end-to-end: run_loop treats alias-keyed and field-name-keyed calls
# identically ──────────────────────────────────────────────────────────────

pbn_tools = ToolSet()
pbn_received: list[str] = []

_ENTITY_IDS = {"PT IMC Pelita Logistik": "ENT_5831"}


class _ResolveIn(BaseModel):
    name: str


@pbn_tools.tool(tier=1)
async def pbn_resolve_entity(inp: _ResolveIn) -> Any:
    """Resolve a company name to its canonical entity id."""
    return Reusable(value=_ENTITY_IDS[inp.name], kind="entity_id", label=inp.name)


@pbn_tools.tool(tier=1)
async def pbn_get_entity_detail(inp: EntityDetailPopulateByNameIn) -> str:
    """Fetch details for a resolved entity id (populate_by_name field)."""
    pbn_received.append(inp.entity_id)
    return f"detail-for-{inp.entity_id}"


PBN_REGISTRY = ToolRegistry([pbn_tools], {})


async def _run(model: FakeModelClient, messages: list[dict[str, Any]]) -> list[Any]:
    events: list[Any] = []
    async for ev in run_loop(
        model=model, registry=PBN_REGISTRY, adapters={}, system="test", messages=messages,
    ):
        events.append(ev)
    return events


def _tool_results(events: list[Any]) -> list[ToolResultEvent]:
    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert results, "expected at least one ToolResultEvent"
    return results


@pytest.mark.parametrize("call_key", ["entityId", "entity_id"])
async def test_wrong_raw_id_rejected_identically_whichever_key_the_model_uses(call_key):
    """The GH-148 mismatch rejection must fire for a wrong raw id regardless
    of whether the model keys its call by the wire alias or the bare python
    field name — this is the exact silent-passthrough gap RT-001 closes."""
    pbn_received.clear()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve PT IMC Pelita Logistik"}]}
    ]
    model1 = FakeModelClient(
        [tool_call("pbn_resolve_entity", {"name": "PT IMC Pelita Logistik"}), reply("resolved")]
    )
    await _run(model1, messages)

    messages.append({"role": "user", "content": [{"text": "get details"}]})
    model2 = FakeModelClient(
        [tool_call("pbn_get_entity_detail", {call_key: "ENT_6236"}), reply("ack")]
    )
    events2 = await _run(model2, messages)
    result2 = _tool_results(events2)[0]
    assert not result2.ok, (
        f"a wrong raw id keyed by {call_key!r} must be rejected, not silently executed "
        "(GH-148 substitution bug reopened via the field-name key)"
    )
    assert pbn_received == [], "tool body must never run on a rejected call"


@pytest.mark.parametrize("call_key", ["entityId", "entity_id"])
async def test_ref_token_substituted_identically_whichever_key_the_model_uses(call_key):
    """$ref:entity_id must actually resolve — not reach the tool body
    verbatim as a literal string — regardless of which key the model used."""
    pbn_received.clear()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve PT IMC Pelita Logistik"}]}
    ]
    model1 = FakeModelClient(
        [tool_call("pbn_resolve_entity", {"name": "PT IMC Pelita Logistik"}), reply("resolved")]
    )
    await _run(model1, messages)

    messages.append({"role": "user", "content": [{"text": "try again with ref"}]})
    model2 = FakeModelClient(
        [tool_call("pbn_get_entity_detail", {call_key: "$ref:entity_id"}), reply("done")]
    )
    events2 = await _run(model2, messages)
    result2 = _tool_results(events2)[0]
    assert result2.ok, result2.error
    assert pbn_received == ["ENT_5831"], (
        f"expected $ref substitution to resolve when keyed by {call_key!r}, got "
        f"{pbn_received!r} (the literal '$ref:entity_id' token reaching the tool "
        "body means the field-name-keyed path is still unfixed)"
    )


# ── end-to-end: invoke_any (RT-A-009 parity, no conversation transcript) ───


def _entry() -> ToolEntry:
    decl = next(d for d in pbn_tools.decls if d.name == "pbn_get_entity_detail")
    return ToolEntry(decl=decl)


@pytest.mark.parametrize("call_key", ["entityId", "entity_id"])
async def test_invoke_any_rejects_ref_token_whichever_key_is_used(call_key):
    """invoke_any's RT-A-009 rejection (no conversation transcript to
    resolve a $ref against — MCP tools/call, admin try-tool, the
    commitments executor) must fire whether the caller keys its argument by
    the alias or the bare python field name."""
    pbn_received.clear()
    entry = _entry()

    with pytest.raises(AgentError) as exc_info:
        await entry.invoke_any({call_key: "$ref:entity_id"}, {})

    assert exc_info.value.category == ErrorCategory.VALIDATION
    assert pbn_received == [], (
        f"the tool body must never run for a $ref token keyed by {call_key!r}"
    )


@pytest.mark.parametrize("call_key", ["entityId", "entity_id"])
async def test_invoke_any_rejects_raw_override_token_whichever_key_is_used(call_key):
    pbn_received.clear()
    entry = _entry()

    with pytest.raises(AgentError) as exc_info:
        await entry.invoke_any({call_key: "$raw:ENT_9999"}, {})

    assert exc_info.value.category == ErrorCategory.VALIDATION
    assert pbn_received == []
