"""C-024 — shared admission bookkeeping for indefinitely-held SSE routes.

Every route in this SDK that holds an open ``text/event-stream`` admits it
against a bounded budget before the ``StreamingResponse`` is ever constructed:
``GET /mcp`` and ``GET /mcp/sse`` (routes/mcp.py), ``POST /v1/message:stream``
and ``POST /v1/tasks/{id}:subscribe`` (routes/a2a.py), and ``POST /ag-ui/run``
(routes/ag_ui.py, which admits against the A2A budget). The server is
single-process by design (DESIGN.md §2), so those streams all contend for one
connection pool.

RT-002 (round 5): the bookkeeping behind that was implemented twice, in the
same wave, once per transport — a byte-identical ``_identity_key``, two copies
of the lazy-init table accessor, two copies of the liveness prune loop, and two
copies of the override-and-clamp limit resolver. The copies had already drifted
(different record arities), which is how the next fix lands in one and not the
other. This module is the single implementation; the routes keep only what is
genuinely transport-specific — their own cap constants, their own rejection
shape (MCP answers ``JSONResponse`` carrying ``MCP-Protocol-Version``, A2A
raises ``HTTPException`` so the app-level A2A error envelope can wrap it), and
A2A's extra per-task cap and deferred slot binding.

RT-001 (round 6): that deferred binding is reached ONLY through the claimed
slot's own ``subscribe(task_id)`` (routes/a2a.py's ``_ClaimedSlot``), which
performs ``store.subscribe()`` and the ``task_id`` rewrite below as one
synchronous step. It was previously a separate ``bind`` the route called after
its own ``store.subscribe()``, and ``/ag-ui/run`` — a documented sharer of the
per-task cap — never called it, so its slots kept the ``""`` placeholder and
``count_for_task`` could neither cap nor count them.

What is NOT shared, deliberately: the two budgets are separate tables
(``app.state.mcp_get_streams`` vs ``app.state.a2a_streams``). They bound
different transports with different defaults; merging them would be a behaviour
change, not a deduplication.
"""

from __future__ import annotations

import asyncio
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from ..auth.identity import Identity

__all__ = [
    "StreamSlot",
    "SlotTable",
    "identity_key",
    "slot_table",
    "prune_finished",
    "count_for_owner",
    "count_for_task",
    "resolve_per_identity_limit",
]


@dataclass
class StreamSlot:
    """One admitted stream's bookkeeping entry.

    ``owning_task`` is the ASGI request task, and it is the ONLY liveness fact
    ``prune_finished`` keys on — never elapsed wall-clock time. A live stream
    whose ``send()`` is backpressured, or whose heartbeat sleep overshoots under
    exactly the event-loop congestion these caps exist to bound, would age out
    of a TTL-based reaper while still open and defeat the cap.

    ``release`` is the slot's COMPLETE, idempotent teardown — every structure
    the admitting route registered under this key, not just this table (mcp_sse
    registers a ``_sse_queues()`` record too). Carrying it in the record is what
    lets the layer-3 backstop reclaim exactly what the fast paths reclaim; a
    reaper that reclaims less orphans the difference permanently.

    ``release`` MUST be ``async def``. Starlette dispatches a plain ``def``
    ``BackgroundTask`` via ``run_in_threadpool``, which would mutate this
    event-loop-owned table off-loop while the loop concurrently iterates it.

    ``task_id`` is ``""`` for a slot reserved before its task exists (A2A's
    no-taskId ``message:stream`` path, a fresh ``/ag-ui/run``) and is rewritten
    once a subscription is attached — which can only happen via the claimed
    slot's ``subscribe()``, so the rewrite cannot be skipped by a route that
    forgets it. Per-task counting only ever matches real ids, so a
    reserved-but-unbound slot counts toward the global and per-identity budgets
    — which is what bounds process load — and never toward a per-task one.
    """

    owner: str
    owning_task: "asyncio.Task[Any]"
    release: Callable[[], Awaitable[None]]
    task_id: str = ""


# Concrete alias so both routes annotate their table identically.
SlotTable = OrderedDict[str, StreamSlot]


def identity_key(identity: Identity) -> str:
    """Stable per-caller key binding a stream slot to its owner.

    NOTE (and this is a documented, supported deployment mode, not a bug):
    ``Identity.subject`` is an OAuth ``client_id`` or an API-key id — a
    *registration*, never an end user. Org-wide OAuth client provisioning
    (``provision-org-oauth-client``) and a shared API key both collapse every
    caller in the org onto ONE key here, so a per-identity cap built on this is
    really a per-ORG cap under those modes. That is why the defaults are in the
    low hundreds and are operator-overridable.
    """
    return f"{identity.kind}:{identity.subject}"


def slot_table(app: Any, attr: str) -> "OrderedDict[str, StreamSlot]":
    """Lazy-init accessor for a budget table stored on ``app.state.<attr>``."""
    streams = getattr(app.state, attr, None)
    if streams is None:
        streams = OrderedDict()
        setattr(app.state, attr, streams)
    return streams


async def prune_finished(streams: "OrderedDict[str, StreamSlot]") -> None:
    """Layer-3 backstop: reclaim every slot whose owning ASGI request task has
    finished, by invoking the slot's OWN ``release``.

    A bare generator ``finally`` is not a lifecycle hook and a response
    ``BackgroundTask`` can be skipped too: a hard cancellation of the owning
    request task unwinds the response cycle before ``stream_response`` pulls the
    first chunk AND before ``await self.background()`` is reached. This layer
    bounds that without ever discounting a slot that is still genuinely open.

    Calls ``release`` rather than popping directly so the backstop always
    reclaims exactly what the fast paths do. ``release`` is idempotent, so
    overlapping layers are harmless; the extra ``pop`` is a termination guard so
    a release that failed to clear its own slot cannot loop forever. Awaited on
    the event-loop thread, like every other caller.
    """
    for sid, slot in list(streams.items()):
        if slot.owning_task.done():
            await slot.release()
            streams.pop(sid, None)


def count_for_owner(streams: "OrderedDict[str, StreamSlot]", owner: str) -> int:
    """How many slots this identity currently holds."""
    return sum(1 for slot in streams.values() if slot.owner == owner)


def count_for_task(streams: "OrderedDict[str, StreamSlot]", task_id: str) -> int:
    """How many slots currently subscribe to this task. Never matches the ``""``
    placeholder of a reserved-but-unbound slot."""
    if not task_id:
        return 0
    return sum(1 for slot in streams.values() if slot.task_id == task_id)


def resolve_per_identity_limit(
    app: Any, attr: str, default: int, ceiling: int
) -> int:
    """Effective per-identity cap: operator override if set, else ``default``,
    clamped to ``ceiling``.

    A per-identity cap above the process-wide budget is meaningless and would
    only mask misconfiguration, hence the clamp.

    The override is validated ``ge=1`` at settings construction (config.py), so
    it can never arrive here as ``0`` or negative. That matters because every
    call site guards with ``count >= limit``: a ``0`` — the natural operator
    reading of "unlimited" — would be unconditionally true and deny every stream
    for every identity, silently. "Unlimited" is expressed by leaving the
    variable unset, which selects ``default``.
    """
    override = getattr(app.state.settings, attr, None)
    limit = override if override is not None else default
    return min(limit, ceiling)
