"""RT-B-002 regression: the RT-A-008 bounded-recovery bound must cover the
AMBIGUITY rejection, not only the single-resolution mismatch.

``resolve_reuse_fields`` returned the "value is ambiguous" error from an
early ``return`` placed ABOVE the ``reject_counts`` increment, so once two or
more resolutions of a kind were on record — the common shape in any
multi-entity conversation — a field left at every default (``strict=True``,
``allow_raw_override=False``) rejected a genuinely new raw value forever and
``reject_counts`` stayed empty. The recovery path that rejection recommends,
``$ref:<kind>:<label>``, is itself rejected by RT-A-007 for a label no
resolution carries, so the model had no in-band move left and could only loop
on the resolver tool until ``max_turns`` — exactly the liveness hole RT-A-008
claims, unconditionally, to have closed.

RT-002 follow-up: the forced-passthrough recovery itself is an OPT-IN
(``LoopPolicies.reuse_forced_passthrough_limit`` defaults to ``0`` —
reject-forever). The end-to-end ``run_loop`` tests below cover both: opting
in recovers after the bound, the default policy rejects the same new raw id
forever.
"""

from __future__ import annotations

import functools
from typing import Annotated, Any

import pytest
from pydantic import BaseModel

from agent_sdk.agent.events import AuditEvent, ToolResultEvent
from agent_sdk.agent.loop import LoopPolicies, run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.reuse import (
    MAX_CONSECUTIVE_REUSE_REJECTIONS,
    Reusable,
    ReuseKind,
    ReuseSubstitution,
    resolve_reuse_fields,
)
from agent_sdk.testing import FakeModelClient, reply, tool_call

pytestmark = pytest.mark.asyncio

_TWO_RESOLUTIONS: dict[str, list[tuple[str | None, Any]]] = {
    "entity_id": [("Acme Corp", "ENT_1"), ("Beta Ltd", "ENT_2")]
}

# RT-021: resolve_reuse_fields's own max_consecutive_rejections default is
# now fail-closed (0) — these unit-level tests exercise the OPTED-IN
# bounded-recovery shape directly, so they supply the module's suggested
# value as their own default.
resolve_reuse_fields = functools.partial(
    resolve_reuse_fields, max_consecutive_rejections=MAX_CONSECUTIVE_REUSE_REJECTIONS
)


# ── unit-level: resolve_reuse_fields(reject_counts=...) ────────────────────


async def test_ambiguity_rejection_is_bounded_like_the_mismatch_rejection():
    """With two resolutions on record, a new raw value must recover after the
    same bounded window the single-resolution mismatch already honoured."""
    fields = {"entity_id": "entity_id"}
    reject_counts: dict[tuple[str, str, str], int] = {}

    for attempt in range(MAX_CONSECUTIVE_REUSE_REJECTIONS):
        _effective, substitutions, error = resolve_reuse_fields(
            "get_entity_detail",
            {"entity_id": "ENT_NEW"},
            fields,
            _TWO_RESOLUTIONS,
            reject_counts=reject_counts,
        )
        assert error is not None, "must still reject within the bounded-recovery window"
        assert substitutions == []
        # RT-C-001: keyed on (tool, field, repr(raw value)), not just
        # (tool, field) — same raw value "ENT_NEW" every attempt here, so
        # the count still accumulates the same way for this single-value
        # sequence.
        assert reject_counts == {
            ("get_entity_detail", "entity_id", repr("ENT_NEW")): attempt + 1
        }, (
            "the ambiguity rejection must increment the recovery counter, not "
            "return above it"
        )

    effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail",
        {"entity_id": "ENT_NEW"},
        fields,
        _TWO_RESOLUTIONS,
        reject_counts=reject_counts,
    )
    assert error is None, "must recover instead of rejecting forever"
    assert effective == {"entity_id": "ENT_NEW"}
    assert substitutions == [
        ReuseSubstitution(field_name="entity_id", kind="entity_id", via_forced_passthrough=True)
    ]
    assert reject_counts == {}, "the counter resets once the budget is spent"


