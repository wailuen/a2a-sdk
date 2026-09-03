"""RT-003 — ``TaskStore.subscribe()`` conformance: dead subscriptions must be
reaped before a new one is appended, for EVERY ``TaskStore`` implementation,
not only ``InMemoryTaskStore``.

Root cause: the reap (drop any ``Subscription`` whose ``owner_task.done()``)
previously lived only inside ``InMemoryTaskStore.subscribe`` — the abstract
``TaskStore.subscribe`` declaration carried no docstring stating the
obligation, and every sibling abstractmethod on the same ABC does. ``TaskStore``
is a documented public extension point (``Agent(task_store=...)``), so a
third-party or future shared-backend implementation that reproduces only the
*shape* of ``subscribe()`` (register a ``Subscription``, append it, return it)
silently reintroduces the unbounded ``record.subscriptions`` growth this
backstop exists to close — ``store.publish`` walks that list for every frame.

Fix: the reap is now a CONCRETE method on the ``TaskStore`` base class
(``reap_dead_subscriptions``), so any subclass gets it for free just by
calling ``self.reap_dead_subscriptions(record)`` from its own ``subscribe()``
— and the abstract ``subscribe`` docstring states the obligation explicitly.

RT-002 (round 7): that fix, and this suite, covered only the CONSUME half of
the contract. ``reap_dead_subscriptions`` keeps every entry whose
``owner_task`` is ``None``, and ``Subscription.__init__`` defaults it to
``None`` — so an implementation that faithfully called the reap but never
stamped ``sub.owner_task`` on the subscription it RETURNS had a permanently
vacuous backstop, leaking exactly as much as one that never reaped at all.
The original suite could not see that: it seeded ``owner_task`` by hand on its
fixtures and never asserted anything about what ``store.subscribe()`` itself
produced, so a stamp-less implementation passed. Both halves are now hoisted
into one concrete ``TaskStore.new_subscription(record, maxsize)`` and both are
asserted below — including end-to-end, via a subscription this suite never
touches, so the reap is proven non-vacuous rather than merely present.

This module is a portable conformance suite: ``_STORE_FACTORIES`` lists every
``TaskStore`` implementation the SDK ships, and a future implementation
(shipped here or by a third party) should add its own factory to prove it
satisfies the identical contract.
"""

from __future__ import annotations

import asyncio
from typing import Callable

import pytest

from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import Subscription, TaskStore

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)

_STORE_FACTORIES: list[Callable[[], TaskStore]] = [InMemoryTaskStore]


async def _assert_subscribe_reaps_dead_subscriptions(store: TaskStore) -> None:
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id, _IDENTITY)
    assert record is not None

    done_task = asyncio.create_task(asyncio.sleep(0))
    await done_task
    assert done_task.done()

    orphan = Subscription()
    orphan.owner_task = done_task
    record.subscriptions.append(orphan)

    live = store.subscribe(task.id)
    try:
        assert orphan not in record.subscriptions, (
            "subscribe() must drop a subscription whose owner_task.done() — "
            f"{type(store).__name__} left it behind, reintroducing the "
            "unbounded record.subscriptions growth publish() walks per frame"
        )
        assert live in record.subscriptions
    finally:
        store.unsubscribe(task.id, live)


async def _assert_subscribe_keeps_live_subscriptions(store: TaskStore) -> None:
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id, _IDENTITY)
    assert record is not None

    async def _never_finishes() -> None:
        await asyncio.Event().wait()

    live_owner = asyncio.create_task(_never_finishes())
    still_live = Subscription()
    still_live.owner_task = live_owner
    record.subscriptions.append(still_live)

    new_sub = store.subscribe(task.id)
    try:
        assert still_live in record.subscriptions, (
            f"{type(store).__name__} reaped a subscription whose owning task "
            "is still running — a live stream must never be reaped, no "
            "matter how long it has held its connection"
        )
    finally:
        store.unsubscribe(task.id, new_sub)
        store.unsubscribe(task.id, still_live)
        live_owner.cancel()
        try:
            await live_owner
        except BaseException:
            pass


