"""Tests for agent_sdk.contrib.scheduler."""

from __future__ import annotations

import asyncio
import importlib
import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Import tests
# ---------------------------------------------------------------------------


def test_import_from_contrib():
    """from agent_sdk.contrib import Scheduler must work."""
    from agent_sdk.contrib import Scheduler  # noqa: F401 — import is the assertion

    assert Scheduler is not None


def test_scheduler_class_accessible():
    """Scheduler is importable directly from its module too."""
    from agent_sdk.contrib.scheduler import Scheduler

    assert callable(Scheduler)


# ---------------------------------------------------------------------------
# .cron() registration tests
# ---------------------------------------------------------------------------


def test_cron_registers_exactly_one_job():
    """@sched.cron(5) registers exactly one job."""
    from agent_sdk.contrib import Scheduler

    sched = Scheduler()

    @sched.cron(interval_seconds=5)
    async def my_job():
        pass

    assert len(sched._jobs) == 1
    fn, interval = sched._jobs[0]
    assert fn is my_job
    assert interval == 5


def test_cron_returns_original_function():
    """The decorator must return the original callable unchanged."""
    from agent_sdk.contrib import Scheduler

    sched = Scheduler()

    async def my_job():
        return 42

    result = sched.cron(interval_seconds=10)(my_job)
    assert result is my_job


def test_cron_multiple_jobs():
    """Multiple @sched.cron decorators each add one entry."""
    from agent_sdk.contrib import Scheduler

    sched = Scheduler()

    @sched.cron(interval_seconds=1)
    async def job_a():
        pass

    @sched.cron(interval_seconds=2)
    async def job_b():
        pass

    assert len(sched._jobs) == 2


def test_cron_rejects_non_positive_interval():
    """interval_seconds <= 0 must raise ValueError."""
    from agent_sdk.contrib import Scheduler

    sched = Scheduler()
    with pytest.raises(ValueError, match="interval_seconds must be positive"):
        sched.cron(interval_seconds=0)


def test_cron_accepts_sync_callable():
    """Sync callables must be accepted (wrapped in asyncio.to_thread at runtime)."""
    from agent_sdk.contrib import Scheduler

    sched = Scheduler()

    @sched.cron(interval_seconds=30)
    def sync_job():
        pass

    assert len(sched._jobs) == 1


# ---------------------------------------------------------------------------
# .lifespan async context manager tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_starts_background_tasks():
    """Entering sched.lifespan must start one asyncio.Task per registered job."""
    from agent_sdk.contrib import Scheduler

    sched = Scheduler()
    started: list[str] = []

    @sched.cron(interval_seconds=9999)
    async def job_a():
        started.append("a")

    @sched.cron(interval_seconds=9999)
    async def job_b():
        started.append("b")

    app = MagicMock()
    created_tasks: list[asyncio.Task] = []
    original_create_task = asyncio.create_task

    def capturing_create_task(coro, **kwargs):
        task = original_create_task(coro, **kwargs)
        created_tasks.append(task)
        return task

    with patch("asyncio.create_task", side_effect=capturing_create_task):
        async with sched.lifespan(app):
            # Two tasks should have been created (one per job).
            # Give the event loop a tick to schedule tasks.
            await asyncio.sleep(0)
            # Both tasks should be alive (not done) — they're sleeping for 9999s.
            all_tasks = {t for t in asyncio.all_tasks() if "sched:" in (t.get_name() or "")}
            assert len(all_tasks) == 2

    # After exit, the tasks should be cancelled / done.
    for task in all_tasks:
        assert task.done()


@pytest.mark.asyncio
async def test_lifespan_cancels_tasks_cleanly():
    """Exiting sched.lifespan must cancel tasks without propagating CancelledError."""
    from agent_sdk.contrib import Scheduler

    sched = Scheduler()

    @sched.cron(interval_seconds=9999)
    async def long_running():
        await asyncio.sleep(9999)

    app = MagicMock()
    # Should not raise anything
    async with sched.lifespan(app):
        await asyncio.sleep(0)  # let the task start

    # If we reach here, no CancelledError was propagated — test passes.


