"""Store-level tests for InMemoryTaskStore.interrupt_ttl_remaining (RT-003).

RT-003: interrupt_ttl_remaining is only exercised end-to-end through the
AG-UI route test; its None branches (task_id absent, record not interrupted,
interrupt_deadline is None) had no direct unit test, so a regression that
made it return a bogus value or raise on a non-interrupted task would not
be caught at the store layer. These tests pin the contract directly against
InMemoryTaskStore under both a monotonic clock and a wall clock (see
routes/ag_ui.py RT-001: the caller must treat the return value as a
relative duration regardless of which clock the store uses internally).
"""

from __future__ import annotations

import time
from typing import Callable

import pytest

from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.tasks.memory import InMemoryTaskStore
from agent_sdk.tasks.store import TaskStore

_IDENTITY = Identity(kind="api_key", subject="test-runner", admin=True)


class _PreHookTaskStore(InMemoryTaskStore):
    """Stands in for an external TaskStore subclass written before the
    interrupt_ttl_remaining hook existed (RT-002): reuses every concrete
    InMemoryTaskStore behavior but pins the hook back to TaskStore's
    unoverridden default, so it always reports "unknown" rather than
    InMemoryTaskStore's real deadline-derived value."""

    interrupt_ttl_remaining = TaskStore.interrupt_ttl_remaining


def test_interrupt_ttl_remaining_unknown_task_returns_none() -> None:
    store = InMemoryTaskStore()
    assert store.interrupt_ttl_remaining("does-not-exist") is None


def test_interrupt_ttl_remaining_non_interrupted_task_returns_none() -> None:
    store = InMemoryTaskStore()
    task = new_task()
    store.create(task, _IDENTITY)
    assert store.interrupt_ttl_remaining(task.id) is None


@pytest.mark.asyncio
async def test_interrupt_ttl_remaining_none_after_resume() -> None:
    store = InMemoryTaskStore()
    task = new_task()
    store.create(task, _IDENTITY)
    store.mark_interrupted(task.id, "interrupt-1")

    assert store.deliver_resume(task.id, {"ok": True}) is True
    assert store.interrupt_ttl_remaining(task.id) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("clock", [time.monotonic, time.time])
async def test_interrupt_ttl_remaining_freshly_interrupted_task(
    clock: Callable[[], float],
) -> None:
    interrupt_ttl = 45.0
    store = InMemoryTaskStore(interrupt_ttl=interrupt_ttl, clock=clock)
    task = new_task()
    store.create(task, _IDENTITY)

    store.mark_interrupted(task.id, "interrupt-1")

    remaining = store.interrupt_ttl_remaining(task.id)
    assert remaining is not None
    assert 0 < remaining <= interrupt_ttl


@pytest.mark.asyncio
async def test_pre_hook_task_store_subclass_boots_and_reports_no_ttl() -> None:
    """RT-002: a TaskStore subclass that predates interrupt_ttl_remaining
    must still boot, and must report None (unknown) rather than a stale or
    fabricated value once the task is genuinely interrupted."""
    store = _PreHookTaskStore()
    task = new_task()
    store.create(task, _IDENTITY)
    store.mark_interrupted(task.id, "interrupt-1")

    assert store.interrupt_ttl_remaining(task.id) is None
