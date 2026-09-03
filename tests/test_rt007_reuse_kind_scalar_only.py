"""RT-007 regression: ``ReuseKind`` only supports a top-level scalar field.

Before this fix ``reuse_fields_for_model`` silently accepted two shapes it
cannot actually enforce:

- a container field (``Annotated[list[str], ReuseKind("entity_id")]``) —
  ``resolve_reuse_fields`` compares the whole list against each scalar
  resolution with ``==``, so a correct list value (e.g. ``["ENT_1"]`` when
  ``ENT_1`` is the resolved id) was permanently rejected as a mismatch.
- a ``ReuseKind`` annotation on a field of a *nested* model — silently
  ignored, since ``reuse_fields_for_model`` only inspects top-level hints, so
  any ``$ref:`` token there reached the tool verbatim with no substitution
  and no validation.

Both shapes must now fail loudly at ``@tools.tool`` registration time
instead of misbehaving at call time.
"""

from typing import Annotated

import pytest
from pydantic import BaseModel

from agent_sdk.agent.reuse import ReuseKind, reuse_fields_for_model


def test_top_level_scalar_field_still_works():
    class ScalarIn(BaseModel):
        entity_id: Annotated[str, ReuseKind("entity_id")]
        note: str

    assert reuse_fields_for_model(ScalarIn) == {"entity_id": "entity_id"}


def test_optional_scalar_field_still_works():
    class OptionalScalarIn(BaseModel):
        entity_id: Annotated[str | None, ReuseKind("entity_id")] = None

    assert reuse_fields_for_model(OptionalScalarIn) == {"entity_id": "entity_id"}


def test_plain_nested_model_without_reuse_kind_is_unaffected():
    class Inner(BaseModel):
        name: str

    class OuterIn(BaseModel):
        inner: Inner
        entity_id: Annotated[str, ReuseKind("entity_id")]

    assert reuse_fields_for_model(OuterIn) == {"entity_id": "entity_id"}


def test_list_field_annotated_reuse_kind_raises_at_registration():
    class ListIn(BaseModel):
        entity_ids: Annotated[list[str], ReuseKind("entity_id")]

    with pytest.raises(TypeError, match="ReuseKind"):
        reuse_fields_for_model(ListIn)


def test_tuple_field_annotated_reuse_kind_raises_at_registration():
    class TupleIn(BaseModel):
        entity_ids: Annotated[tuple[str, ...], ReuseKind("entity_id")]

    with pytest.raises(TypeError, match="ReuseKind"):
        reuse_fields_for_model(TupleIn)


def test_reuse_kind_on_nested_model_field_raises_at_registration():
    class Inner(BaseModel):
        entity_id: Annotated[str, ReuseKind("entity_id")]

    class OuterIn(BaseModel):
        inner: Inner

    with pytest.raises(TypeError, match="ReuseKind"):
        reuse_fields_for_model(OuterIn)


def test_reuse_kind_on_optional_nested_model_field_raises_at_registration():
    class Inner(BaseModel):
        entity_id: Annotated[str, ReuseKind("entity_id")]

    class OuterIn(BaseModel):
        inner: Inner | None = None

    with pytest.raises(TypeError, match="ReuseKind"):
        reuse_fields_for_model(OuterIn)


def test_reuse_kind_on_model_nested_inside_a_list_raises_at_registration():
    class Inner(BaseModel):
        entity_id: Annotated[str, ReuseKind("entity_id")]

    class OuterIn(BaseModel):
        items: list[Inner]

    with pytest.raises(TypeError, match="ReuseKind"):
        reuse_fields_for_model(OuterIn)


def test_top_level_field_annotated_reuse_kind_with_nested_model_type_raises():
    class Inner(BaseModel):
        name: str

    class OuterIn(BaseModel):
        inner: Annotated[Inner, ReuseKind("entity_id")]

    with pytest.raises(TypeError, match="ReuseKind"):
        reuse_fields_for_model(OuterIn)
