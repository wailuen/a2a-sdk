"""RT-010: the ``$ref:<kind>`` affordance must be visible to the model in
the tool's JSON schema, not just discoverable via a ``__resolved__`` marker
after the fact (or, on AG-UI, never — RT-001).

``ToolDecl.reuse_fields`` (GH-148) was computed and stored but never fed
back into ``ToolEntry.input_schema()``, so a ``ReuseKind`` field's schema
looked like a plain string with no mention of the ``$ref:<kind>``/
``$ref:<kind>:<label>`` token. Fix: when a field is in ``decl.reuse_fields``,
``input_schema(include_reuse_hint=True)`` appends a generated sentence to
that field's ``description`` naming the kind and both token forms.

RT-005: the hint is a loop-only projection — ``include_reuse_hint`` defaults
to ``False`` and every call below that means to exercise the hint passes it
explicitly, mirroring the one real call site (``loop.py``'s ``tool_specs``).
MCP ``tools/list`` and the agent card's ``x-sdk.inputSchema`` call
``input_schema()`` with no argument and must never see this text — see
``tests/test_rt005_reuse_hint_surface_scope.py``.
"""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from pydantic import BaseModel, Field

from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolDecl, ToolEntry, ToolRegistry, ToolSet
from agent_sdk.agent.reuse import ReuseKind
from agent_sdk.testing import FakeModelClient, reply, tool_call

# ---------------------------------------------------------------------------
# Unit: ToolEntry.input_schema()
# ---------------------------------------------------------------------------


def _entry(model: type[BaseModel], reuse_fields: dict[str, str]) -> ToolEntry:
    async def _fn(inp: model) -> None:  # type: ignore[valid-type]
        """no-op"""

    decl = ToolDecl(
        fn=_fn,
        name="reuse_tool",
        description="no-op",
        tier=1,
        emits=None,
        sample=None,
        input_model=model,
        adapter_params={},
        reuse_fields=reuse_fields,
    )
    return ToolEntry(decl=decl)


def test_reuse_field_description_names_the_ref_token() -> None:
    class In(BaseModel):
        entity_id: Annotated[str, ReuseKind("entity_id")]

    schema = _entry(In, {"entity_id": "entity_id"}).input_schema(include_reuse_hint=True)
    description = schema["properties"]["entity_id"]["description"]
    assert "$ref:entity_id" in description
    assert "$ref:entity_id:" in description, "must also surface the disambiguating <label> form"


def test_reuse_field_hint_appends_to_existing_description() -> None:
    class In(BaseModel):
        entity_id: Annotated[
            str, ReuseKind("entity_id"), Field(description="The canonical entity id.")
        ]

    schema = _entry(In, {"entity_id": "entity_id"}).input_schema(include_reuse_hint=True)
    description = schema["properties"]["entity_id"]["description"]
    assert description.startswith("The canonical entity id.")
    assert "$ref:entity_id" in description


def test_non_reuse_field_unaffected() -> None:
    class In(BaseModel):
        entity_id: Annotated[str, ReuseKind("entity_id")]
        note: str

    schema = _entry(In, {"entity_id": "entity_id"}).input_schema(include_reuse_hint=True)
    assert "description" not in schema["properties"]["note"]


def test_multiple_reuse_fields_each_get_their_own_kind() -> None:
    class In(BaseModel):
        entity_id: Annotated[str, ReuseKind("entity_id")]
        account_id: Annotated[str, ReuseKind("account_id")]

    schema = _entry(
        In, {"entity_id": "entity_id", "account_id": "account_id"}
    ).input_schema(include_reuse_hint=True)
    assert "$ref:entity_id" in schema["properties"]["entity_id"]["description"]
    assert "$ref:account_id" in schema["properties"]["account_id"]["description"]
    assert "$ref:account_id" not in schema["properties"]["entity_id"]["description"]


def test_no_reuse_fields_schema_unchanged() -> None:
    class In(BaseModel):
        x: int

    schema = _entry(In, {}).input_schema()
    assert "description" not in schema["properties"]["x"]


def test_default_call_omits_hint_even_with_reuse_fields() -> None:
    """RT-005: ``include_reuse_hint`` defaults to ``False`` — every non-loop
    caller (routes/mcp.py, routes/agent_card.py, routes/admin.py) invokes
    ``input_schema()`` with no argument and must never see the ``$ref:``
    token, since only ``loop.py`` implements the substitution/validation
    gate the token advertises."""

    class In(BaseModel):
        entity_id: Annotated[str, ReuseKind("entity_id")]

    schema = _entry(In, {"entity_id": "entity_id"}).input_schema()
    assert "description" not in schema["properties"]["entity_id"]


# ---------------------------------------------------------------------------
# End-to-end: the hint reaches the model-visible tool spec (run_loop)
# ---------------------------------------------------------------------------


class _EntityDetailIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")]


@pytest.mark.asyncio
async def test_model_visible_tools_include_ref_hint() -> None:
    """The exact ``tools`` payload handed to the model (loop.py's
    ``tool_specs``, built from ``input_schema()``) must carry the hint —
    this is the surface RT-010 says never learns about ``$ref`` today."""
    tools = ToolSet()

    @tools.tool(tier=1)
    async def get_entity_detail(inp: _EntityDetailIn) -> str:
        """Fetch details for a resolved entity id."""
        return f"detail-for-{inp.entity_id}"

    registry = ToolRegistry([tools], {})
    model = FakeModelClient(
        [tool_call("get_entity_detail", {"entity_id": "ENT_1"}), reply("done")]
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]

    async for _ in run_loop(
        model=model, registry=registry, adapters={}, system="test", messages=messages
    ):
        pass

    sent_tools = model.calls[0]["tools"]
    spec = next(t for t in sent_tools if t["name"] == "get_entity_detail")
    hint = spec["input_schema"]["properties"]["entity_id"]["description"]
    assert "$ref:entity_id" in hint
