"""RT-020 regression: resolve_reuse_fields must coerce a raw argument through
the field's declared type before the match check, so a value pydantic's own
``model_validate`` would treat as identical (e.g. the string ``"5831"``
against an ``int``-typed field resolved to ``5831``) is not rejected here as
a type mismatch before the tool is ever reached.

``resolve_reuse_fields`` runs against the model's raw, un-validated tool
arguments — before ``ToolEntry.invoke``'s ``input_model.model_validate`` ever
sees them — while the match check (``_raw_matches_resolved``) requires exact
type identity. Without coercion, a correct value supplied in a merely
coercible form (a JSON string where the field is typed ``int``) is rejected
as a mismatch, the model burns turns re-resolving, and after
``MAX_CONSECUTIVE_REUSE_REJECTIONS`` such rejections RT-A-008's forced
passthrough executes it anyway while recording a misleading
``reuse_forced_passthrough`` audit for what was the right value all along.

The RT-014 bool/int type-boundary guard must still hold after coercion is
introduced: ``True`` must not match a resolved ``1`` (or vice versa) even
though pydantic's own lax ``int``/``bool`` validators would happily coerce
one into the other.
"""

from __future__ import annotations

import decimal
import uuid
from datetime import datetime
from enum import Enum

from agent_sdk.agent.reuse import resolve_reuse_fields


def test_coercible_string_matches_int_resolution_when_field_type_given():
    index = {"entity_id": [(None, 5831)]}
    fields = {"entity_id": "entity_id"}
    field_types = {"entity_id": int}

    effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "5831"}, fields, index,
        field_types=field_types,
    )

    assert error is None, f"pydantic-coercible string must match the resolved int: {error!r}"
    assert effective == {"entity_id": "5831"}, "raw argument itself must be untouched"
    assert substitutions == []


def test_coercible_string_still_rejected_when_no_field_types_given():
    index = {"entity_id": [(None, 5831)]}
    fields = {"entity_id": "entity_id"}

    _effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "5831"}, fields, index,
    )

    assert error is not None, "callers that predate field_types keep the old strict behavior"
    assert substitutions == []


def test_non_coercible_string_still_rejected_with_field_types():
    index = {"entity_id": [(None, 5831)]}
    fields = {"entity_id": "entity_id"}
    field_types = {"entity_id": int}

    _effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "not-a-number"}, fields, index,
        field_types=field_types,
    )

    assert error is not None


def test_bool_argument_still_rejected_against_int_resolution_with_field_types():
    index = {"n": [(None, 1)]}
    fields = {"n": "n"}
    field_types = {"n": int}

    _effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"n": True}, fields, index, field_types=field_types,
    )

    assert error is not None, "True must not match a resolved int of 1 even with coercion on"
    assert substitutions == []


def test_int_argument_still_rejected_against_bool_resolution_with_field_types():
    index = {"flag": [(None, True)]}
    fields = {"flag": "flag"}
    field_types = {"flag": bool}

    _effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"flag": 1}, fields, index, field_types=field_types,
    )

    assert error is not None, "1 must not match a resolved bool of True even with coercion on"
    assert substitutions == []


def test_matching_type_and_value_still_passes_with_field_types():
    index = {"n": [(None, 1)]}
    fields = {"n": "n"}
    field_types = {"n": int}

    effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"n": 1}, fields, index, field_types=field_types,
    )

    assert error is None
    assert effective == {"n": 1}
    assert substitutions == []


def test_coercible_string_matches_float_resolution():
    index = {"amount": [(None, 12.5)]}
    fields = {"amount": "amount"}
    field_types = {"amount": float}

    effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"amount": "12.5"}, fields, index, field_types=field_types,
    )

    assert error is None
    assert effective == {"amount": "12.5"}
    assert substitutions == []


# ── RT-002: non-JSON-native ReuseKind field types (Enum/UUID/Decimal/
# datetime) must not reject the CORRECT resolved value.
#
# ``agent/loop.py``'s ``jsonable_reuse_value`` normalizes a Reusable.value
# through ``to_jsonable_python`` before storing it in ``resolved_index`` — a
# str-Enum member becomes its bare string value, a UUID/Decimal/datetime
# become their canonical string form. ``_coerce_raw_for_match`` coerces the
# model's raw argument through the field's DECLARED type instead (e.g. back
# into an Enum member or a UUID object), so without normalizing that coerced
# value the SAME way, the two sides of the equality never compared equal —
# rejecting the exact value the field was already correctly resolved to.


