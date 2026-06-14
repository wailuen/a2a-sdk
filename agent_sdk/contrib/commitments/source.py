"""CommitmentsSource — the tool-facing scheduling API (DESIGN §9).

A tool can only receive SDK-instantiated ``SourceAdapter`` instances (by typed
keyword param) or its own pydantic input — there is no ambient handle to the
commitment store. So scheduling is exposed as a source: register
``CommitmentsSource`` like any other, and a tool annotates it to schedule, list,
or cancel durable commitments::

    from agent_sdk.contrib.commitments import (
        CommitmentsSource, commitments_lifespan,
    )

    agent.register_source(CommitmentsSource)
    agent = Agent(..., lifespan_extras=[commitments_lifespan()])

    @tools.tool()
    async def remind_me(inp: ReminderInput, *, commitments: CommitmentsSource) -> dict:
        cid = await commitments.schedule(
            tool="send_reminder",
            args={"text": inp.text},
            fire_at=inp.when,                 # ISO 8601; normalized to UTC
            identity_binding=inp.user_key,    # integrator-supplied (Approach 2)
            auth_context={"home_account_id": inp.home_account_id},
        )
        return {"scheduled": True, "commitment_id": cid}

This is a non-HTTP source: it never makes outbound requests, so ``allowed_hosts``
stays empty and the inherited HTTP client is never created. It owns the
:class:`CommitmentStore`; the :func:`commitments_lifespan` executor reuses that
same store so writes and polls share one connection.

**Identity binding (Approach 2 — integrator hook).** ``commitments`` does not
read the SDK ``Identity`` (no core change). The caller supplies
``identity_binding`` — an opaque, non-secret key identifying the owner — which is
persisted and used to scope ``cancel``/``get``/``list``. For the OBO case the
integrator passes the ``home_account_id`` it captured from the *live* exchange
(never from LLM/user args), so a commitment created by one user cannot later
re-mint for another (the executor's ``fire_auth`` re-mints from this persisted
reference). See the carried-forward OBO contract in the module docstring.
"""

from __future__ import annotations

from typing import Any

from ...models.errors import AgentError, ErrorCategory
from ...sources import CredentialResolver, SourceAdapter
from .backend import CommitmentBackend
from .store import Commitment, CommitmentStore


class CommitmentsSource(SourceAdapter):
    """Tool-facing durable-scheduling source backed by :class:`CommitmentStore`."""

    source_name = "commitments"
    _no_http = True  # non-HTTP adapter; never makes outbound requests (SI-7 opt-out)
    # SSRF host-pin list stays empty and the inherited httpx client is never instantiated.

    def __init__(
        self,
        settings: Any,
        credential_resolver: CredentialResolver,
        *,
        db_path: str | None = None,
        require_future: bool = True,
    ) -> None:
        super().__init__(settings, credential_resolver)
        from pathlib import Path

        path = db_path or str(Path(settings.data_dir) / "commitments.db")
        self.store: CommitmentBackend = CommitmentStore(path)
        self.store.initialize()
        self._require_future = require_future

    async def schedule(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        fire_at: str,
        identity_binding: str | None = None,
        auth_context: dict[str, Any] | None = None,
    ) -> str:
        """Persist a pending commitment; return its id. Validation errors surface
        as ``AgentError(VALIDATION)`` (typed for the tool/consumer). When
        ``require_future`` (the default), a ``fire_at`` not strictly in the
        future is rejected — scheduling means the future, and a past time would
        fire on the next tick."""
        if self._require_future:
            self._reject_non_future(fire_at)
        try:
            return self.store.add(
                tool=tool,
                args=args,
                fire_at=fire_at,
                identity_binding=identity_binding,
                auth_context=auth_context,
            )
        except ValueError as exc:
            # store.add raises ValueError for bad fire_at / secret-in-args; map to
            # a typed error. The store's messages are already generic (no echo).
            raise AgentError(
                ErrorCategory.VALIDATION, str(exc), source=self.source_name
            ) from exc

    async def cancel(
        self, commitment_id: str, *, identity_binding: str | None = None
    ) -> bool:
        """Cancel a pending commitment (identity-scoped when ``identity_binding``
        is given). Returns True iff a pending row was cancelled."""
        return self.store.cancel(commitment_id, identity_binding=identity_binding)

    async def get(
        self, commitment_id: str, *, identity_binding: str | None = None
    ) -> Commitment | None:
        """Identity-scoped lookup (mismatch → None, existence not leaked)."""
        return self.store.get(commitment_id, identity_binding=identity_binding)

    async def list(
        self,
        *,
        identity_binding: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Commitment]:
        """List commitments, newest first, scoped to ``identity_binding`` when
        given and optionally filtered by ``status``."""
        return self.store.list(
            identity_binding=identity_binding, status=status, limit=limit
        )

    def _reject_non_future(self, fire_at: str) -> None:
        import datetime as _dt

        try:
            if not isinstance(fire_at, str):
                raise ValueError("fire_at must be an ISO 8601 string")
            parsed = _dt.datetime.fromisoformat(fire_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=_dt.timezone.utc)
            norm = parsed.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        except ValueError as exc:
            raise AgentError(
                ErrorCategory.VALIDATION,
                "fire_at must be a valid ISO 8601 timestamp",
                source=self.source_name,
            ) from exc
        fire_dt = _dt.datetime.strptime(norm, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=_dt.timezone.utc
        )
        if fire_dt <= _dt.datetime.now(_dt.timezone.utc):
            raise AgentError(
                ErrorCategory.VALIDATION,
                "fire_at must be in the future",
                source=self.source_name,
            )

    async def aclose(self) -> None:
        await super().aclose()
        self.store.close()


__all__ = ["CommitmentsSource"]
