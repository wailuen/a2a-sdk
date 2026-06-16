"""TaskStore interface + records (DESIGN.md §5.2).

Process-local by design (§2 single-process invariant). The store owns task
lifecycle state shared by A2A routes, the loop worker, and SSE subscribers:

- LRU (1000) / TTL (1h) bounded records carrying their creating identity
- per-subscriber bounded queues (maxsize 256) with sentinel close;
  overflow terminates that subscriber's stream — never silent drops
- the resume channel for interrupted tasks: interrupted tasks are excluded
  from LRU pressure-eviction, get their own TTL (default 30 min), and are
  capped by AGENT_SDK_MAX_INTERRUPTED (at the cap a new interrupt is a typed
  task failure). Any eviction cancels the paused worker, closes the resume
  channel and sentinel-closes subscriber queues — nothing leaks.
"""

from __future__ import annotations

import abc
import asyncio
from dataclasses import dataclass, field
from typing import Any

from ..auth.identity import Identity
from ..models.a2a import Task

_CLOSE = object()  # sentinel: stream closed normally (final frame already published)


class StreamTerminated(Exception):
    """Subscriber queue overflowed or task was evicted: the stream ends
    without a final frame; the documented consumer contract is re-subscribe
    (then 404 if the task expired)."""


class Subscription:
    def __init__(self, maxsize: int = 256) -> None:
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=maxsize)
        self._killed = False

    def publish(self, event: Any) -> None:
        if self._killed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            # slow consumer: terminate, never drop frames silently (§5.2)
            self._killed = True

    def close(self) -> None:
        if self._killed:
            return
        try:
            self._queue.put_nowait(_CLOSE)
        except asyncio.QueueFull:
            self._killed = True

    async def get(self) -> Any:
        """Next event; None on normal close; StreamTerminated on kill."""
        if self._killed and self._queue.empty():
            raise StreamTerminated()
        event = await self._queue.get()
        if event is _CLOSE:
            return None
        return event


@dataclass(slots=True)
class TaskRecord:
    task: Task
    identity: tuple[str, str]  # (kind, subject) binding — §5.1
    created_at: float
    updated_at: float
    worker: asyncio.Task[Any] | None = None
    subscriptions: list[Subscription] = field(default_factory=list)
    # interrupt state
    interrupted: bool = False
    interrupt_deadline: float | None = None
    interrupt_id: str | None = None
    resume_future: asyncio.Future[Any] | None = None
    # cumulative model spend, survives resume cycles (§8)
    spent_tokens: int = 0
    # Converse-format history retained for resume folding
    messages: list[dict[str, Any]] = field(default_factory=list)


class TaskStore(abc.ABC):
    @abc.abstractmethod
    def create(self, task: Task, identity: Identity) -> TaskRecord: ...

    @abc.abstractmethod
    def get(self, task_id: str, identity: Identity | None = None) -> TaskRecord | None:
        """Identity-bound lookup: mismatched identity → None (existence is
        not leaked; routes answer 404 + -32001). ``identity=None`` or an
        admin api_key identity bypasses the binding."""

    @abc.abstractmethod
    def subscribe(self, task_id: str) -> Subscription: ...

    @abc.abstractmethod
    def unsubscribe(self, task_id: str, sub: Subscription) -> None:
        """Detach a consumer (stream ended or client disconnected) so the
        worker stops filling its queue."""

    @abc.abstractmethod
    def find_interrupt(
        self, interrupt_id: str, identity: Identity | None = None
    ) -> TaskRecord | None:
        """Identity-bound lookup by pending interrupt id (AG-UI resume path,
        §5.3)."""

    @abc.abstractmethod
    def publish(self, task_id: str, event: Any) -> None: ...

    @abc.abstractmethod
    def close_streams(self, task_id: str) -> None:
        """Normal close after the final frame was published."""

    @abc.abstractmethod
    def mark_interrupted(self, task_id: str, interrupt_id: str) -> asyncio.Future[Any]:
        """Register the interrupt and return the resume future the worker
        awaits. Raises AgentError at the MAX_INTERRUPTED cap."""

    @abc.abstractmethod
    def deliver_resume(self, task_id: str, value: Any) -> bool:
        """Hand a resume value to the paused worker. False if the task is
        not interrupted (caller maps to the spec error)."""

    @abc.abstractmethod
    def list_tasks_for_identity(
        self, identity: Identity, page_size: int = 50, page_token: str | None = None
    ) -> tuple[list[Task], str | None]:
        """Return up to ``page_size`` tasks owned by ``identity``, sorted by
        task id, plus an opaque ``nextPageToken`` when more remain."""

    @abc.abstractmethod
    def evict(self, task_id: str) -> None:
        """Cancel worker, close resume channel, sentinel-close subscribers,
        drop the record."""

    @abc.abstractmethod
    def sweep(self) -> None:
        """TTL pass — called periodically from the lifespan."""
