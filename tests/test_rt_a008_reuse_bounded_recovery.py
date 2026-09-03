"""RT-A-008 regression: bounded recovery for a ReuseKind field with no
in-band escape hatch under the landed defaults (``strict=True``,
``allow_raw_override=False``).

Before this fix, once any resolution of a kind existed, a raw value the
resolver tool cannot produce was rejected on *every* attempt — the rejection
is deliberately forbidden (RT-002) from naming the ``$raw:`` escape hatch,
which is off by default anyway — so the model looped on the resolver tool
until ``max_turns``. This covers both the unit-level ``resolve_reuse_fields``
contract (``reject_counts``) and the end-to-end ``run_loop`` behavior: a
field left at every default CAN recover after N consecutive rejections once
an operator opts into ``LoopPolicies.reuse_forced_passthrough_limit`` (a
positive integer) instead of failing forever within the same conversation.

RT-002 follow-up: ``reuse_forced_passthrough_limit`` itself defaults to
``0`` — reject-forever — precisely because this is a correctness gate and a
correctness gate must never default to fail-open; the unit-level
``resolve_reuse_fields(reject_counts=...)`` tests below pass an explicit
``max_consecutive_rejections`` (via ``MAX_CONSECUTIVE_REUSE_REJECTIONS``, the
module ceiling an operator may opt into) directly, so they are unaffected by
that default — only the end-to-end ``run_loop`` tests, which go through
``LoopPolicies``, need to opt in explicitly to see recovery at all.
"""

from __future__ import annotations

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


# ── unit-level: resolve_reuse_fields(reject_counts=...) ────────────────────


async def test_default_field_recovers_after_two_consecutive_rejections():
    """A field at every default (strict=True, allow_raw_override=False)
    must still gain an in-band recovery path when the caller tracks
    per-(tool, field) rejection counts — the exact liveness hole RT-A-008
    identified."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {"entity_id": [(None, "ENT_5831")]}
    reject_counts: dict[tuple[str, str, str], int] = {}

    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS):
        effective, substitutions, error = resolve_reuse_fields(
            "get_entity_detail",
            {"entity_id": "ENT_6236"},
            fields,
            index,
            reject_counts=reject_counts,
            max_consecutive_rejections=MAX_CONSECUTIVE_REUSE_REJECTIONS,
        )
        assert error is not None, "must still reject within the bounded-recovery window"
        assert substitutions == []
        assert effective == {"entity_id": "ENT_6236"}

    # One more attempt beyond the bound: passthrough, not another rejection.
    effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail",
        {"entity_id": "ENT_6236"},
        fields,
        index,
        reject_counts=reject_counts,
        max_consecutive_rejections=MAX_CONSECUTIVE_REUSE_REJECTIONS,
    )
    assert error is None, "must recover instead of rejecting forever"
    assert effective == {"entity_id": "ENT_6236"}
    assert substitutions == [
        ReuseSubstitution(field_name="entity_id", kind="entity_id", via_forced_passthrough=True)
    ]


async def test_reject_counts_omitted_preserves_old_reject_forever_behavior():
    """The default caller shape (no reject_counts argument, every existing
    caller before this fix) must be byte-identical to before: no bounded
    recovery, reject on every attempt."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {"entity_id": [(None, "ENT_5831")]}

    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS + 3):
        _effective, substitutions, error = resolve_reuse_fields(
            "get_entity_detail", {"entity_id": "ENT_6236"}, fields, index
        )
        assert error is not None
        assert substitutions == []


async def test_rejection_counter_is_scoped_per_tool_and_field():
    """A rejection on one (tool, field) pair must not consume the recovery
    budget of a different field or a different tool sharing the same kind."""
    fields_a = {"entity_id": "entity_id"}
    fields_b = {"other_field": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {"entity_id": [(None, "ENT_5831")]}
    reject_counts: dict[tuple[str, str, str], int] = {}

    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS):
        _e, _s, error = resolve_reuse_fields(
            "tool_a", {"entity_id": "ENT_6236"}, fields_a, index, reject_counts=reject_counts
        )
        assert error is not None

    # A different field on a different tool, same kind: still fresh budget.
    _e, _s, error = resolve_reuse_fields(
        "tool_b", {"other_field": "ENT_6236"}, fields_b, index, reject_counts=reject_counts
    )
    assert error is not None, "a different (tool, field) pair must not inherit the exhausted budget"


async def test_rejection_counter_resets_on_ref_substitution():
    """A successful $ref substitution between two mismatched raw attempts
    resets the consecutive count — the budget guards a stuck retry loop on
    the SAME wrong value, not a running total across the whole conversation."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {"entity_id": [(None, "ENT_5831")]}
    reject_counts: dict[tuple[str, str, str], int] = {}

    _e, _s, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_6236"}, fields, index, reject_counts=reject_counts
    )
    assert error is not None

    effective, substitutions, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "$ref:entity_id"}, fields, index,
        reject_counts=reject_counts,
    )
    assert error is None
    assert effective == {"entity_id": "ENT_5831"}
    assert substitutions == [ReuseSubstitution(field_name="entity_id", kind="entity_id")]

    for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS):
        _e, _s, error = resolve_reuse_fields(
            "get_entity_detail", {"entity_id": "ENT_6236"}, fields, index,
            reject_counts=reject_counts,
        )
        assert error is not None, "the reset must not have pre-spent the recovery budget"


async def test_forced_passthrough_error_text_unchanged_up_to_the_bound():
    """The rejection text within the bound stays exactly the existing
    SI-2-safe message — no new escape hatch is advertised to the model."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {"entity_id": [(None, "ENT_5831")]}
    reject_counts: dict[tuple[str, str, str], int] = {}

    _e, _s, error = resolve_reuse_fields(
        "get_entity_detail", {"entity_id": "ENT_9999"}, fields, index, reject_counts=reject_counts
    )
    assert error == (
        "tool 'get_entity_detail' field 'entity_id' value does not "
        "match a previously resolved entity_id; re-resolve it, or "
        "reference it via $ref:entity_id"
    )


