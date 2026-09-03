"""RT-005: a ``$raw:<value>`` token on a ``ReuseKind`` field that has NOT
opted into ``allow_raw_override`` must be rejected on the loop surface too,
not just on the transcript-free surfaces ``ToolEntry.invoke_any`` already
guards (RT-A-009, ``tests/test_rt_a009_invoke_any_reuse_token_rejection.py``).

Before this fix, ``resolve_reuse_fields`` only caught a non-opted-in
``$raw:`` token when at least one resolution of that field's ``kind`` was
already on record — in that case the token fell through to the ordinary
mismatch check and got rejected there by accident (the literal string
``"$raw:ENT_9"`` doesn't equal a real resolved id). But when NO resolution
of that kind exists yet, ``resolve_reuse_fields`` treats every raw value as
"genuinely new" and passes it through unchanged (the RT-008 "passes a raw
value through unchanged when no resolution of that kind exists yet"
contract) — including the literal token string, which then reaches the tool
body verbatim. RT-A-009's own reasoning ("a silent, wrong-but-successful
result, strictly worse than failing outright") applies identically here: the
loop surface is the ONE surface that advertises ``$ref:<kind>`` syntax to
the model via ``input_schema(include_reuse_hint=True)``, making it the most
likely surface for a model to try the sibling ``$raw:`` syntax too.

The fix: ``resolve_reuse_fields`` now rejects a ``$raw:``-prefixed string
outright, unconditionally, the moment ``raw_override_fields`` says the field
has NOT opted in — before any ``resolved_for_kind``/``strict`` branching —
so the token never reaches ``effective_arguments`` regardless of whether a
resolution exists yet, matching ``invoke_any``'s unconditional rejection.
"""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from pydantic import BaseModel

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.reuse import ReuseSubstitution, ReuseKind, resolve_reuse_fields
from agent_sdk.testing import FakeModelClient, reply, tool_call


# ── 1-4: direct resolve_reuse_fields calls (registry-level, no ASGI, sync) ─


def test_raw_token_rejected_without_opt_in_when_no_resolution_exists_yet():
    """The exact repro from the finding: index={} (no resolution of the
    kind exists yet), raw_override_fields={'entity_id': False} (not opted
    in) — must reject, not pass the token through verbatim."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {}

    effective, substitutions, error = resolve_reuse_fields(
        "lookup",
        {"entity_id": "$raw:ENT_9"},
        fields,
        index,
        raw_override_fields={"entity_id": False},
    )

    assert error is not None, "the $raw: token must not reach the tool body verbatim"
    assert substitutions == []
    assert effective == {"entity_id": "$raw:ENT_9"}, "arguments must be untouched on error"
    assert "$raw:ENT_9" not in error, f"raw value must not leak into the error (SI-2): {error!r}"


def test_raw_token_rejected_when_raw_override_fields_absent_and_no_resolution():
    """The direct-call counterpart with no ``raw_override_fields`` argument
    at all (every caller that predates RT-002) — must still deny by
    default, matching the documented "opposite default from strict_fields"
    contract, even with an empty index."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {}

    effective, substitutions, error = resolve_reuse_fields(
        "lookup", {"entity_id": "$raw:ENT_9"}, fields, index
    )

    assert error is not None
    assert substitutions == []
    assert effective == {"entity_id": "$raw:ENT_9"}


def test_raw_token_still_bypasses_when_field_opted_in_and_no_resolution():
    """Non-regression: a field WITH allow_raw_override=True keeps working
    exactly as before, including with an empty index."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {}

    effective, substitutions, error = resolve_reuse_fields(
        "lookup",
        {"entity_id": "$raw:ENT_9"},
        fields,
        index,
        raw_override_fields={"entity_id": True},
    )

    assert error is None
    assert effective == {"entity_id": "ENT_9"}
    assert substitutions == [
        ReuseSubstitution(field_name="entity_id", kind="entity_id", via_raw_override=True)
    ]


def test_raw_token_rejection_without_opt_in_not_counted_toward_bounded_recovery():
    """RT-B-002 parity: like the malformed-$ref rejection, an unauthorized
    $raw: token leaves the caller a real, obvious recovery move (supply the
    raw value directly, without the prefix) — it must not consume the
    RT-A-008 bounded-recovery budget shared with genuine mismatch
    rejections."""
    fields = {"entity_id": "entity_id"}
    index: dict[str, list[tuple[str | None, Any]]] = {}
    reject_counts: dict[tuple[str, str, str], int] = {}

    for _ in range(5):
        _effective, _subs, error = resolve_reuse_fields(
            "lookup",
            {"entity_id": "$raw:ENT_9"},
            fields,
            index,
            raw_override_fields={"entity_id": False},
            reject_counts=reject_counts,
        )
        assert error is not None

    assert reject_counts == {}, (
        "an unauthorized $raw: token must never accumulate toward, or trip, "
        f"the forced-passthrough budget: {reject_counts!r}"
    )


# ── 5: end-to-end through the real run_loop (loop-surface parity) ────────


class _EntityDetailIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")]


rt005_tools = ToolSet()
rt005_received: list[str] = []


@rt005_tools.tool(tier=1)
async def rt005_get_entity_detail(inp: _EntityDetailIn) -> str:
    """Fetch details for an entity id."""
    rt005_received.append(inp.entity_id)
    return f"detail-for-{inp.entity_id}"


RT005_REGISTRY = ToolRegistry([rt005_tools], {})


@pytest.mark.asyncio
async def test_run_loop_rejects_raw_token_without_opt_in_fresh_conversation():
    """End-to-end loop-surface parity with RT-A-009: a FRESH conversation
    (no resolver call, so no resolution of "entity_id" exists yet) supplies
    $raw:ENT_9001 on a field that never opted into allow_raw_override — the
    call must be rejected and the tool body must never run."""
    rt005_received.clear()
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "get details"}]}]
    model = FakeModelClient(
        [tool_call("rt005_get_entity_detail", {"entity_id": "$raw:ENT_9001"}), reply("done")]
    )

    events: list[Any] = []
    async for ev in run_loop(
        model=model,
        registry=RT005_REGISTRY,
        adapters={},
        system="test",
        messages=messages,
    ):
        events.append(ev)

    results = [e for e in events if isinstance(e, ToolResultEvent)]
    assert results, "expected at least one ToolResultEvent"
    assert not results[0].ok, "$raw: on a non-opted-in field must be rejected on the loop surface"
    assert rt005_received == [], "the tool body must never run for a rejected call"
