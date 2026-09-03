"""RT-018 regression: `resolve_reuse_fields` must treat an explicit `None`
argument on an optional `ReuseKind` field as "not supplied", not as a raw
value to match against prior resolutions.

`ReuseKind`'s own docstring documents `<scalar> | None` as a supported field
shape, and `_strip_optional` exists specifically to see through it. But once
any resolution of that kind exists in `index`, `_raw_matches_resolved(None,
"ENT_1")` is False (type/value mismatch), so the strict-match branch rejected
the call outright — permanently, since `$raw:` yields the string `""`, not
`None`, so there was no way to recover the omitted-field call once any
resolution of that kind existed.
"""

from __future__ import annotations

from agent_sdk.agent.reuse import resolve_reuse_fields


def test_none_argument_passes_through_when_resolution_exists():
    index = {"entity_id": [(None, "ENT_1")]}
    fields = {"entity_id": "entity_id"}

    effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"entity_id": None}, fields, index
    )

    assert error is None
    assert effective == {"entity_id": None}
    assert substitutions == []


def test_none_argument_passes_through_when_no_resolution_exists():
    index: dict = {}
    fields = {"entity_id": "entity_id"}

    effective, substitutions, error = resolve_reuse_fields(
        "some_tool", {"entity_id": None}, fields, index
    )

    assert error is None
    assert effective == {"entity_id": None}
    assert substitutions == []
