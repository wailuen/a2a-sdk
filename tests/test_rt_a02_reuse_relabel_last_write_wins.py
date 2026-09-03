"""RT-A02 regression: re-resolving the same (kind, label) to a NEW value
must not permanently dead-lock that label's `$ref:<kind>:<label>` token.

`agent/loop.py`'s live ``resolved_index`` growth (the ``if ok and
isinstance(result, Reusable):`` branch) used to only skip a byte-identical
``(label, value)`` repeat and otherwise APPEND — so resolving the same label
("Acme") to a genuinely new value (ENT_1, then ENT_2) left TWO entries
sharing one label. `$ref:entity_id:Acme` then hit the multi-match branch
(``len(matches) > 1``) and rejected as ambiguous, and the freshest raw value
(ENT_2) hit the ambiguity branch too — both rejections recommended
``$ref:<kind>:<label>``, the exact move the caller already made, with no
in-band escape. This is the exact liveness failure RT-A-008's bounded
recovery exists to prevent, reachable with zero operator opt-in.

Fix: a same-(kind, label) resolution now REPLACES the prior entry — last
resolution wins — keeping ``index_entry_key``'s type-aware dedup for the
byte-identical-repeat case (no mutation, no reordering).
"""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from pydantic import BaseModel

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.reuse import Reusable, ReuseKind, resolve_reuse_fields
from agent_sdk.testing import FakeModelClient, reply, tool_call

pytestmark = pytest.mark.asyncio


class ResolveIn(BaseModel):
    which: str


class DetailIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")]


tools = ToolSet()


@tools.tool(tier=1)
async def resolve_entity(inp: ResolveIn) -> Any:
    """Resolve the SAME label ("Acme") to different ids across calls —
    simulating a refreshed identifier being re-resolved mid-conversation."""
    value = "ENT_1" if inp.which == "first" else "ENT_2"
    return Reusable(value=value, kind="entity_id", label="Acme")


@tools.tool(tier=1)
async def get_detail(inp: DetailIn) -> str:
    """Fetch details for a resolved entity id."""
    return f"detail-{inp.entity_id}"


REGISTRY = ToolRegistry([tools], {})


async def _run(model: FakeModelClient, messages: list[dict[str, Any]]) -> list[Any]:
    events: list[Any] = []
    async for ev in run_loop(
        model=model, registry=REGISTRY, adapters={}, system="test", messages=messages
    ):
        events.append(ev)
    return events


async def test_labeled_ref_substitutes_the_freshest_resolution():
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]
    model = FakeModelClient(
        [
            tool_call("resolve_entity", {"which": "first"}, tool_call_id="c1"),
            tool_call("resolve_entity", {"which": "second"}, tool_call_id="c2"),
            tool_call("get_detail", {"entity_id": "$ref:entity_id:Acme"}, tool_call_id="c3"),
            reply("done"),
        ]
    )

    events = await _run(model, messages)

    results = [e for e in events if isinstance(e, ToolResultEvent)]
    detail_result = next(r for r in results if r.tool_name == "get_detail")
    assert detail_result.ok, detail_result.error
    assert detail_result.result == "detail-ENT_2", (
        "$ref:entity_id:Acme must substitute the FRESHEST resolution (ENT_2), "
        f"not reject as ambiguous or return the stale ENT_1 — got {detail_result.result!r} "
        f"(error={detail_result.error!r})"
    )


async def test_raw_freshest_value_still_passes_after_relabel():
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]
    model = FakeModelClient(
        [
            tool_call("resolve_entity", {"which": "first"}, tool_call_id="c1"),
            tool_call("resolve_entity", {"which": "second"}, tool_call_id="c2"),
            tool_call("get_detail", {"entity_id": "ENT_2"}, tool_call_id="c3"),
            reply("done"),
        ]
    )

    events = await _run(model, messages)

    results = [e for e in events if isinstance(e, ToolResultEvent)]
    detail_result = next(r for r in results if r.tool_name == "get_detail")
    assert detail_result.ok, detail_result.error
    assert detail_result.result == "detail-ENT_2", (
        "the raw freshest resolved value must pass directly (single entry on "
        f"record for the label after re-resolution) — got {detail_result.result!r} "
        f"(error={detail_result.error!r})"
    )


