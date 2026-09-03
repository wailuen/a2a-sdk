"""RT-A-006 regression: a raw value matching a DIFFERENT, wrong-but-real
resolution of the same kind must not pass the ``ReuseKind`` mismatch check
silently.

Before this fix, ``resolve_reuse_fields`` compared a raw argument against the
UNION of every resolution of that kind, regardless of label — so once two
distinct entities had been resolved (e.g. ``entity_id: [("Acme Corp",
"ENT_1"), ("Beta Ltd", "ENT_2")]``), supplying ``"ENT_2"`` where Acme was
meant passed the check: ``"ENT_2"`` IS a real, previously-resolved value, just
for the wrong label. This is the same class of failure GH-148 describes (\"a
different-but-real, WRONG entity's ID\") — the gate only ever caught a value
that was never resolved at all.

Fix: once more than one resolution of a kind is on record, a bare raw value
can no longer be trusted via membership in that set alone — the call is
rejected as ambiguous, and the model must disambiguate via
``$ref:<kind>:<label>`` (or re-resolve). A single resolution of a kind is
unambiguous and raw-value matching against it is unchanged.

RT-D-001: the ambiguity rejection now names the kind's own on-record LABELS
in its text — the only way ``$ref:<kind>:<label>`` is actually constructible
on a transport (AG-UI) whose transcript never replays the original
``__resolved__`` marker back to the model. Only the resolved VALUES
(``ENT_1``/``ENT_2`` here) stay redacted (SI-2); the labels are
tool-author-supplied display names, not upstream payload.
"""

from __future__ import annotations

from agent_sdk.agent.reuse import resolve_reuse_fields


def test_raw_value_matching_a_different_labelled_resolution_is_rejected():
    """The exact RT-A-006 repro: two distinct resolutions on record, raw
    value equals the WRONG one (Beta's id, when Acme's was meant).

    RT-D-001: the rejection must name the on-record LABELS (so
    ``$ref:entity_id:<label>`` is actually constructible) while still never
    leaking a resolved VALUE."""
    index = {"entity_id": [("Acme Corp", "ENT_1"), ("Beta Ltd", "ENT_2")]}
    fields = {"entity_id": "entity_id"}

    effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_2"}, fields, index
    )

    assert error is not None, (
        "a real-but-wrong-label resolved value must not pass the mismatch "
        "check silently once more than one resolution of the kind exists"
    )
    assert substitutions == []
    assert effective == {"entity_id": "ENT_2"}, "arguments must be untouched on error"
    assert "ENT_1" not in error and "ENT_2" not in error, f"resolved value leaked (SI-2): {error!r}"
    assert "Acme Corp" in error and "Beta Ltd" in error, (
        f"on-record labels must be named so $ref:entity_id:<label> is reachable: {error!r}"
    )


def test_raw_value_matching_the_other_labelled_resolution_is_also_rejected():
    """The flip side of the above: the OTHER value from the same ambiguous
    pair is rejected too — the gate cannot tell which one was intended, so it
    fails closed for both, not just the one the finding's repro used."""
    index = {"entity_id": [("Acme Corp", "ENT_1"), ("Beta Ltd", "ENT_2")]}
    fields = {"entity_id": "entity_id"}

    _effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_1"}, fields, index
    )

    assert error is not None
    assert substitutions == []


def test_raw_value_unrelated_to_either_resolution_still_rejected():
    """Regression: a raw value matching NEITHER of two resolutions was
    already rejected before this fix and must remain so."""
    index = {"entity_id": [("Acme Corp", "ENT_1"), ("Beta Ltd", "ENT_2")]}
    fields = {"entity_id": "entity_id"}

    _effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_9999"}, fields, index
    )

    assert error is not None
    assert substitutions == []


def test_single_resolution_raw_match_is_unaffected():
    """Regression: with only ONE resolution of a kind on record, there is no
    ambiguity — a raw value equal to it must still pass directly, unchanged
    from before this fix."""
    index = {"entity_id": [("Acme Corp", "ENT_1")]}
    fields = {"entity_id": "entity_id"}

    effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_1"}, fields, index
    )

    assert error is None
    assert effective == {"entity_id": "ENT_1"}
    assert substitutions == []


def test_labelled_ref_still_disambiguates_after_the_fix():
    """Regression: $ref:<kind>:<label> remains the correct, unambiguous way
    to reference one of several resolutions — untouched by this fix."""
    index = {"entity_id": [("Acme Corp", "ENT_1"), ("Beta Ltd", "ENT_2")]}
    fields = {"entity_id": "entity_id"}

    effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "$ref:entity_id:Acme Corp"}, fields, index
    )

    assert error is None, error
    assert effective == {"entity_id": "ENT_1"}
    assert substitutions and substitutions[0].field_name == "entity_id"


def test_strict_false_field_still_allows_raw_value_despite_ambiguity():
    """Regression: strict=False (the per-field opt-out) still bypasses the
    mismatch check entirely, ambiguous or not — this fix only tightens the
    default strict behavior."""
    index = {"entity_id": [("Acme Corp", "ENT_1"), ("Beta Ltd", "ENT_2")]}
    fields = {"entity_id": "entity_id"}

    effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail_lenient",
        {"entity_id": "ENT_2"},
        fields,
        index,
        strict_fields={"entity_id": False},
    )

    assert error is None
    assert effective == {"entity_id": "ENT_2"}
    assert substitutions == []
