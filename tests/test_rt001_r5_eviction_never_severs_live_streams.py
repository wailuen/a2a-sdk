"""RT-001/RT-003 (round 5, fresh-lens) — the defects the first four fix rounds
kept circling without ever asserting.

Rounds 1-4 added admission caps at the ROUTE layer (routes/mcp.py,
routes/a2a.py) and moved the admission decision ahead of the durable write.
All of that is correct and none of it closed the hole, because the hole is one
layer below: `InMemoryTaskStore._evict_over_capacity` treated a record with
live subscribers as evictable. Overflow eviction is driven by TOTAL store
occupancy, so the caller who overflows the store is essentially never the owner
of the record that gets evicted — and `POST /v1/message:send`, which has no
admission cap at all and needs none, is enough to drive it.

The fix loop stalled because the suite was green throughout: nothing exercised
capacity overflow against a live subscriber, and nothing asserted the operator
caps rejected a nonsense value. These tests close that.
"""

from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.config import BaseAgentSettings
from agent_sdk.tasks.memory import InMemoryTaskStore


def _ident(subject: str) -> Identity:
    return Identity(kind="api_key", subject=subject)


# ── RT-001: overflow eviction must never sever a live stream ──


@pytest.mark.asyncio
async def test_overflow_from_another_tenant_never_evicts_a_live_streamed_task():
    """The reproduction, end-to-end at the store layer.

    Tenant A holds one live subscription. Tenant B — a DIFFERENT identity —
    creates enough unrelated tasks to overflow capacity. Before the fix this
    evicted A's task: `evict()` cancelled its worker and `sub.close()`d its
    subscriber, which pushes the bare `None` sentinel. routes/a2a.py's `gen()`
    reads `None` as "stop" and returns WITHOUT emitting a `final:true`
    TaskStatusUpdateEvent, so A's SSE stream simply died mid-flight and the
    task vanished from the store (a later `tasks:subscribe` 404s, work lost).
    """
    store = InMemoryTaskStore(capacity=3)

    victim = store.create(new_task(None), _ident("tenant-A"))
    sub = store.subscribe(victim.task.id)
    victim.worker = asyncio.get_running_loop().create_task(asyncio.sleep(3600))
    try:
        for _ in range(6):
            store.create(new_task(None), _ident("tenant-B"))

        assert store.get(victim.task.id) is not None, (
            "another tenant's overflow evicted a live-streamed task out of the store"
        )
        assert len(victim.subscriptions) == 1, (
            "another tenant's overflow closed a live subscriber"
        )
        assert not victim.worker.cancelled(), (
            "another tenant's overflow cancelled a live task's worker"
        )
        # The subscriber must NOT have been handed the close sentinel.
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub.get(), timeout=0.15)
    finally:
        victim.worker.cancel()


@pytest.mark.asyncio
async def test_unsubscribed_task_is_still_evictable():
    """The guard must protect only genuinely-streamed records — once the
    subscription is gone the record is ordinary LRU fodder again, or the fix
    would trade a severed stream for an unbounded store."""
    store = InMemoryTaskStore(capacity=3)

    victim = store.create(new_task(None), _ident("tenant-A"))
    sub = store.subscribe(victim.task.id)
    store.unsubscribe(victim.task.id, sub)

    for _ in range(6):
        store.create(new_task(None), _ident("tenant-B"))

    assert store.get(victim.task.id) is None, (
        "a task with no live subscriber was pinned in the store by the guard"
    )


@pytest.mark.asyncio
async def test_leaked_subscription_cannot_pin_a_record_forever():
    """A subscription whose owning ASGI request task has finished is a LEAK,
    not a live stream. `_evict_over_capacity` reaps before it decides, so a
    leaked entry can never convert 'severed stream' into 'unbounded store'."""
    store = InMemoryTaskStore(capacity=3)

    victim = store.create(new_task(None), _ident("tenant-A"))

    async def _owner() -> None:
        store.subscribe(victim.task.id)

    owner_task = asyncio.get_running_loop().create_task(_owner())
    await owner_task  # the owning request task is now .done() -> the sub is dead
    assert len(victim.subscriptions) == 1

    for _ in range(6):
        store.create(new_task(None), _ident("tenant-B"))

    assert store.get(victim.task.id) is None, (
        "a dead (leaked) subscription pinned a record against overflow eviction"
    )


def test_publish_refreshes_lru_position_not_just_the_ttl_clock():
    """`_evict_over_capacity` walks `self._records` in insertion order, so a
    task that has been streaming frames for an hour must not still be sitting
    at the LRU end. Before the fix `publish()` touched only `updated_at`, and
    `touch()` — the one helper that keeps position and clock in step — had zero
    call sites repo-wide."""
    store = InMemoryTaskStore(capacity=10)

    first = store.create(new_task(None), _ident("tenant-A"))
    second = store.create(new_task(None), _ident("tenant-A"))

    assert list(store._records) == [first.task.id, second.task.id]
    store.publish(first.task.id, object())
    assert list(store._records) == [second.task.id, first.task.id], (
        "publish() did not move the actively-streaming task to the MRU end"
    )


# ── RT-003: an operator cap of 0 must be refused, not read as "deny all" ──


@pytest.mark.parametrize("bad", [0, -1, -5])
@pytest.mark.parametrize(
    "alias",
    [
        "AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY",
        "AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY",
    ],
)
def test_nonpositive_stream_cap_is_refused_at_settings_construction(alias, bad, tmp_path):
    """Both route guards are `if owner_count >= limit:`, so a 0 or negative cap
    is unconditionally true and 429s EVERY stream for EVERY identity from the
    first request — with no startup error and no log. `0` is the natural
    operator reading of "unlimited", so this must fail loudly at construction.
    """
    with pytest.raises(ValidationError):
        BaseAgentSettings(
            DEV_MODE=True,
            DATA_DIR=str(tmp_path / "data"),
            AGENT_NAME="test-agent",
            **{alias: bad},
        )


@pytest.mark.parametrize(
    "alias",
    [
        "AGENT_SDK_MAX_MCP_STREAMS_PER_IDENTITY",
        "AGENT_SDK_MAX_A2A_STREAMS_PER_IDENTITY",
    ],
)
def test_positive_stream_cap_and_unset_are_both_accepted(alias, tmp_path):
    """`ge=1` must not break the supported cases: an explicit raise for a large
    org, and "unlimited" expressed by leaving the variable unset."""
    raised = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        **{alias: 900},
    )
    assert getattr(raised, alias.replace("AGENT_SDK_", "").lower()) == 900

    unset = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent"
    )
    assert getattr(unset, alias.replace("AGENT_SDK_", "").lower()) is None