async def test_stale_raw_value_is_rejected_after_relabel():
    """The superseded value (ENT_1) must no longer be treated as a match —
    it was replaced, not merely joined by the fresher resolution."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]
    model = FakeModelClient(
        [
            tool_call("resolve_entity", {"which": "first"}, tool_call_id="c1"),
            tool_call("resolve_entity", {"which": "second"}, tool_call_id="c2"),
            tool_call("get_detail", {"entity_id": "ENT_1"}, tool_call_id="c3"),
            reply("done"),
        ]
    )

    events = await _run(model, messages)

    results = [e for e in events if isinstance(e, ToolResultEvent)]
    detail_result = next(r for r in results if r.tool_name == "get_detail")
    assert detail_result.ok is False, (
        "the superseded value must be rejected, not silently accepted as a "
        "second live entry"
    )


async def test_byte_identical_repeat_still_collapses_to_one_entry():
    """Regression: re-resolving the SAME label to the SAME value (a genuine
    repeat, e.g. a task-local cache hit re-folding the same Reusable) must
    not disturb the single-entry, unambiguous state."""
    messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "go"}]}]
    model = FakeModelClient(
        [
            tool_call("resolve_entity", {"which": "first"}, tool_call_id="c1"),
            tool_call("resolve_entity", {"which": "first"}, tool_call_id="c2"),
            tool_call("get_detail", {"entity_id": "$ref:entity_id"}, tool_call_id="c3"),
            reply("done"),
        ]
    )

    events = await _run(model, messages)

    results = [e for e in events if isinstance(e, ToolResultEvent)]
    detail_result = next(r for r in results if r.tool_name == "get_detail")
    assert detail_result.ok, detail_result.error
    assert detail_result.result == "detail-ENT_1"


# ── unit: resolve_reuse_fields' labeled multi-match message must not
# recommend the move the caller already made ────────────────────────────────


async def test_labeled_multi_match_message_does_not_recommend_the_label_the_caller_already_gave():
    """A same-label duplicate can still reach resolve_reuse_fields directly
    (e.g. inherited from a scan_resolved rebuild over persisted messages
    spanning more than one run_loop call) — the caller supplied
    $ref:entity_id:Acme, which already IS the disambiguated form, so the
    error must not tell it to do that again."""
    index = {"entity_id": [("Acme", "ENT_1"), ("Acme", "ENT_2")]}
    fields = {"entity_id": "entity_id"}

    _effective, substitutions, error = resolve_reuse_fields(
        "get_detail", {"entity_id": "$ref:entity_id:Acme"}, fields, index
    )

    assert error is not None
    assert substitutions == []
    assert "use $ref:entity_id:<label> to disambiguate" not in error, (
        f"must not recommend the exact move the caller already made: {error!r}"
    )


async def test_labeled_multi_match_message_echoes_the_labeled_token_form():
    """The old message printed the bare `$ref:<kind>` even when the caller
    supplied a labeled token — misreporting what was actually sent."""
    index = {"entity_id": [("Acme", "ENT_1"), ("Acme", "ENT_2")]}
    fields = {"entity_id": "entity_id"}

    _effective, _substitutions, error = resolve_reuse_fields(
        "get_detail", {"entity_id": "$ref:entity_id:Acme"}, fields, index
    )

    assert error is not None
    assert "$ref:entity_id:Acme" in error, (
        f"must echo the labeled token form actually supplied: {error!r}"
    )


async def test_bare_ref_multi_match_message_unchanged():
    """Regression: the bare $ref:<kind> (no label) multi-match branch keeps
    its original "use $ref:<kind>:<label> to disambiguate" advice — that
    advice is genuinely actionable when no label was supplied yet."""
    index = {"entity_id": [("Acme", "ENT_1"), ("Beta", "ENT_2")]}
    fields = {"entity_id": "entity_id"}

    _effective, _substitutions, error = resolve_reuse_fields(
        "get_detail", {"entity_id": "$ref:entity_id"}, fields, index
    )

    assert error is not None
    assert "use $ref:entity_id:<label> to disambiguate" in error
