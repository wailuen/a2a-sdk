"""RT-007 regression (redteam finding on reuse.py, medium severity): a tool
declaring MORE than one ``ReuseKind`` field must not lose one field's
bounded-recovery budget (RT-A-008/RT-C-001) to a sibling field's rejection
in the same call.

Before this fix, a field that earned a forced passthrough popped its own
``reject_counts`` entry immediately (spending its budget) and ``continue``d
to the next field in the same ``fields.items()`` iteration; if that LATER
field then rejected the call outright, ``resolve_reuse_fields`` returned
``(arguments, [], reject_reason)`` — discarding the earlier field's earned
substitution while its budget was already gone. The next identical call
started that field's counter back at zero, so its bounded recovery could
never complete for as long as the sibling field kept rejecting — the model
loops to ``max_turns``, which is exactly what RT-A-008 exists to prevent.

``resolve_reuse_fields`` now defers every ``reject_counts`` mutation for a
field that "succeeds" (a resolved ``$ref``, a matching raw value, or a
forced passthrough) until every field in the call is confirmed not to
trigger a hard rejection — committed only on the success return path.
"""

from __future__ import annotations

from typing import Any

import functools

from agent_sdk.agent.reuse import (
    MAX_CONSECUTIVE_REUSE_REJECTIONS,
    ReuseSubstitution,
    resolve_reuse_fields,
)

resolve_reuse_fields = functools.partial(
    resolve_reuse_fields, max_consecutive_rejections=MAX_CONSECUTIVE_REUSE_REJECTIONS
)

_FIELDS = {"a": "kind_a", "b": "kind_b"}
_INDEX: dict[str, list[tuple[str | None, Any]]] = {
    "kind_a": [(None, "A_1")],
    "kind_b": [(None, "B_1")],
}


def test_earlier_field_forced_passthrough_survives_later_field_rejection():
    reject_counts: dict[tuple[str, str, str], int] = {}

    # Drive field 'a' to its bounded-recovery threshold with a STUCK wrong
    # value while 'b' is correct, so every rejection in this loop is due to
    # 'a' alone.
    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS):
        _e, _s, error = resolve_reuse_fields(
            "two_field_tool", {"a": "A_WRONG", "b": "B_1"}, _FIELDS, _INDEX,
            reject_counts=reject_counts,
        )
        assert error is not None

    a_key = ("two_field_tool", "a", repr("A_WRONG"))
    assert reject_counts.get(a_key) == MAX_CONSECUTIVE_REUSE_REJECTIONS

    # The NEXT call: 'a' has now reached its threshold and would earn a
    # forced passthrough, but 'b' is ALSO wrong this time and rejects the
    # whole call outright, iterated after 'a' in dict order.
    _e, _s, error = resolve_reuse_fields(
        "two_field_tool", {"a": "A_WRONG", "b": "B_WRONG"}, _FIELDS, _INDEX,
        reject_counts=reject_counts,
    )
    assert error is not None, "the call must still fail overall, due to 'b'"

    # RT-007: 'a's budget must NOT have been spent by the aborted call — it
    # never actually proceeded, since 'b' blocked it.
    assert reject_counts.get(a_key) == MAX_CONSECUTIVE_REUSE_REJECTIONS, (
        "field 'a's forced-passthrough budget must survive a later field's "
        "hard rejection in the same call, not be silently spent"
    )

    # Confirm the budget was truly preserved: the NEXT call, with 'b'
    # correct again, must earn 'a' its forced passthrough immediately —
    # not require MAX_CONSECUTIVE_REUSE_REJECTIONS more rejections first.
    effective, substitutions, error = resolve_reuse_fields(
        "two_field_tool", {"a": "A_WRONG", "b": "B_1"}, _FIELDS, _INDEX,
        reject_counts=reject_counts,
    )
    assert error is None, (
        f"'a' must recover on this call — its budget must have carried over "
        f"from before the aborted call: {error!r}"
    )
    assert effective == {"a": "A_WRONG", "b": "B_1"}
    assert substitutions == [
        ReuseSubstitution(field_name="a", kind="kind_a", via_forced_passthrough=True)
    ]
    assert reject_counts.get(a_key) is None, "the spent budget clears once actually used"


def test_earlier_field_success_reset_survives_later_field_rejection():
    """The same deferred-commit discipline applies to an ordinary success
    reset, not only a forced passthrough: 'a' matches correctly, but 'b'
    then rejects the whole call — 'a's prior rejection history (if any)
    must be UNCHANGED by this aborted call, not cleared as though the call
    had actually gone through."""
    reject_counts: dict[tuple[str, str, str], int] = {}

    # Establish a prior (not-yet-exhausted) rejection count on 'a' via a
    # DIFFERENT wrong value than the one used below.
    _e, _s, error = resolve_reuse_fields(
        "two_field_tool", {"a": "A_STALE_WRONG", "b": "B_1"}, _FIELDS, _INDEX,
        reject_counts=reject_counts,
    )
    assert error is not None
    stale_key = ("two_field_tool", "a", repr("A_STALE_WRONG"))
    assert reject_counts.get(stale_key) == 1

    # A call where 'a' is CORRECT (would reset stale counts for 'a' on
    # success) but 'b' rejects — the call fails overall.
    _e, _s, error = resolve_reuse_fields(
        "two_field_tool", {"a": "A_1", "b": "B_WRONG"}, _FIELDS, _INDEX,
        reject_counts=reject_counts,
    )
    assert error is not None

    # RT-007: since the call never actually succeeded, 'a's stale count
    # must not have been reset either.
    assert reject_counts.get(stale_key) == 1, (
        "an aborted call must not reset a field's rejection history as "
        "though it had gone through"
    )