class _Ent(str, Enum):
    A = "ENT_1"
    B = "ENT_2"


def test_str_enum_field_correct_raw_value_matches_jsonsafed_resolution():
    # The index holds the JSON-safed form (a bare str), exactly as
    # jsonable_reuse_value stores a Reusable(value=_Ent.A, ...) resolution.
    index = {"entity_id": [(None, "ENT_1")]}
    fields = {"entity_id": "entity_id"}
    field_types = {"entity_id": _Ent}

    effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_1"}, fields, index,
        field_types=field_types,
    )

    assert error is None, f"correct raw value on a str-Enum field must match: {error!r}"
    assert effective == {"entity_id": "ENT_1"}
    assert substitutions == []


def test_str_enum_field_wrong_raw_value_still_rejected():
    index = {"entity_id": [(None, "ENT_1")]}
    fields = {"entity_id": "entity_id"}
    field_types = {"entity_id": _Ent}

    _effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_2"}, fields, index,
        field_types=field_types,
    )

    assert error is not None, "a genuinely wrong Enum value must still be rejected"
    assert substitutions == []


def test_uuid_field_correct_raw_value_matches_jsonsafed_resolution():
    entity_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    index = {"entity_id": [(None, str(entity_uuid))]}
    fields = {"entity_id": "entity_id"}
    field_types = {"entity_id": uuid.UUID}

    effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": str(entity_uuid)}, fields, index,
        field_types=field_types,
    )

    assert error is None, f"correct raw value on a UUID field must match: {error!r}"
    assert effective == {"entity_id": str(entity_uuid)}
    assert substitutions == []


def test_uuid_field_wrong_raw_value_still_rejected():
    entity_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")
    other_uuid = uuid.UUID("87654321-4321-8765-4321-876543218765")
    index = {"entity_id": [(None, str(entity_uuid))]}
    fields = {"entity_id": "entity_id"}
    field_types = {"entity_id": uuid.UUID}

    _effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": str(other_uuid)}, fields, index,
        field_types=field_types,
    )

    assert error is not None, "a genuinely wrong UUID must still be rejected"
    assert substitutions == []


def test_decimal_field_correct_raw_value_matches_jsonsafed_resolution():
    index = {"amount": [(None, "12.50")]}
    fields = {"amount": "amount"}
    field_types = {"amount": decimal.Decimal}

    effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"amount": "12.50"}, fields, index, field_types=field_types,
    )

    assert error is None, f"correct raw value on a Decimal field must match: {error!r}"
    assert effective == {"amount": "12.50"}
    assert substitutions == []


def test_datetime_field_correct_raw_value_matches_jsonsafed_resolution():
    resolved_at = datetime(2026, 9, 2, 12, 0, 0)
    index = {"resolved_at": [(None, resolved_at.isoformat())]}
    fields = {"resolved_at": "resolved_at"}
    field_types = {"resolved_at": datetime}

    # The model may echo back the exact string it saw as the tool's plain
    # str(datetime) result (space-separated), not necessarily isoformat()'s
    # 'T'-separated string — both must coerce+normalize to the same value.
    effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"resolved_at": str(resolved_at)}, fields, index,
        field_types=field_types,
    )

    assert error is None, f"correct raw value on a datetime field must match: {error!r}"
    assert effective == {"resolved_at": str(resolved_at)}
    assert substitutions == []


def test_datetime_field_wrong_raw_value_still_rejected():
    resolved_at = datetime(2026, 9, 2, 12, 0, 0)
    other = datetime(2026, 9, 3, 8, 30, 0)
    index = {"resolved_at": [(None, resolved_at.isoformat())]}
    fields = {"resolved_at": "resolved_at"}
    field_types = {"resolved_at": datetime}

    _effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"resolved_at": str(other)}, fields, index, field_types=field_types,
    )

    assert error is not None, "a genuinely wrong datetime must still be rejected"
    assert substitutions == []
