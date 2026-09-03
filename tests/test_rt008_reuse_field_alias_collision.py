"""RT-008 regression (redteam finding on reuse.py, medium severity): the
RT-001 dual-keying (wire name + bare python field name, both mapping to the
same field's declared kind/strict/allow_raw_override/type) writes into one
flat dict with no collision check.

A model declaring field ``a`` with ``alias="b"`` alongside a REAL field
``b`` produces two writes to key ``"b"`` — one field's ``ReuseKind`` policy
silently overwrote the other's before this fix, applying the WRONG policy
to a field rather than none (e.g. a ``strict=True`` field silently
inheriting a sibling's ``strict=False``). ``reuse_fields_for_model`` and its
three sibling map builders now raise ``TypeError`` at registration time
instead.
"""

from __future__ import annotations

from typing import Annotated

import pytest
from pydantic import BaseModel, Field

from agent_sdk.agent.reuse import (
    ReuseKind,
    reuse_field_types_for_model,
    reuse_fields_for_model,
    reuse_raw_override_for_model,
    reuse_strict_for_model,
)


class _AliasCollidesWithFieldName(BaseModel):
    a: Annotated[str, ReuseKind("kind_a", strict=True)] = Field(alias="b")
    b: Annotated[str, ReuseKind("kind_b", strict=False)]


def test_reuse_fields_for_model_raises_on_alias_field_name_collision():
    with pytest.raises(TypeError, match="both resolve to the wire key"):
        reuse_fields_for_model(_AliasCollidesWithFieldName)


def test_reuse_strict_for_model_raises_on_alias_field_name_collision():
    with pytest.raises(TypeError, match="both resolve to the wire key"):
        reuse_strict_for_model(_AliasCollidesWithFieldName)


def test_reuse_raw_override_for_model_raises_on_alias_field_name_collision():
    with pytest.raises(TypeError, match="both resolve to the wire key"):
        reuse_raw_override_for_model(_AliasCollidesWithFieldName)


def test_reuse_field_types_for_model_raises_on_alias_field_name_collision():
    with pytest.raises(TypeError, match="both resolve to the wire key"):
        reuse_field_types_for_model(_AliasCollidesWithFieldName)


def test_registering_the_tool_itself_raises_on_alias_field_name_collision():
    from agent_sdk.agent.registry import ToolSet

    tools = ToolSet()

    with pytest.raises(TypeError, match="both resolve to the wire key"):

        @tools.tool(tier=1)
        async def colliding_tool(inp: _AliasCollidesWithFieldName) -> str:
            """A tool whose input model has a collision that must never
            register."""
            return inp.a


class _DistinctAliasesNoCollision(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")] = Field(alias="entityId")
    account_id: Annotated[str, ReuseKind("account_id")] = Field(alias="accountId")


def test_no_false_positive_when_aliases_are_distinct():
    """Two ReuseKind fields with genuinely distinct wire names must not
    collide — this is the ordinary, common shape and must keep working."""
    fields = reuse_fields_for_model(_DistinctAliasesNoCollision)
    assert fields == {"entityId": "entity_id", "accountId": "account_id"}
