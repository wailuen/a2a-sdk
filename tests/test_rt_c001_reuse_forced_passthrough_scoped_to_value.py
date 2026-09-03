"""RT-C-001 regression (redteam finding RT-002 on reuse.py:686): the RT-A-008
bounded-recovery escape hatch must be scoped to a stuck retry of the SAME
wrong value, not merely the same ``(tool_name, field_name)`` pair.

Before this fix, ``reject_counts`` was keyed only on ``(tool_name,
field_name)``, so three DIFFERENT wrong-but-plausible raw values in a row on
the same field also tripped the forced passthrough — live-verified: with
``index = {"entity_id": [("Acme Corp", "ENT_1")]}``, ``resolve_reuse_fields``
rejects ``WRONG_A`` and ``WRONG_B``, then executes ``WRONG_C`` with
``via_forced_passthrough=True``. This reopens the exact GH-148 failure mode
(the model substitutes a different-but-real, wrong-but-plausible id) the
mismatch check exists to catch, and contradicts both this module's own
docstring and CHANGELOG.md, which claim the budget guards a stuck retry loop
on the SAME wrong value.
"""

from __future__ import annotations

import functools
from typing import Any

import pytest

from agent_sdk.agent.reuse import (
    MAX_CONSECUTIVE_REUSE_REJECTIONS,
    ReuseSubstitution,
    resolve_reuse_fields,
)

pytestmark = pytest.mark.asyncio

# RT-021: resolve_reuse_fields's own max_consecutive_rejections default is
# now fail-closed (0) — these unit-level tests exercise the OPTED-IN
# bounded-recovery shape directly, so they supply the module's suggested
# value as their own default; test_max_consecutive_rejections_zero_disables_
# escape_hatch below overrides it explicitly (a call-time kwarg wins over a
# functools.partial's preset one).
resolve_reuse_fields = functools.partial(
    resolve_reuse_fields, max_consecutive_rejections=MAX_CONSECUTIVE_REUSE_REJECTIONS
)


async def test_distinct_wrong_values_never_trigger_forced_passthrough():
    """The exact live-verified RT-002 failure shape: three DIFFERENT
    hallucinated ids in a row must all be rejected — the budget must not be
    shared across distinct raw values on the same (tool, field)."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {"entity_id": [("Acme Corp", "ENT_1")]}
    reject_counts: dict[tuple[str, str, str], int] = {}

    for wrong_value in ["WRONG_A", "WRONG_B", "WRONG_C"]:
        effective, substitutions, error = resolve_reuse_fields(
            "get_entity_detail",
            {"entity_id": wrong_value},
            fields,
            index,
            reject_counts=reject_counts,
        )
        assert error is not None, (
            f"{wrong_value!r} must be rejected — a sequence of distinct "
            "hallucinated ids must never earn a forced passthrough"
        )
        assert substitutions == []
        assert effective == {"entity_id": wrong_value}


async def test_same_wrong_value_repeated_still_recovers():
    """The mirror image: a genuinely stuck retry of the SAME wrong value must
    still recover after MAX_CONSECUTIVE_REUSE_REJECTIONS, exactly as
    RT-A-008 originally intended — this must keep passing after the fix."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {"entity_id": [("Acme Corp", "ENT_1")]}
    reject_counts: dict[tuple[str, str, str], int] = {}

    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS):
        _e, _s, error = resolve_reuse_fields(
            "get_entity_detail", {"entity_id": "ENT_STUCK"}, fields, index,
            reject_counts=reject_counts,
        )
        assert error is not None

    effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_STUCK"}, fields, index,
        reject_counts=reject_counts,
    )
    assert error is None
    assert effective == {"entity_id": "ENT_STUCK"}
    assert substitutions == [
        ReuseSubstitution(field_name="entity_id", kind="entity_id", via_forced_passthrough=True)
    ]


async def test_interleaved_distinct_values_each_track_independently():
    """Alternating between two distinct wrong values must not let either
    borrow budget from the other — each raw value gets its own consecutive
    count. Bounded to exactly MAX_CONSECUTIVE_REUSE_REJECTIONS rounds so
    neither value's OWN per-value budget is exhausted either — this isolates
    cross-value leakage from each value's own legitimate recovery."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {"entity_id": [("Acme Corp", "ENT_1")]}
    reject_counts: dict[tuple[str, str, str], int] = {}

    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS):
        _e, _s, error_a = resolve_reuse_fields(
            "get_entity_detail", {"entity_id": "ENT_ALPHA"}, fields, index,
            reject_counts=reject_counts,
        )
        _e, _s, error_b = resolve_reuse_fields(
            "get_entity_detail", {"entity_id": "ENT_BETA"}, fields, index,
            reject_counts=reject_counts,
        )
        assert error_a is not None
        assert error_b is not None

    # Each value has now independently reached the bound. Confirm ALPHA
    # recovers on its next attempt while BETA (untouched since) still needs
    # its own next attempt to do the same — proving the two counts never
    # shared or borrowed from one another.
    _e, _s, error_a = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_ALPHA"}, fields, index,
        reject_counts=reject_counts,
    )
    assert error_a is None, "ALPHA must recover after its own bound is reached"
    _e, _s, error_b = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_BETA"}, fields, index,
        reject_counts=reject_counts,
    )
    assert error_b is None, "BETA must recover after its own bound is reached"


async def test_success_on_one_value_clears_stale_counts_for_other_values():
    """A successful $ref resolution (or matching raw value) resets the
    field's tracked rejection state entirely, including budget spent on a
    DIFFERENT wrong value earlier in the same conversation."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {"entity_id": [("Acme Corp", "ENT_1")]}
    reject_counts: dict[tuple[str, str, str], int] = {}

    _e, _s, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_WRONG"}, fields, index,
        reject_counts=reject_counts,
    )
    assert error is not None
    assert reject_counts

    _e, _s, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "$ref:entity_id"}, fields, index,
        reject_counts=reject_counts,
    )
    assert error is None
    assert reject_counts == {}, "a successful resolution must clear stale counts for this field"


async def test_max_consecutive_rejections_zero_disables_escape_hatch():
    """LoopPolicies knob: an operator setting the limit to 0 for a
    high-stakes field must reject a mismatched raw value forever, even on
    repeated attempts of the identical value."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {"entity_id": [("Acme Corp", "ENT_1")]}
    reject_counts: dict[tuple[str, str, str], int] = {}

    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS + 5):
        _e, substitutions, error = resolve_reuse_fields(
            "get_entity_detail", {"entity_id": "ENT_STUCK"}, fields, index,
            reject_counts=reject_counts,
            max_consecutive_rejections=0,
        )
        assert error is not None, "limit=0 must reject forever, never a forced passthrough"
        assert substitutions == []
