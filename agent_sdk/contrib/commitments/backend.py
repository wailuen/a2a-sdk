"""CommitmentBackend — abstract base class for commitment storage (DESIGN §9).

Defines the interface that :class:`~agent_sdk.contrib.commitments.store.CommitmentStore`
and any alternative backends must implement. Decoupling the interface from the
SQLite implementation lets :class:`~agent_sdk.contrib.commitments.executor.CommitmentExecutor`
and :class:`~agent_sdk.contrib.commitments.source.CommitmentsSource` be wired with
any conforming backend (in-memory for testing, remote-backed stores, etc.) without
touching application code.

Implementors must satisfy all at-most-once and identity-binding contracts described
in the store module docstring; the ABC enforces only the signature contract.
"""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True, slots=True)
class Commitment:
    """A parsed commitment row. ``args`` / ``auth_context`` are JSON-decoded.

    Defined here (rather than in ``store``) so ``CommitmentBackend`` can reference
    it without creating a circular import between ``backend`` and ``store``.
    """

    id: str
    tool: str
    args: dict[str, Any]
    fire_at: str
    status: str
    created_at: str
    identity_binding: str | None = None
    auth_context: dict[str, Any] = field(default_factory=dict)
    attempts: int = 0


class CommitmentBackend(abc.ABC):
    """Abstract interface for durable commitment storage (DESIGN §9).

    Every public method of :class:`~agent_sdk.contrib.commitments.store.CommitmentStore`
    is declared here as an abstract method so alternative backend implementations
    are immediately checked at class definition time.
    """

    # ── write ──

    @abc.abstractmethod
    def add(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        fire_at: str,
        identity_binding: str | None = None,
        auth_context: dict[str, Any] | None = None,
    ) -> str:
        """Insert a pending commitment and return its generated id."""

    @abc.abstractmethod
    def claim_due(self, now: str | None = None, limit: int = 50) -> list[Commitment]:
        """Atomically claim up to ``limit`` due pending commitments."""

    @abc.abstractmethod
    def mark_fired(self, commitment_id: str) -> bool:
        """Complete a claimed commitment as ``fired``; returns True iff this call
        owned the transition."""

    @abc.abstractmethod
    def mark_failed(self, commitment_id: str, reason: str | None) -> bool:
        """Mark a claimed commitment ``failed``; returns True iff this call owned
        the transition. ``reason`` may be ``None`` when no error detail is
        available; implementations MUST treat ``None`` identically to an empty
        string."""

    @abc.abstractmethod
    def cancel(
        self, commitment_id: str, *, identity_binding: str | None = None
    ) -> bool:
        """Cancel a still-pending commitment; returns True iff a row transitioned
        to cancelled."""

    @abc.abstractmethod
    def reap_stale_firing(self, lease_seconds: int) -> int:
        """Move rows stuck in ``firing`` beyond ``lease_seconds`` to ``failed``;
        returns the count reaped."""

    # ── read ──

    @abc.abstractmethod
    def get(
        self, commitment_id: str, *, identity_binding: str | None = None
    ) -> Commitment | None:
        """Identity-scoped lookup; mismatch returns None (existence not leaked)."""

    @abc.abstractmethod
    def list(
        self,
        *,
        identity_binding: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Commitment]:
        """List commitments, newest first, optionally scoped and filtered."""

    # ── lifecycle ──

    @abc.abstractmethod
    def initialize(self) -> None:
        """Create / migrate any schema or connection resources.

        Called once at startup before any other method.
        """

    @abc.abstractmethod
    def close(self) -> None:
        """Release backend resources. Idempotent.

        After ``close()`` is called, all other methods SHOULD raise
        ``RuntimeError``.
        """


__all__ = ["Commitment", "CommitmentBackend"]
