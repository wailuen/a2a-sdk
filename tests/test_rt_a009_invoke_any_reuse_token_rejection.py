"""RT-A-009: ``ToolEntry.invoke_any`` must REJECT a ``$ref:<kind>``/``$raw:``
reuse token on a ``ReuseKind`` field, not hand it to the tool body as an
ordinary raw string.

``invoke_any`` (agent_sdk/agent/registry.py) is the shared dispatch helper
behind three surfaces with no ``messages`` transcript of their own — MCP
``tools/call``, the admin try-tool endpoint, and the commitments executor
(GH-148's own docstring, and its CHANGELOG entry, call these "not fixed
here: ... never accepts a $ref:<kind> token on that same call, by design").
Before this fix that sentence was true only in the sense that no
substitution ever happened — the token was NOT rejected either, it was
handed to ``self.decl.input_model.model_validate(...)`` and on to the tool
body as an ordinary string, unchanged
(test_gh148_reuse_kind_substitution.py's
``test_mcp_tools_call_ref_token_passes_through_no_conversation_transcript``,
now renamed to
``test_mcp_tools_call_ref_token_rejected_no_conversation_transcript`` to
match). A tool whose input model validates any string would then look up an
entity literally named ``"$ref:entity_id"`` and return a wrong-but-successful
result — worse than an error, since nothing in the response signals that the
token was never resolved. An MCP client (or any caller of these three
surfaces) that read the token syntax off the CHANGELOG or the loop-side
``input_schema(include_reuse_hint=True)`` description had no way to know it
would silently misfire here.

The fix: before invoking the tool body, ``invoke_any`` now rejects any
``decl.reuse_fields`` argument whose value is a string starting with
``REF_PREFIX`` (``$ref:``) or ``RAW_PREFIX`` (``$raw:``) — regardless of the
field's own ``strict``/``allow_raw_override`` flags, which only govern the
loop.py substitution/validation path and have no meaning on a transcript-free
surface — via a generic ``AgentError(ErrorCategory.VALIDATION, ...)`` every
caller already maps to its existing failure shape.

Tests:
1-4. Registry-level (no ASGI, hand-built ``ToolSet``): ``invoke_any`` raises
   for a ``$ref:`` token and a ``$raw:`` token (even on a field with
   ``allow_raw_override=True``) — the tool body never runs; a plain raw
   value keeps working (non-regression); a tool with no ``ReuseKind`` fields
   at all is untouched even if an argument happens to look like a token
   (non-regression, scope of the check).
5. End-to-end through the real ``CommitmentExecutor`` + a real
   ``ToolSet``/``ToolRegistry``-built ``ToolEntry`` (mirrors
   test_rt002_invoke_any_deferred_result.py's
   ``test_executor_fire_actually_runs_deferred_handle`` pattern): a committed
   ``$ref:`` argument on a ``ReuseKind`` field must mark the commitment
   FAILED with category ``validation`` and never run the tool body — never
   ``mark_fired`` with the literal token as if it were a real id.

MCP tools/call and admin try-tool end-to-end coverage for this same fix live
in test_gh148_reuse_kind_substitution.py (which already has the fixtures,
tools, and ``gh148_client``) —
``test_mcp_tools_call_ref_token_rejected_no_conversation_transcript`` and
``test_mcp_tools_call_raw_override_token_rejected_no_conversation_transcript``.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Annotated

import pytest
from pydantic import BaseModel

from agent_sdk.agent.registry import ToolEntry, ToolRegistry, ToolSet
from agent_sdk.agent.reuse import ReuseKind
from agent_sdk.contrib.commitments import CommitmentExecutor, CommitmentStore
from agent_sdk.models.errors import AgentError, ErrorCategory

pytestmark = pytest.mark.asyncio


rt_a009_tools = ToolSet()
rt_a009_received: list[str] = []


class EntityDetailIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id")]


class EntityDetailRawOverrideIn(BaseModel):
    entity_id: Annotated[str, ReuseKind("entity_id", allow_raw_override=True)]


class PlainIn(BaseModel):
    x: str


@rt_a009_tools.tool(tier=1)
async def rt_a009_get_entity_detail(inp: EntityDetailIn) -> str:
    """Fetch details for an entity id."""
    rt_a009_received.append(inp.entity_id)
    return f"detail-for-{inp.entity_id}"


@rt_a009_tools.tool(tier=1)
async def rt_a009_get_entity_detail_raw_override(inp: EntityDetailRawOverrideIn) -> str:
    """Fetch details for an entity id (raw-override field)."""
    rt_a009_received.append(inp.entity_id)
    return f"detail-for-{inp.entity_id}"


@rt_a009_tools.tool(tier=1)
async def rt_a009_plain_tool(inp: PlainIn) -> str:
    """A tool with no ReuseKind fields — must be untouched by this check."""
    return f"plain-{inp.x}"


def _entry(name: str) -> ToolEntry:
    decl = next(d for d in rt_a009_tools.decls if d.name == name)
    return ToolEntry(decl=decl)


# ── 1-4: registry-level ──────────────────────────────────────────────────


async def test_invoke_any_rejects_ref_token_on_reuse_kind_field():
    rt_a009_received.clear()
    entry = _entry("rt_a009_get_entity_detail")

    with pytest.raises(AgentError) as exc_info:
        await entry.invoke_any({"entity_id": "$ref:entity_id"}, {})

    assert exc_info.value.category == ErrorCategory.VALIDATION
    assert rt_a009_received == [], (
        "the tool body must never run for a $ref token on a surface with "
        "no conversation transcript to resolve it against"
    )


async def test_invoke_any_rejects_raw_token_on_reuse_kind_field_even_when_opted_in():
    """$raw: exists to bypass loop.py's mismatch check (agent/reuse.py's
    RT-002 escape hatch) — a surface with no transcript has no mismatch
    check to bypass in the first place, so the token is rejected the same
    as $ref:, even on a field with allow_raw_override=True."""
    rt_a009_received.clear()
    entry = _entry("rt_a009_get_entity_detail_raw_override")

    with pytest.raises(AgentError) as exc_info:
        await entry.invoke_any({"entity_id": "$raw:ENT_9001"}, {})

    assert exc_info.value.category == ErrorCategory.VALIDATION
    assert rt_a009_received == []


async def test_invoke_any_still_passes_through_a_plain_raw_value():
    """Non-regression: an ordinary (non-token) value on a ReuseKind field
    must keep working — this fix only rejects the two reserved prefixes."""
    rt_a009_received.clear()
    entry = _entry("rt_a009_get_entity_detail")

    result = await entry.invoke_any({"entity_id": "ENT_5831"}, {})

    assert result == "detail-for-ENT_5831"
    assert rt_a009_received == ["ENT_5831"]


async def test_invoke_any_unaffected_when_tool_has_no_reuse_fields():
    """Non-regression / scope: a tool with no ReuseKind fields at all is not
    touched by this check, even when an argument happens to look like a
    token on an unrelated plain field."""
    entry = _entry("rt_a009_plain_tool")

    result = await entry.invoke_any({"x": "$ref:entity_id"}, {})

    assert result == "plain-$ref:entity_id"


# ── 5: end-to-end through the real CommitmentExecutor ───────────────────


async def test_commitment_executor_rejects_ref_token_on_reuse_kind_field(tmp_path):
    rt_a009_received.clear()
    store = CommitmentStore(str(tmp_path / "commitments.db"))
    store.initialize()
    registry = ToolRegistry([rt_a009_tools], {})
    fire_at = (datetime.now(timezone.utc) - timedelta(seconds=1)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    cid = store.add(
        tool="rt_a009_get_entity_detail",
        args={"entity_id": "$ref:entity_id"},
        fire_at=fire_at,
    )

    executor = CommitmentExecutor(store, registry, {})
    fired = await executor.tick_once()

    assert fired == 1  # the due commitment was claimed and processed
    assert store.get(cid).status == "failed", (
        "a committed $ref token on a ReuseKind field must never be treated "
        "as a real id and fired"
    )
    assert rt_a009_received == [], "the tool body must never run"
    store.close()
