"""Background commitment executor + lifespan wiring (DESIGN §9).

:class:`CommitmentExecutor` polls a :class:`CommitmentStore` every
``poll_interval`` seconds, atomically claims due commitments, and fires each by
re-invoking its registered tool through the SDK's own tool registry
(``registry.get(name).invoke_any(args, adapters)`` — RT-002/LRN-116: the same
is_generator-aware dispatch the agent loop and MCP's ``tools/call`` use, so a
Tier-1 ``long_running=True`` async-generator tool fires here too instead of
TypeError-ing inside a bare ``invoke()``). Each fire is independent: one tool
failing never blocks the others, and a failure is recorded as a short
non-secret reason, never a raw message.

**Credential-agnostic by design (the integrator hook).** The executor fires
tools with NO request context — there is no inbound assertion, no per-request
auth. A tool that needs live credentials at fire time (e.g. an OBO Graph call)
cannot re-read the original token. So the executor takes an optional
``fire_auth`` hook: an async context manager built per commitment that
re-establishes whatever auth the tool needs (typically by re-minting from a
persisted, re-mintable reference such as an OBO ``home_account_id`` carried in
``commitment.auth_context``). This keeps ``commitments`` free of any OBO/Graph
import — the bridge is supplied by the integrator at wiring time.

``commitments_lifespan`` is the wiring helper: pass it to ``Agent(lifespan_extras
=[...])``. It starts the poller on app startup and cancels it on shutdown
(graceful shutdown, DESIGN §9). A commitment whose fire is interrupted by
shutdown is left ``firing`` and reaped to ``failed`` on next startup — it is
never silently re-run (a side-effecting tool must not double-act).

**Secrets hygiene:** the executor logs only commitment ids, tool names, error
categories, and exception *type* names — never args, auth_context, or any error
message body.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Callable

from ...agent.registry import ToolInputValidationError
from ...common.redact import frame_locations
from ...models.errors import AgentError
from .backend import CommitmentBackend
from .store import Commitment, CommitmentStore

# GH-135/RT-006: stable persisted reason for "the stored tool_call arguments no
# longer satisfy the tool's input model". Explicit rather than
# type(exc).__name__ so the string written to the commitments DB is part of the
# contract and cannot silently change when an exception class is renamed — which
# is exactly what GH-135 did by introducing ToolInputValidationError between the
# ValidationError raise site and this catch-all.
INVALID_TOOL_INPUT_REASON = "invalid_tool_input"

if TYPE_CHECKING:  # avoid importing FastAPI / registry types at module import
    from fastapi import FastAPI

logger = logging.getLogger("agent_sdk.contrib.commitments")

# A per-commitment auth-context factory: given the claimed commitment, return an
# async context manager entered around the tool invocation.
FireAuth = Callable[[Commitment], AbstractAsyncContextManager[None]]


class CommitmentExecutor:
    """Polls a :class:`CommitmentStore` and fires due commitments (DESIGN §9)."""

    def __init__(
        self,
        store: CommitmentBackend,
        registry: Any,  # agent.registry.ToolRegistry (duck-typed: .get(name))
        adapters: dict[type, Any],
        *,
        poll_interval: float = 30.0,
        lease_seconds: int = 300,
        claim_limit: int = 50,
        fire_auth: FireAuth | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._adapters = adapters
        self._poll_interval = max(1.0, float(poll_interval))
        self._lease_seconds = max(1, int(lease_seconds))
        self._claim_limit = max(1, int(claim_limit))
        self._fire_auth = fire_auth

    async def run(self) -> None:
        """Run the poll loop until cancelled. Reaps stale ``firing`` rows once at
        startup (crash recovery), then ticks every ``poll_interval`` seconds.
        Sleeps before the first tick so a cold start does not fire before the
        registry/adapters are warm."""
        self._safe_reap()  # guarded: a locked DB at startup must not kill the poller
        try:
            while True:
                await asyncio.sleep(self._poll_interval)
                try:
                    await self.tick_once()
                except asyncio.CancelledError:
                    raise
                except Exception as exc:  # a tick must never kill the loop
                    logger.error("commitments tick error_type=%s", type(exc).__name__)
        except asyncio.CancelledError:
            return

    def _safe_reap(self) -> None:
        """Reap stale ``firing`` rows, swallowing a transient store error (e.g. a
        cross-process ``database is locked`` past the busy-timeout) so a single
        bad reap can never kill the poller — the next tick retries."""
        try:
            self._store.reap_stale_firing(self._lease_seconds)
        except Exception as exc:
            logger.error("commitments reap error_type=%s", type(exc).__name__)

    async def tick_once(self) -> int:
        """Reap stale rows, claim all currently-due commitments, and fire each.
        Returns the number fired-or-failed this tick. Exposed for tests and for
        an integrator that wants to drive ticks manually."""
        self._safe_reap()
        due = self._store.claim_due(limit=self._claim_limit)
        for commitment in due:
            await self._fire(commitment)
        return len(due)

    async def _fire(self, commitment: Commitment) -> None:
        entry = self._registry.get(commitment.tool)
        if entry is None:
            self._store.mark_failed(commitment.id, "unknown_tool")
            logger.error(
                "commitment %s: tool %r not registered", commitment.id, commitment.tool
            )
            return
        try:
            # RT-002/LRN-116: invoke_any() branches on decl.is_generator so a
            # committed Tier-1 long_running=True async-generator tool is
            # drained (mirroring routes/mcp.py:380-390) instead of TypeErroring
            # inside invoke() and being permanently marked failed.
            if self._fire_auth is not None:
                async with self._fire_auth(commitment):
                    await entry.invoke_any(commitment.args, self._adapters)
            else:
                await entry.invoke_any(commitment.args, self._adapters)
        except asyncio.CancelledError:
            # Shutdown mid-fire: leave the row 'firing' for the reaper. Do NOT
            # mark fired/failed and do NOT re-run — at-most-once for side effects.
            raise
        except AgentError as exc:
            self._store.mark_failed(commitment.id, exc.category.value)
            logger.error(
                "commitment %s failed category=%s", commitment.id, exc.category.value
            )
            return
        except ToolInputValidationError:
            # GH-135/RT-006 (C-012 cross-surface parity): the executor is the
            # FOURTH tool-dispatch surface, alongside agent/loop.py, routes/mcp.py
            # and routes/admin.py — a tool-body ValidationError must classify
            # identically on all four. Without this branch the generic catch-all
            # below persisted type(exc).__name__, so the stored reason silently
            # changed from "ValidationError" to "ToolInputValidationError" on
            # upgrade, and a caller-input coercion failure stayed
            # indistinguishable from a body failure. Never log/store the
            # exception's payload: .validation_error renders the rejected value
            # (SI-2).
            self._store.mark_failed(commitment.id, INVALID_TOOL_INPUT_REASON)
            logger.error(
                "commitment %s failed reason=%s tool=%s",
                commitment.id,
                INVALID_TOOL_INPUT_REASON,
                commitment.tool,
            )
            return
        except Exception as exc:
            # Never log/store the message — it can embed args or upstream bodies.
            # frame_locations() (common/redact.py, SI-2-safe: filename/lineno
            # only, never the source line) keeps this FOURTH tool-dispatch
            # surface at the C-012 cross-surface parity loop.py/mcp.py/admin.py
            # already carry (LRN-044) — a bare error_type=%s here was
            # undiagnosable when a genuine tool-body bug fired in the
            # background with no caller observing the failure.
            #
            # Persisting type(exc).__name__ as last_error (rather than logging
            # it only) is the RT-012 carve-out in LRN-044's Check: last_error
            # is a durable, operator-facing DB column, never a caller/model-
            # facing error body — Commitment (backend.py) has no last_error
            # field, so CommitmentsSource.get()/.list() never hand it to a
            # tool. If that ever changes, switch this to a stable enumerated
            # reason alongside INVALID_TOOL_INPUT_REASON.
            self._store.mark_failed(commitment.id, type(exc).__name__)
            logger.error(
                "commitment %s failed error_type=%s frames=%s",
                commitment.id,
                type(exc).__name__,
                frame_locations(exc),
            )
            return
        if self._store.mark_fired(commitment.id):
            logger.info("commitment %s fired tool=%s", commitment.id, commitment.tool)
        else:
            # The row left 'firing' before we finished (e.g. reaped after a lease
            # overrun). The side effect already ran — record, do NOT retry.
            logger.warning(
                "commitment %s completed after its row left 'firing' (no retry)",
                commitment.id,
            )


def commitments_lifespan(
    *,
    db_path: str | Path | None = None,
    poll_interval: float = 30.0,
    lease_seconds: int = 300,
    claim_limit: int = 50,
    fire_auth: FireAuth | None = None,
) -> Callable[["FastAPI"], AbstractAsyncContextManager[None]]:
    """Build a lifespan extra that runs a :class:`CommitmentExecutor` for the
    app's lifetime. Wire it via ``Agent(lifespan_extras=[commitments_lifespan(...)])``.

    If a :class:`~agent_sdk.contrib.commitments.source.CommitmentsSource` is
    registered, the executor reuses *its* store so tool writes and executor polls
    share one connection; otherwise it stands up its own store at ``db_path``
    (default ``{data_dir}/commitments.db``) for executor-only deployments.

    The executor task is cancelled and awaited on shutdown (graceful shutdown,
    DESIGN §9)."""

    @asynccontextmanager
    async def _lifespan(app: "FastAPI") -> AsyncIterator[None]:
        from .source import CommitmentsSource  # local import: avoid import cycle

        settings = app.state.settings
        source = next(
            (
                a
                for a in app.state.adapters.values()
                if isinstance(a, CommitmentsSource)
            ),
            None,
        )
        owns_store = source is None
        if source is not None:
            store = source.store
        elif db_path is not None:
            # Explicit path: backward-compat SQLite
            store = CommitmentStore(db_path)
            store.initialize()
        else:
            # Auto-detect: use Azure when configured, else SQLite
            from agent_sdk.contrib.commitments.azure_table import create_commitment_backend

            store = create_commitment_backend(settings)
            store.initialize()
        app.state.commitment_store = store

        executor = CommitmentExecutor(
            store,
            app.state.registry,
            app.state.adapters,
            poll_interval=poll_interval,
            lease_seconds=lease_seconds,
            claim_limit=claim_limit,
            fire_auth=fire_auth,
        )
        task = asyncio.create_task(executor.run(), name="commitment-executor")
        try:
            yield
        finally:
            task.cancel()
            try:
                await task
            except BaseException:
                pass
            if owns_store:  # a source-owned store is closed by source.aclose()
                store.close()

    return _lifespan


__all__ = ["CommitmentExecutor", "commitments_lifespan", "FireAuth"]
