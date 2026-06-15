"""Abstract base class for Graph subscription persistence backends (§9).

:class:`SubscriptionBackend` defines the interface every persistence layer must
implement so that :class:`~agent_sdk.contrib.webhooks.subscriptions.GraphSubscriptionManager`
and :func:`~agent_sdk.contrib.webhooks.subscriptions.webhooks_renewal_lifespan` can
operate against any durable store (SQLite, Redis, Postgres, …) without coupling to
a specific implementation.

The canonical SQLite implementation is
:class:`~agent_sdk.contrib.webhooks.subscriptions.SubscriptionStore`, which
subclasses this ABC.
"""

from __future__ import annotations

import abc
from typing import Any, List


class SubscriptionBackend(abc.ABC):
    """Abstract persistence backend for Graph webhook subscriptions.

    All methods match the public interface of
    :class:`~agent_sdk.contrib.webhooks.subscriptions.SubscriptionStore` exactly.
    Concrete implementations MUST honour the same security invariant: the
    ``clientState`` secret is NEVER persisted — only the non-secret reference label.
    """

    @abc.abstractmethod
    def initialize(self) -> None:
        """Create / migrate any schema or connection resources.

        Called once at startup before any other method.
        """

    @abc.abstractmethod
    def upsert(
        self,
        *,
        id: str,
        resource: str,
        change_type: str,
        notification_url: str,
        expiration: str,
        lifecycle_url: str | None = None,
        client_state_ref: str = "default",
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Insert or update a subscription record.

        The ``clientState`` secret MUST NOT be stored. Only the non-secret
        ``client_state_ref`` label is persisted.
        """

    @abc.abstractmethod
    def set_expiration(self, id: str, expiration: str) -> bool:
        """Update the ``expirationDateTime`` for *id*.

        Returns ``True`` if a row was updated, ``False`` if *id* was not found.
        """

    @abc.abstractmethod
    def delete(self, id: str) -> None:
        """Remove the subscription record for *id* (no-op if absent)."""

    @abc.abstractmethod
    def get(self, id: str) -> dict[str, Any] | None:
        """Return the subscription record for *id*, or ``None`` if not found."""

    @abc.abstractmethod
    def list(self) -> list[dict[str, Any]]:
        """Return all subscription records ordered by expiration (ascending)."""

    @abc.abstractmethod
    def due_for_renewal(self, before_iso: str) -> List[dict[str, Any]]:
        """Return subscriptions expiring at or before ``before_iso`` (UTC ISO).

        Results should be ordered by expiration ascending so the soonest-to-
        expire are renewed first.
        """

    @abc.abstractmethod
    def close(self) -> None:
        """Release any resources held by the backend (connections, file handles…).

        After ``close()`` all other methods SHOULD raise ``RuntimeError``.
        """


__all__ = ["SubscriptionBackend"]