@pytest.mark.asyncio
async def test_lifespan_with_no_jobs():
    """An empty Scheduler.lifespan must enter and exit without error."""
    from agent_sdk.contrib import Scheduler

    sched = Scheduler()
    app = MagicMock()

    async with sched.lifespan(app):
        pass  # nothing to cancel, should be fine


@pytest.mark.asyncio
async def test_lifespan_is_asynccontextmanager():
    """sched.lifespan must be callable and return an async context manager."""
    from agent_sdk.contrib import Scheduler

    sched = Scheduler()
    app = MagicMock()
    cm = sched.lifespan(app)

    assert hasattr(cm, "__aenter__")
    assert hasattr(cm, "__aexit__")


@pytest.mark.asyncio
async def test_lifespan_job_exception_does_not_crash_shutdown():
    """A job that raises an exception must not prevent clean shutdown."""
    from agent_sdk.contrib import Scheduler
    import agent_sdk.contrib.scheduler as sched_mod

    sched = Scheduler()
    call_count = 0

    # Use a sleep that fires once then hangs, so the job raises exactly once
    # and the loop sleeps forever after that (cancelled cleanly on exit).
    invocation = 0

    async def controlled_sleep(n):
        nonlocal invocation
        invocation += 1
        if invocation > 1:
            # After the first job cycle, park indefinitely until cancelled.
            await asyncio.sleep(9999)

    @sched.cron(interval_seconds=1)
    async def bad_job():
        nonlocal call_count
        call_count += 1
        raise RuntimeError("boom")

    app = MagicMock()

    with patch.object(sched_mod, "_sleep", side_effect=controlled_sleep):
        async with sched.lifespan(app):
            # Wait for the first sleep + job execution to complete.
            await asyncio.sleep(0.05)

    # We reach here — no unhandled exception propagated.
    assert call_count >= 1


@pytest.mark.asyncio
async def test_lifespan_sync_job_runs_in_thread():
    """A sync job must be run via asyncio.to_thread (not blocking the loop)."""
    from agent_sdk.contrib import Scheduler
    import agent_sdk.contrib.scheduler as sched_mod

    sched = Scheduler()
    ran: list[bool] = []

    invocation = 0

    async def controlled_sleep(n):
        nonlocal invocation
        invocation += 1
        if invocation > 1:
            await asyncio.sleep(9999)

    @sched.cron(interval_seconds=1)
    def sync_job():
        ran.append(True)

    app = MagicMock()

    with patch.object(sched_mod, "_sleep", side_effect=controlled_sleep):
        async with sched.lifespan(app):
            await asyncio.sleep(0.05)

    assert ran, "sync job should have been called at least once"


# ---------------------------------------------------------------------------
# Helpful ImportError for mis-import of agent_sdk.scheduler
# ---------------------------------------------------------------------------


def test_agent_sdk_scheduler_import_error_message():
    """from agent_sdk import scheduler must raise ImportError with migration guide."""
    # Remove any cached entry so the stub is freshly executed.
    sys.modules.pop("agent_sdk.scheduler", None)
    with pytest.raises(ImportError, match="agent_sdk.contrib"):
        importlib.import_module("agent_sdk.scheduler")


# ---------------------------------------------------------------------------
# .lifespan snapshot semantics
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_lifespan_snapshot_excludes_late_registrations():
    """Jobs registered after .lifespan is first accessed must NOT be started.

    The .lifespan property captures a snapshot of _jobs at access time.
    Any job added to the scheduler afterwards is silently excluded.
    """
    from agent_sdk.contrib import Scheduler

    sched = Scheduler()

    @sched.cron(interval_seconds=9999)
    async def early_job():
        pass

    app = MagicMock()

    # Capture the lifespan *before* registering the late job.
    lifespan_fn = sched.lifespan  # snapshot taken here — only early_job included

    @sched.cron(interval_seconds=9999)
    async def late_job():
        pass

    # sched._jobs now has 2 jobs, but the snapshot inside lifespan_fn only has 1.
    async with lifespan_fn(app):
        await asyncio.sleep(0)
        sched_tasks = {
            t for t in asyncio.all_tasks() if "sched:" in (t.get_name() or "")
        }
        # Only early_job should be running — late_job was registered after the snapshot.
        assert len(sched_tasks) == 1
        assert any("early_job" in t.get_name() for t in sched_tasks)
        assert not any("late_job" in t.get_name() for t in sched_tasks)