async def test_ambiguity_rejection_text_unchanged_within_the_bound():
    """The bound changes WHEN the rejection stops, never what it says — no
    new escape hatch is advertised to the model (RT-002/SI-2), and no VALUE
    (raw or resolved) ever leaks. RT-D-001: the text DOES now name the
    kind's on-record LABELS — display names, not values — since that is the
    only way the ``$ref:<kind>:<label>`` recovery move it recommends is
    reachable on a transport (AG-UI) whose transcript never replays the
    original marker back to the model."""
    _e, _s, error = resolve_reuse_fields(
        "get_entity_detail",
        {"entity_id": "ENT_NEW"},
        {"entity_id": "entity_id"},
        _TWO_RESOLUTIONS,
        reject_counts={},
    )
    assert error == (
        "tool 'get_entity_detail' field 'entity_id' value is ambiguous: more "
        "than one entity_id has been resolved in this conversation (known "
        "labels: Acme Corp, Beta Ltd); reference "
        "it via $ref:entity_id:<label>"
    )
    assert "$raw" not in error
    assert "ENT_NEW" not in error and "ENT_1" not in error and "ENT_2" not in error


async def test_ambiguity_reject_forever_preserved_without_reject_counts():
    """A caller that predates RT-A-008 (no ``reject_counts``) keeps the
    original reject-forever behavior byte-for-byte."""
    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS + 3):
        _e, substitutions, error = resolve_reuse_fields(
            "get_entity_detail", {"entity_id": "ENT_NEW"}, {"entity_id": "entity_id"},
            _TWO_RESOLUTIONS,
        )
        assert error is not None
        assert substitutions == []


async def test_ambiguity_and_mismatch_share_one_consecutive_budget():
    """The counter is per (tool, field), not per rejection REASON: a run that
    rejects once as a mismatch and then as an ambiguity (a second resolution
    landed in between) must not restart the budget."""
    fields = {"entity_id": "entity_id"}
    one: dict[str, list[tuple[str | None, Any]]] = {"entity_id": [("Acme Corp", "ENT_1")]}
    reject_counts: dict[tuple[str, str, str], int] = {}

    _e, _s, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_NEW"}, fields, one, reject_counts=reject_counts
    )
    assert error is not None
    assert reject_counts == {("get_entity_detail", "entity_id", repr("ENT_NEW")): 1}

    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS - 1):
        _e, _s, error = resolve_reuse_fields(
            "get_entity_detail", {"entity_id": "ENT_NEW"}, fields, _TWO_RESOLUTIONS,
            reject_counts=reject_counts,
        )
        assert error is not None

    _effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_NEW"}, fields, _TWO_RESOLUTIONS,
        reject_counts=reject_counts,
    )
    assert error is None, "a mid-sequence change of rejection reason must not reset the budget"
    assert substitutions == [
        ReuseSubstitution(field_name="entity_id", kind="entity_id", via_forced_passthrough=True)
    ]


async def test_ambiguity_budget_resets_on_a_successful_labelled_ref():
    """A successful ``$ref:<kind>:<label>`` between attempts resets the count
    — the budget guards a stuck retry loop on the SAME wrong value."""
    fields = {"entity_id": "entity_id"}
    reject_counts: dict[tuple[str, str, str], int] = {}

    _e, _s, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_NEW"}, fields, _TWO_RESOLUTIONS,
        reject_counts=reject_counts,
    )
    assert error is not None

    effective, _s, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "$ref:entity_id:Beta Ltd"}, fields,
        _TWO_RESOLUTIONS, reject_counts=reject_counts,
    )
    assert error is None
    assert effective == {"entity_id": "ENT_2"}
    assert reject_counts == {}

    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS):
        _e, _s, error = resolve_reuse_fields(
            "get_entity_detail", {"entity_id": "ENT_NEW"}, fields, _TWO_RESOLUTIONS,
            reject_counts=reject_counts,
        )
        assert error is not None, "the reset must not have pre-spent the recovery budget"


async def test_ref_token_rejections_are_not_counted():
    """A ``$ref`` rejection leaves the caller a real recovery move (supply the
    raw value, or a label that IS on record), so it must not consume the
    raw-value recovery budget."""
    fields = {"entity_id": "entity_id"}
    reject_counts: dict[tuple[str, str, str], int] = {}

    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS + 2):
        _e, _s, error = resolve_reuse_fields(
            "get_entity_detail", {"entity_id": "$ref:entity_id:Nonesuch Ltd"}, fields,
            _TWO_RESOLUTIONS, reject_counts=reject_counts,
        )
        assert error is not None
        assert reject_counts == {}, "a $ref rejection must never be counted"

    # And a $ref token is never force-passed through to the tool body.
    _e, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "$ref:entity_id:Nonesuch Ltd"}, fields,
        _TWO_RESOLUTIONS, reject_counts=reject_counts,
    )
    assert error is not None
    assert substitutions == []


# ── end-to-end: run_loop within a single conversation ──────────────────────


class ResolveEntityIn(BaseModel):
    name: str


class EntityDetailIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")]


received_entity_ids: list[str] = []

