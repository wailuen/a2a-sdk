"""RT-007 regression: resolved-index de-duplication must be type-aware, not
plain tuple ``==``.

``agent/reuse.py``'s ``scan_resolved`` and ``agent/loop.py``'s marker-append
both de-duplicate a ``(label, value)`` resolved-index entry before adding
it — an identical repeat resolution (e.g. a task-local cache hit re-folding
the same ``Reusable``) must contribute one index entry, not two, or a repeat
resolution would spuriously turn a single-match bare ``$ref:<kind>`` lookup
into an "ambiguous" rejection.

Before this fix that de-duplication compared ``(label, value)`` tuples with
plain ``==``. Python's cross-type numeric equality conflates ``1``/``True``/
``1.0`` (``1 == True`` is ``True``), so a ``Reusable(value=1, label="X")``
and a LATER, genuinely distinct ``Reusable(value=True, label="X")`` of the
same kind collapsed into a single index entry — after which
``_raw_matches_resolved`` (which deliberately enforces type identity at
MATCH time, specifically to stop exactly this ``1``/``True`` conflation)
could only ever compare a raw value against whichever one was indexed
first, silently discarding the second resolution. The same hazard the code
guards against at match time was reintroduced at index time.

Both call sites now key de-duplication via ``index_entry_key`` —
``(label, type(value).__name__, repr(value))`` — mirroring
``resolve_reuse_fields``'s own ``repr``-based ``reject_counts`` keying.

RT-A-02 follow-up: at ``agent/loop.py``'s live-growth call site specifically,
a *same-label* re-resolution to a type-aware-distinct value now REPLACES the
prior entry (last resolution wins) rather than appending a second, forever-
ambiguous one for that label — see
``test_rt_a02_reuse_relabel_last_write_wins.py``. ``index_entry_key`` still
does the same job it always did here: telling a genuinely new resolution
apart from a byte-identical repeat, so the growth code knows whether to
mutate at all. Only ``scan_resolved``'s rebuild-from-persisted-messages call
site keeps the original append-two-distinct-entries behavior this module
docstring describes.
"""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from pydantic import BaseModel

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.agent.loop import run_loop
from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.agent.reuse import Reusable, ReuseKind, index_entry_key, scan_resolved
from agent_sdk.testing import FakeModelClient, reply, tool_call

pytestmark = pytest.mark.asyncio


# ── unit: index_entry_key itself ───────────────────────────────────────────


async def test_index_entry_key_distinguishes_int_one_from_bool_true():
    assert index_entry_key("X", 1) != index_entry_key("X", True)


async def test_index_entry_key_distinguishes_float_from_int():
    assert index_entry_key("X", 1.0) != index_entry_key("X", 1)


async def test_index_entry_key_identical_for_identical_repeat():
    assert index_entry_key("X", "ENT_1") == index_entry_key("X", "ENT_1")


# ── unit: scan_resolved must not collapse a 1/True pair ─────────────────────


def _resolved_message(kind: str, label: str, value: Any) -> dict[str, Any]:
    return {
        "role": "user",
        "content": [
            {
                "toolResult": {
                    "toolUseId": "t1",
                    "content": [
                        {"json": {"__resolved__": {"kind": kind, "label": label, "value": value}}}
                    ],
                }
            }
        ],
    }


async def test_scan_resolved_keeps_int_one_and_bool_true_as_distinct_entries():
    messages = [
        _resolved_message("flag", "X", 1),
        _resolved_message("flag", "X", True),
    ]
    index = scan_resolved(messages)
    assert index["flag"] == [("X", 1), ("X", True)], (
        "a 1-valued and a True-valued resolution of the same label must "
        f"both survive de-duplication, got {index['flag']!r}"
    )


async def test_scan_resolved_still_dedupes_a_genuine_identical_repeat():
    messages = [
        _resolved_message("entity_id", "Acme", "ENT_1"),
        _resolved_message("entity_id", "Acme", "ENT_1"),
    ]
    index = scan_resolved(messages)
    assert index["entity_id"] == [("Acme", "ENT_1")], (
        "a byte-identical repeat resolution must still collapse to one entry"
    )


# ── end-to-end: run_loop's marker growth must recognize a 1/True pair as
# genuinely distinct (RT-A-02: same-label growth now replaces, not appends) ─

flag_tools = ToolSet()
flag_received: list[Any] = []


class ResolveFlagIn(BaseModel):
    which: str


class UseFlagIn(BaseModel):
    flag: Annotated[Any, ReuseKind("flag")]


@flag_tools.tool(tier=1)
async def resolve_flag(inp: ResolveFlagIn) -> Any:
    """Resolve a flag name to its raw stored value (int 1 or bool True) —
    always under the SAME label 'shared', so the two resolutions differ
    only by type/value, never by label."""
    value = 1 if inp.which == "int_one" else True
    return Reusable(value=value, kind="flag", label="shared")


@flag_tools.tool(tier=1)
async def use_flag(inp: UseFlagIn) -> str:
    """Consume a flag value."""
    flag_received.append(inp.flag)
    return f"used-{inp.flag!r}"


FLAG_REGISTRY = ToolRegistry([flag_tools], {})


async def test_run_loop_live_index_last_write_wins_across_a_type_change():
    """Resolve the SAME label ("shared") twice WITHIN one run_loop call —
    once to int 1, once to bool True — then reference it via
    ``$ref:flag:shared``. This exercises loop.py's own in-memory
    ``resolved_index`` growth directly (RT-007's other call site, distinct
    from ``scan_resolved`` above), not a re-scan of the folded transcript.

    RT-A-02 changed the growth policy for a same-(kind, label)
    re-resolution from "append (permanently ambiguous — see
    test_rt_a02_reuse_relabel_last_write_wins.py)" to "replace (last
    resolution wins)". This test now covers the half of RT-007's property
    that survives that change: ``index_entry_key``'s type-aware identity
    must still correctly recognize int ``1`` and bool ``True`` as DIFFERENT
    values, not silently no-op via plain tuple ``==`` (which conflates
    ``1 == True``) — a plain-``==`` regression here would drop the second
    resolution entirely and leave the STALE int ``1`` on record instead of
    replacing it with the fresher bool ``True``."""
    flag_received.clear()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": [{"text": "resolve shared twice, then use it"}]}
    ]
    model = FakeModelClient(
        [
            tool_call("resolve_flag", {"which": "int_one"}),
            tool_call("resolve_flag", {"which": "bool_true"}),
            tool_call("use_flag", {"flag": "$ref:flag:shared"}),
            reply("done"),
        ]
    )
    events: list[Any] = []
    async for ev in run_loop(
        model=model, registry=FLAG_REGISTRY, adapters={}, system="test", messages=messages
    ):
        events.append(ev)

    use_results = [
        e for e in events if isinstance(e, ToolResultEvent) and e.tool_name == "use_flag"
    ]
    assert len(use_results) == 1
    assert use_results[0].ok is True, (
        "the fresher bool True resolution must replace the stale int 1 one "
        f"under the same label, resolving $ref:flag:shared unambiguously — "
        f"got error={use_results[0].error!r}"
    )
    assert flag_received == [True], (
        "use_flag must receive the FRESHEST resolution (bool True), proving "
        "index_entry_key's type-aware identity recognized it as distinct "
        "from the stale int 1 rather than silently no-op'ing the replace"
    )