async def _assert_subscribe_records_owner_task(store: TaskStore) -> None:
    """RT-002 (round 7): the PRODUCE half — the subscription ``subscribe()``
    returns must carry the calling ASGI request task as its ``owner_task``.

    Without this, ``reap_dead_subscriptions``'s ``owner_task is None`` keep-rule
    matches every subscription the store ever hands out and the backstop is a
    no-op. Nothing in this suite previously asserted it, so a store that reaped
    but never stamped passed clean."""
    task = new_task()
    store.create(task, _IDENTITY)

    sub = store.subscribe(task.id)
    try:
        assert sub.owner_task is asyncio.current_task(), (
            f"{type(store).__name__}.subscribe() must record the calling task "
            "as Subscription.owner_task — reap_dead_subscriptions keeps every "
            "owner_task=None entry, so omitting the stamp makes the reap "
            "permanently vacuous and record.subscriptions unbounded again"
        )
    finally:
        store.unsubscribe(task.id, sub)


async def _assert_reap_is_not_vacuous_end_to_end(store: TaskStore) -> None:
    """RT-002 (round 7): the two halves, composed, on subscriptions this test
    never touches — a store-produced orphan must be reclaimed by a later
    ``subscribe()``. This is the property that actually bounds
    ``record.subscriptions``; asserting the halves separately cannot prove it."""
    task = new_task()
    store.create(task, _IDENTITY)
    record = store.get(task.id, _IDENTITY)
    assert record is not None

    produced: list[Subscription] = []

    async def _orphan_subscriber() -> None:
        # Subscribes and is hard-unwound without unsubscribing — the exact
        # shape of a request task cancelled at Starlette's
        # send(http.response.start) checkpoint.
        produced.append(store.subscribe(task.id))

    orphan_owner = asyncio.create_task(_orphan_subscriber())
    await orphan_owner
    assert orphan_owner.done()
    orphan = produced[0]
    assert orphan in record.subscriptions

    live = store.subscribe(task.id)
    try:
        assert orphan not in record.subscriptions, (
            f"{type(store).__name__} left an orphan subscription IT PRODUCED "
            "on record.subscriptions after its owning task finished — the "
            "reap only fires on subscriptions whose owner_task was recorded"
        )
        assert record.subscriptions == [live]
    finally:
        store.unsubscribe(task.id, live)


@pytest.mark.parametrize("factory", _STORE_FACTORIES, ids=lambda f: f.__name__)
async def test_subscribe_records_owner_task(factory: Callable[[], TaskStore]) -> None:
    await _assert_subscribe_records_owner_task(factory())


@pytest.mark.parametrize("factory", _STORE_FACTORIES, ids=lambda f: f.__name__)
async def test_reap_is_not_vacuous_end_to_end(factory: Callable[[], TaskStore]) -> None:
    await _assert_reap_is_not_vacuous_end_to_end(factory())


@pytest.mark.parametrize("factory", _STORE_FACTORIES, ids=lambda f: f.__name__)
async def test_subscribe_reaps_dead_subscriptions(factory: Callable[[], TaskStore]) -> None:
    await _assert_subscribe_reaps_dead_subscriptions(factory())


@pytest.mark.parametrize("factory", _STORE_FACTORIES, ids=lambda f: f.__name__)
async def test_subscribe_keeps_live_subscriptions(factory: Callable[[], TaskStore]) -> None:
    await _assert_subscribe_keeps_live_subscriptions(factory())


def test_reap_dead_subscriptions_is_defined_on_the_base_class() -> None:
    """RT-003/RT-004: the reap must be reachable by a bare TaskStore subclass
    that never re-derives it — pin that it lives on the ABC, not only inside
    InMemoryTaskStore's own subscribe()."""
    assert "reap_dead_subscriptions" in TaskStore.__dict__
    assert "reap_dead_subscriptions" not in InMemoryTaskStore.__dict__


def test_new_subscription_is_defined_on_the_base_class() -> None:
    """RT-002 (round 7): the PRODUCE half must be reachable the same way the
    consume half is. A base-class backstop that keys on a field only the
    subclass populates is a no-op for every subclass that does not populate it,
    so reap+stamp+append is one concrete method here — not a two-step contract
    a subclass can satisfy halfway."""
    assert "new_subscription" in TaskStore.__dict__
    assert "new_subscription" not in InMemoryTaskStore.__dict__


def test_subscribe_abstract_docstring_states_both_halves_of_the_contract() -> None:
    doc = TaskStore.subscribe.__doc__ or ""
    assert "reap_dead_subscriptions" in doc, "consume half must be stated"
    assert "new_subscription" in doc, (
        "the docstring must point at the concrete helper that discharges the "
        "whole contract, not just describe it"
    )
    assert "owner_task" in doc, (
        "RT-002 (round 7): the docstring must also mandate RECORDING "
        "Subscription.owner_task — mandating only the reap leaves the reap "
        "vacuous for any implementation that does not already stamp it"
    )
