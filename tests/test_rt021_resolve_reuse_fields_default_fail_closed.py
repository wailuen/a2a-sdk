"""RT-021 regression (redteam finding, medium severity): ``resolve_reuse_fields``'s
own ``max_consecutive_rejections`` default must be fail-closed (``0``), not
``MAX_CONSECUTIVE_REUSE_REJECTIONS``.

Before this fix, the signature default was ``MAX_CONSECUTIVE_REUSE_REJECTIONS``
(``2``) while every other part of this mechanism — ``LoopPolicies.
reuse_forced_passthrough_limit`` (``agent/loop.py``) and this module's own
docstrings (module docstring RT-005; the constant's own comment) — insists the
GH-148 substitution gate is a correctness gate that "must default fail-closed,
not fail-open." The module docstring explicitly advertises ``resolve_reuse_fields``
accepting ``max_consecutive_rejections`` directly "for a caller that wants the
budget somewhere other than ``LoopPolicies``" — such a caller that supplied
``reject_counts`` but omitted the kwarg (a reasonable reading of that
docstring) silently got bounded recovery ON by default, the exact fail-open
behavior the surrounding prose forbids. ``run_loop`` itself was never affected
(it always passes ``policies.reuse_forced_passthrough_limit`` explicitly), but
the function's OWN default contradicted its own documented contract.
"""

from __future__ import annotations

from typing import Any

from agent_sdk.agent.reuse import MAX_CONSECUTIVE_REUSE_REJECTIONS, resolve_reuse_fields


def test_default_rejects_forever_even_with_reject_counts_tracked():
    """A caller that tracks ``reject_counts`` but does not pass
    ``max_consecutive_rejections`` explicitly must still reject the same
    wrong value forever — the function's own default must be fail-closed,
    matching ``LoopPolicies.reuse_forced_passthrough_limit``'s default."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {"entity_id": [(None, "ENT_5831")]}
    reject_counts: dict[tuple[str, str, str], int] = {}

    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS + 3):
        effective, substitutions, error = resolve_reuse_fields(
            "get_entity_detail",
            {"entity_id": "ENT_6236"},
            fields,
            index,
            reject_counts=reject_counts,
        )
        assert error is not None, (
            "the fail-closed default must reject every attempt, never fail "
            "open into a forced passthrough"
        )
        assert substitutions == []
        assert effective == {"entity_id": "ENT_6236"}


def test_explicit_max_consecutive_rejections_still_opts_in_unit_level():
    """The suggested constant is still usable directly — a caller that wants
    the budget outside ``LoopPolicies`` must still be able to opt in by
    passing it explicitly."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {"entity_id": [(None, "ENT_5831")]}
    reject_counts: dict[tuple[str, str, str], int] = {}

    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS):
        _e, _s, error = resolve_reuse_fields(
            "get_entity_detail",
            {"entity_id": "ENT_6236"},
            fields,
            index,
            reject_counts=reject_counts,
            max_consecutive_rejections=MAX_CONSECUTIVE_REUSE_REJECTIONS,
        )
        assert error is not None

    effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail",
        {"entity_id": "ENT_6236"},
        fields,
        index,
        reject_counts=reject_counts,
        max_consecutive_rejections=MAX_CONSECUTIVE_REUSE_REJECTIONS,
    )
    assert error is None, "explicit opt-in must still recover after the bound"
    assert effective == {"entity_id": "ENT_6236"}
