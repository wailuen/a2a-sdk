"""RT-014 regression: resolve_reuse_fields' raw-value match must not let
Python's ``True == 1`` / ``False == 0`` equivalence satisfy a resolution of a
different type.

Before the fix, a boolean argument silently matched an integer-valued
resolution (and vice versa) because the raw-value check used bare ``==``.
Cosmetic today (resolved kinds are normally string ids) but the field is
typed ``Any`` and this check is the mechanism's only correctness gate.
"""

from __future__ import annotations

from agent_sdk.agent.reuse import resolve_reuse_fields


def test_bool_argument_does_not_match_int_resolution():
    index = {"n": [(None, 1)]}
    fields = {"n": "n"}

    _effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"n": True}, fields, index
    )

    assert error is not None, "True must not silently match a resolved int of 1"
    assert substitutions == []


def test_int_argument_does_not_match_bool_resolution():
    index = {"flag": [(None, True)]}
    fields = {"flag": "flag"}

    _effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"flag": 1}, fields, index
    )

    assert error is not None, "1 must not silently match a resolved bool of True"
    assert substitutions == []


def test_matching_type_and_value_still_passes():
    index = {"n": [(None, 1)]}
    fields = {"n": "n"}

    effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"n": 1}, fields, index
    )

    assert error is None
    assert effective == {"n": 1}
    assert substitutions == []
