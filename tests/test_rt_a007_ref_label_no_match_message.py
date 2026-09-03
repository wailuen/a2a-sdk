"""RT-A-007 regression: a labelled ``$ref:<kind>:<label>`` that matches zero
resolutions must not receive the same "does not resolve to exactly one
value; use $ref:<kind>:<label> to disambiguate" message as an *ambiguous*
(multi-match) ``$ref``.

Before the fix both the zero-match and multi-match cases fell through the
same ``if len(matches) != 1`` branch, so a caller who supplied
``$ref:entity_id:Acme Corp.`` (a label one character off from the resolved
``"Acme Corp"``) was told to disambiguate with a label — the exact thing it
already did. The model has no way to act on that and burns its turn budget
retrying label variations (the same liveness failure RT-008 fixed for the
raw-value mismatch path).

The fix splits the branch: a labelled ``$ref`` with zero matches gets a
distinct "no resolution carries that label" message; the disambiguate
wording is reserved for an actual multi-match. Neither message may echo the
caller-supplied label back (SI-2) — only the schema-declared field name and
kind.

RT-A-02 follow-up: the disambiguate wording is now reserved further still —
only for a *bare* ``$ref:<kind>`` multi-match (``test_bare_ref_matching_
more_than_one_keeps_disambiguate_wording`` below). A *labelled*
``$ref:<kind>:<label>`` that still matches more than one on-record entry
(``test_labelled_ref_matching_more_than_one_gets_relabel_wording`` below) no
longer gets that wording either — the caller already supplied a label, so
recommending ``$ref:<kind>:<label>`` again recommends the exact move it just
made. That state is reachable when a same-label duplicate survives in the
index (loop.py's own live growth now replaces on a same-label
re-resolution — see ``test_rt_a02_reuse_relabel_last_write_wins.py`` — but a
``scan_resolved`` rebuild over persisted messages spanning more than one
``run_loop`` call can still surface a stale one), and its supplied label
IS safe to echo (unlike the zero-match case above) because reaching this
branch already proves it names a real, on-record label.
"""

from __future__ import annotations

from agent_sdk.agent.reuse import resolve_reuse_fields


def test_labelled_ref_with_no_matching_label_gets_distinct_message():
    index = {"entity_id": [("Acme Corp", "ENT_1")]}
    fields = {"entity_id": "entity_id"}

    effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"entity_id": "$ref:entity_id:Acme Corp."}, fields, index
    )

    assert error is not None
    assert "disambiguate" not in error, (
        "a label was already supplied and matched nothing; telling the "
        "model to disambiguate with a label sends it down the wrong "
        "recovery path"
    )
    assert effective == {"entity_id": "$ref:entity_id:Acme Corp."}
    assert substitutions == []


def test_labelled_ref_no_match_message_never_echoes_supplied_label():
    index = {"entity_id": [("Acme Corp", "ENT_1")]}
    fields = {"entity_id": "entity_id"}

    _effective, _substitutions, error = resolve_reuse_fields(
        "some_tool", {"entity_id": "$ref:entity_id:Acme Corp."}, fields, index
    )

    assert error is not None
    assert "Acme Corp." not in error, f"supplied label leaked (SI-2): {error!r}"
    assert "Acme Corp" not in error, f"resolved label leaked (SI-2): {error!r}"
    assert "ENT_1" not in error, f"resolved value leaked (SI-2): {error!r}"
    assert "entity_id" in error
    assert "some_tool" in error


def test_labelled_ref_matching_exactly_one_still_resolves():
    index = {"entity_id": [("Acme Corp", "ENT_1"), ("Other Co", "ENT_2")]}
    fields = {"entity_id": "entity_id"}

    effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"entity_id": "$ref:entity_id:Acme Corp"}, fields, index
    )

    assert error is None
    assert effective == {"entity_id": "ENT_1"}
    assert len(substitutions) == 1


def test_labelled_ref_matching_more_than_one_gets_relabel_wording():
    """RT-A-02: a label was already supplied and STILL matches more than one
    on-record entry (a same-label duplicate). The old generic "...
    disambiguate" wording recommended the caller's own already-taken move;
    this case now gets its own wording that echoes the labelled token form
    actually supplied instead."""
    index = {"entity_id": [("Acme Corp", "ENT_1"), ("Acme Corp", "ENT_2")]}
    fields = {"entity_id": "entity_id"}

    effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"entity_id": "$ref:entity_id:Acme Corp"}, fields, index
    )

    assert error is not None
    assert "disambiguate" not in error, (
        "the caller already supplied a label; recommending "
        f"$ref:<kind>:<label> again recommends the exact move it just made: {error!r}"
    )
    assert "$ref:entity_id:Acme Corp" in error, (
        f"must echo the labelled token form actually supplied: {error!r}"
    )
    assert effective == {"entity_id": "$ref:entity_id:Acme Corp"}
    assert substitutions == []


def test_bare_ref_matching_more_than_one_keeps_disambiguate_wording():
    index = {"entity_id": [("Acme Corp", "ENT_1"), ("Other Co", "ENT_2")]}
    fields = {"entity_id": "entity_id"}

    effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"entity_id": "$ref:entity_id"}, fields, index
    )

    assert error is not None
    assert "disambiguate" in error
    assert effective == {"entity_id": "$ref:entity_id"}
    assert substitutions == []
