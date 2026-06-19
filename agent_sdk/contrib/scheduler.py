"""agent_sdk.contrib.scheduler — Scheduler helper wrapping lifespan_extras.

Provides a :class:`Scheduler` that lets you register recurring background jobs
with ``@sched.cron(interval_seconds=...)`` and then wire the jobs into the
agent's ``lifespan_extras`` list via ``sched.lifespan``.

Example usage::

    from agent_sdk import Agent
    from agent_sdk.contrib import Scheduler

    sched = Scheduler()

    @sched.cron(interval_seconds=300)
    async def refresh_cache():
        ...  # runs every 5 minutes

    agent = Agent(
        ...,
        lifespan_extras=[sched.lifespan],
    )

Both async and sync callables are accepted.  Sync callables are wrapped in
:func:`asyncio.to_thread` so they do not block the event loop.

Jobs start when the ASGI lifespan enters and are cancelled cleanly (no
:exc:`asyncio.CancelledError` propagation) when it exits.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Capture asyncio.sleep at import time so test patches of asyncio.sleep
# applied at runtime do not inadvertently affect production job loops.
_sleep = asyncio.sleep


class Scheduler:
    """Register async or sync callables as recurring background jobs.

    Usage::

        sched = Scheduler()

        @sched.cron(interval_seconds=60)
        async def my_job():
            print("tick")

        # Then pass sched.lifespan into Agent(lifespan_extras=[sched.lifespan])
    """

    def __init__(self) -> None:
        self._jobs: list[tuple[Callable[[], Any], int]] = []

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def cron(self, interval_seconds: int) -> Callable[[Callable[[], Any]], Callable[[], Any]]:
        """Return a decorator that registers ``fn`` to run every *interval_seconds*.

        Args:
            interval_seconds: How many seconds to wait between successive
                invocations of the decorated callable.

        Returns:
            A decorator that stores the callable and returns it unchanged, so
            the function can still be called directly in tests.

        Note:
            The first execution occurs **after** the first full interval, not at
            startup.  If an immediate initial run is required, call the function
            once before registering it with ``cron()``.

        Example::

            @sched.cron(interval_seconds=300)
            async def refresh():
                ...
        """
        if interval_seconds <= 0:
            raise ValueError(f"interval_seconds must be positive, got {interval_seconds!r}")

        def decorator(fn: Callable[[], Any]) -> Callable[[], Any]:
            self._jobs.append((fn, interval_seconds))
            return fn

        return decorator

    @property
    def lifespan(self) -> Callable[[FastAPI], Any]:
        """Return an async context-manager factory compatible with *lifespan_extras*.

        The returned callable accepts a :class:`~fastapi.FastAPI` app (which
        may be ignored), enters on startup — starting all registered jobs as
        :class:`asyncio.Task` objects — and cancels them cleanly on shutdown.

        Example::

            agent = Agent(..., lifespan_extras=[sched.lifespan])
        """
        # Bind the job list at the time .lifespan is accessed.  Jobs
        # registered *after* this point will NOT be included — register all
        # jobs before accessing .lifespan.
        jobs_snapshot = list(self._jobs)
        if not jobs_snapshot:
            logger.warning(
                "Scheduler.lifespan accessed with no registered jobs — "
                "ensure all @cron decorators run before accessing .lifespan"
            )

        @asynccontextmanager
        async def _lifespan(app: FastAPI):  # noqa: ARG001
            tasks: list[asyncio.Task[None]] = []
            for fn, interval in jobs_snapshot:
                task = asyncio.create_task(
                    _run_loop(fn, interval),
                    name=f"sched:{getattr(fn, '__name__', repr(fn))}@{interval}s",
                )
                tasks.append(task)
                logger.debug(
                    "Scheduler: started job %s every %ds",
                    getattr(fn, "__name__", repr(fn)),
                    interval,
                )
            try:
                yield
            finally:
                for task in tasks:
                    task.cancel()
                results = await asyncio.gather(*tasks, return_exceptions=True)
                for task, result in zip(tasks, results):
                    if isinstance(result, Exception) and not isinstance(
                        result, asyncio.CancelledError
                    ):
                        logger.warning(
                            "Scheduler: job %s raised %r during shutdown",
                            task.get_name(),
                            result,
                        )

        return _lifespan


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


async def _run_loop(fn: Callable[[], Any], interval_seconds: int) -> None:
    """Run *fn* in a loop, sleeping *interval_seconds* between invocations."""
    while True:
        try:
            await _sleep(interval_seconds)
            if inspect.iscoroutinefunction(fn):
                await fn()
            else:
                await asyncio.to_thread(fn)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Scheduler: unhandled exception in job %s — continuing",
                getattr(fn, "__name__", repr(fn)),
            )