tools = ToolSet()

_ENTITY_IDS = {"Acme Corp": "ENT_1", "Beta Ltd": "ENT_2"}


@tools.tool(tier=1)
async def resolve_entity(inp: ResolveEntityIn) -> Any:
    """Resolve a company name to its canonical entity id."""
    return Reusable(value=_ENTITY_IDS[inp.name], kind="entity_id", label=inp.name)


@tools.tool(tier=1)
async def get_entity_detail(inp: EntityDetailIn) -> str:
    """Fetch details for a resolved entity id."""
    received_entity_ids.append(inp.entity_id)
    return f"detail-for-{inp.entity_id}"


REGISTRY = ToolRegistry([tools], {})


async def test_two_resolutions_then_new_raw_id_recovers_when_opted_in():
    """The RT-B-002 failure shape end-to-end: two entities resolved this
    conversation, then the user names a third id directly. Before the fix
    every retry returned the ambiguity error and the loop burned max_turns.
    RT-002: the forced-passthrough recovery is opt-in (defaults to 0/
    reject-forever — a correctness gate must never default to fail-open),
    so this test opts in explicitly via LoopPolicies; the default-policy
    behavior is covered by the sibling test below."""
    received_entity_ids.clear()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve Acme and Beta, then detail ENT_9"}]}
    ]
    model = FakeModelClient(
        [
            tool_call("resolve_entity", {"name": "Acme Corp"}),
            tool_call("resolve_entity", {"name": "Beta Ltd"}),
            *[
                tool_call("get_entity_detail", {"entity_id": "ENT_9"})
                for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS + 1)
            ],
            reply("done"),
        ]
    )
    policies = LoopPolicies(reuse_forced_passthrough_limit=MAX_CONSECUTIVE_REUSE_REJECTIONS)
    events: list[Any] = []
    async for ev in run_loop(
        model=model, registry=REGISTRY, adapters={}, system="test", messages=messages,
        policies=policies,
    ):
        events.append(ev)

    detail_results = [
        e for e in events
        if isinstance(e, ToolResultEvent) and e.tool_name == "get_entity_detail"
    ]
    assert len(detail_results) == MAX_CONSECUTIVE_REUSE_REJECTIONS + 1
    assert [r.ok for r in detail_results] == (
        [False] * MAX_CONSECUTIVE_REUSE_REJECTIONS + [True]
    ), "must reject up to the bound, then recover rather than looping forever"
    assert detail_results[-1].result == "detail-for-ENT_9"
    assert received_entity_ids == ["ENT_9"], "tool body must run exactly once, on recovery"

    forced = [
        e for e in events
        if isinstance(e, AuditEvent) and e.code == "reuse_forced_passthrough"
    ]
    assert len(forced) == 1
    assert forced[0].detail.get("field_name") == "entity_id"
    assert "ENT_9" not in repr(forced[0].detail), (
        f"raw value leaked in audit record (SI-2): {forced[0].detail!r}"
    )


async def test_two_resolutions_then_new_raw_id_rejected_forever_by_default():
    """RT-002: on the default LoopPolicies() (no opt-in), the ambiguity
    rejection must reject the same new raw id forever, never fail open into
    an unvalidated passthrough — the bounded-recovery escape hatch is
    opt-in only."""
    received_entity_ids.clear()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve Acme and Beta, then detail ENT_9"}]}
    ]
    attempts = MAX_CONSECUTIVE_REUSE_REJECTIONS + 3
    model = FakeModelClient(
        [
            tool_call("resolve_entity", {"name": "Acme Corp"}),
            tool_call("resolve_entity", {"name": "Beta Ltd"}),
            *[tool_call("get_entity_detail", {"entity_id": "ENT_9"}) for _ in range(attempts)],
            reply("done"),
        ]
    )
    events: list[Any] = []
    async for ev in run_loop(
        model=model, registry=REGISTRY, adapters={}, system="test", messages=messages,
    ):  # default LoopPolicies() — no opt-in
        events.append(ev)

    detail_results = [
        e for e in events
        if isinstance(e, ToolResultEvent) and e.tool_name == "get_entity_detail"
    ]
    assert len(detail_results) == attempts
    assert all(not r.ok for r in detail_results), (
        "the default policy must reject the same new raw id forever, never "
        "fail open into an unvalidated passthrough"
    )
    assert received_entity_ids == [], "tool body must never run on a rejected call"
    assert not [
        e for e in events if isinstance(e, AuditEvent) and e.code == "reuse_forced_passthrough"
    ], "no forced passthrough must occur under the default (opt-in-only) policy"