# ── end-to-end: run_loop within a single conversation ──────────────────────


class ResolveEntityIn(BaseModel):
    name: str


class EntityDetailIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")]


received_entity_ids: list[str] = []

tools = ToolSet()

_ENTITY_IDS = {"PT IMC Pelita Logistik": "ENT_5831"}


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


async def _run(
    model: FakeModelClient,
    messages: list[dict[str, Any]],
    policies: LoopPolicies | None = None,
) -> list[Any]:
    events: list[Any] = []
    async for ev in run_loop(
        model=model, registry=REGISTRY, adapters={}, system="test", messages=messages,
        policies=policies,
    ):
        events.append(ev)
    return events


def _tool_results(events: list[Any]) -> list[ToolResultEvent]:
    return [e for e in events if isinstance(e, ToolResultEvent)]


async def test_model_stuck_retrying_wrong_raw_id_eventually_recovers_when_opted_in():
    """The exact RT-A-008 failure shape: a default-configured ReuseKind field
    (strict=True, allow_raw_override=False) is fed the same wrong raw value
    on every retry within a single run_loop call. With the RT-002 liveness
    fallback explicitly opted into (`reuse_forced_passthrough_limit` set to a
    positive bound — it defaults to 0/reject-forever, see the sibling test
    below), the model would otherwise loop on the resolver tool until
    max_turns; now the call eventually succeeds instead."""
    received_entity_ids.clear()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve PT IMC Pelita Logistik, then get details"}]}
    ]
    model = FakeModelClient(
        [
            tool_call("resolve_entity", {"name": "PT IMC Pelita Logistik"}),
            *[
                tool_call("get_entity_detail", {"entity_id": "ENT_6236"})
                for _ in range(MAX_CONSECUTIVE_REUSE_REJECTIONS + 1)
            ],
            reply("done"),
        ]
    )
    policies = LoopPolicies(reuse_forced_passthrough_limit=MAX_CONSECUTIVE_REUSE_REJECTIONS)
    events = await _run(model, messages, policies=policies)
    results = _tool_results(events)

    detail_results = [
        r for r in results if r.tool_name == "get_entity_detail"
    ]
    assert len(detail_results) == MAX_CONSECUTIVE_REUSE_REJECTIONS + 1
    assert [r.ok for r in detail_results] == (
        [False] * MAX_CONSECUTIVE_REUSE_REJECTIONS + [True]
    ), "must reject up to the bound, then recover rather than looping forever"
    assert detail_results[-1].result == "detail-for-ENT_6236"
    assert received_entity_ids == ["ENT_6236"], "tool body must run exactly once, on recovery"

    audits = [e for e in events if isinstance(e, AuditEvent)]
    forced = [a for a in audits if a.code == "reuse_forced_passthrough"]
    assert len(forced) == 1
    assert forced[0].detail.get("tool_name") == "get_entity_detail"
    assert forced[0].detail.get("field_name") == "entity_id"
    assert "ENT_6236" not in repr(forced[0].detail), (
        f"raw value leaked in audit record (SI-2): {forced[0].detail!r}"
    )


async def test_default_policies_reject_the_same_wrong_raw_id_forever():
    """RT-002: `LoopPolicies.reuse_forced_passthrough_limit` defaults to `0`
    — reject-forever — so a correctness gate never fails open by default. A
    field left at every default, on the default `LoopPolicies()` (no explicit
    opt-in), must keep rejecting the identical wrong raw value no matter how
    many times the model retries it within one conversation; the tool body
    must never run."""
    received_entity_ids.clear()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve PT IMC Pelita Logistik, then get details"}]}
    ]
    attempts = MAX_CONSECUTIVE_REUSE_REJECTIONS + 3
    model = FakeModelClient(
        [
            tool_call("resolve_entity", {"name": "PT IMC Pelita Logistik"}),
            *[tool_call("get_entity_detail", {"entity_id": "ENT_6236"}) for _ in range(attempts)],
            reply("done"),
        ]
    )
    events = await _run(model, messages)  # default LoopPolicies() — no opt-in
    results = _tool_results(events)

    detail_results = [r for r in results if r.tool_name == "get_entity_detail"]
    assert len(detail_results) == attempts
    assert all(not r.ok for r in detail_results), (
        "the default policy must reject the identical wrong raw value forever, "
        "never fail open into an unvalidated passthrough"
    )
    assert received_entity_ids == [], "tool body must never run on a rejected call"

    audits = [e for e in events if isinstance(e, AuditEvent)]
    assert not [a for a in audits if a.code == "reuse_forced_passthrough"], (
        "no forced passthrough must occur under the default (opt-in-only) policy"
    )
