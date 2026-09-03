"""RT-001 (round 6, AG-UI cross-check) — the live-subscriber guard round 5
added to `_evict_over_capacity` protected only the CAPACITY-overflow eviction
path. `get()`'s TTL/interrupt-deadline expiry path — reachable from any
`get()` call and, critically, from `find_interrupt()` (AG-UI's resume lookup,
`routes/ag_ui.py::_resume_target_task_id`) on a task the caller isn't even
resuming — called `evict()` unconditionally on expiry with no such guard.
`sweep()`'s periodic background reap had the identical gap. Either path could
silently sever an unrelated tenant's live SSE stream with no `final:true`
frame, the exact harm class round 5 already fixed once at the capacity layer.
These tests pin the fix at the expiry layer.
"""

from __future__ import annotations

import asyncio

import pytest

from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.tasks.memory import InMemoryTaskStore


def _ident(subject: str) -> Identity:
    return Identity(kind="api_key", subject=subject)


class _FakeClock:
    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now


@pytest.mark.asyncio
async def test_ttl_expiry_never_evicts_a_live_streamed_task():
    """A record past its task TTL, but with a live subscriber, must survive
    `get()` — not be silently evicted mid-stream."""
    clock = _FakeClock()
    store = InMemoryTaskStore(task_ttl=10.0, clock=clock)

    victim = store.create(new_task(None), _ident("tenant-A"))
    sub = store.subscribe(victim.task.id)
    victim.worker = asyncio.get_running_loop().create_task(asyncio.sleep(3600))
    try:
        clock.now += 100.0  # well past the 10s TTL

        assert store.get(victim.task.id) is not None, (
            "TTL expiry evicted a live-streamed task out of the store"
        )
        assert len(victim.subscriptions) == 1, (
            "TTL expiry closed a live subscriber"
        )
        assert not victim.worker.cancelled(), (
            "TTL expiry cancelled a live task's worker"
        )
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub.get(), timeout=0.15)
    finally:
        victim.worker.cancel()


@pytest.mark.asyncio
async def test_find_interrupt_lookup_on_another_task_never_evicts_a_live_stream():
    """The exact AG-UI reproduction: a resume lookup for interrupt `other`
    walks every record, including an unrelated, TTL-expired-but-still-live
    task. That walk must not evict the unrelated task as a side effect."""
    clock = _FakeClock()
    store = InMemoryTaskStore(task_ttl=10.0, interrupt_ttl=10.0, clock=clock)

    victim = store.create(new_task(None), _ident("tenant-A"))
    sub = store.subscribe(victim.task.id)
    victim.worker = asyncio.get_running_loop().create_task(asyncio.sleep(3600))
    try:
        other = store.create(new_task(None), _ident("tenant-B"))
        store.mark_interrupted(other.task.id, "interrupt-other")

        clock.now += 100.0  # expires victim's TTL and other's interrupt window

        assert store.find_interrupt("interrupt-other") is None, (
            "expired interrupt should not resolve"
        )
        assert store.get(victim.task.id) is not None, (
            "an unrelated find_interrupt() lookup evicted a live-streamed task"
        )
        assert len(victim.subscriptions) == 1
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub.get(), timeout=0.15)
    finally:
        victim.worker.cancel()


@pytest.mark.asyncio
async def test_sweep_never_evicts_a_live_streamed_expired_task():
    """The periodic background sweeper must honor the same guard."""
    clock = _FakeClock()
    store = InMemoryTaskStore(task_ttl=10.0, clock=clock)

    victim = store.create(new_task(None), _ident("tenant-A"))
    sub = store.subscribe(victim.task.id)
    victim.worker = asyncio.get_running_loop().create_task(asyncio.sleep(3600))
    try:
        clock.now += 100.0

        store.sweep()

        assert store.get(victim.task.id) is not None, (
            "sweep() evicted a live-streamed expired task"
        )
        assert len(victim.subscriptions) == 1
        with pytest.raises(asyncio.TimeoutError):
            await asyncio.wait_for(sub.get(), timeout=0.15)
    finally:
        victim.worker.cancel()


@pytest.mark.asyncio
async def test_expired_task_with_no_subscriber_is_still_evicted():
    """The guard must protect only genuinely-streamed records — an expired
    task with no live subscriber remains ordinary TTL fodder for both `get()`
    and `sweep()`, or the fix would leak the store instead of severing a
    stream."""
    clock = _FakeClock()
    store = InMemoryTaskStore(task_ttl=10.0, clock=clock)

    lonely = store.create(new_task(None), _ident("tenant-A"))
    clock.now += 100.0

    assert store.get(lonely.task.id) is None, (
        "an expired task with no subscriber was pinned in the store by the guard"
    )

    other = store.create(new_task(None), _ident("tenant-B"))
    clock.now += 100.0
    store.sweep()
    assert store.get(other.task.id) is None, (
        "sweep() pinned an expired task with no subscriber"
    )


@pytest.mark.asyncio
async def test_leaked_subscription_does_not_block_ttl_expiry_eviction():
    """A subscription whose owning ASGI request task has already finished is
    a leak, not a live stream — `get()`'s expiry check reaps before deciding,
    same as `_evict_over_capacity`, so a leaked entry can't convert 'severed
    stream' into 'unbounded store'."""
    clock = _FakeClock()
    store = InMemoryTaskStore(task_ttl=10.0, clock=clock)

    victim = store.create(new_task(None), _ident("tenant-A"))

    async def _owner() -> None:
        store.subscribe(victim.task.id)

    owner_task = asyncio.get_running_loop().create_task(_owner())
    await owner_task  # the owning request task is now .done() -> the sub is dead
    assert len(victim.subscriptions) == 1

    clock.now += 100.0

    assert store.get(victim.task.id) is None, (
        "a dead (leaked) subscription pinned a record against TTL-expiry eviction"
    )
