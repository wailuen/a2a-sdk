"""commitments — durable scheduled tool execution (DESIGN.md §9).

EXPERIMENTAL (DESIGN.md §4.0): provisional until the m365 port validates it; may
change in minor releases with a CHANGELOG notice.

A *commitment* is a registered tool + arguments + a future UTC ``fire_at``,
persisted in SQLite so it survives restarts. Three pieces:

- :class:`CommitmentStore` — durable SQLite store (stdlib ``sqlite3``, house
  style). At-most-once claim (``pending`` → ``firing`` guarded transition), so a
  side-effecting tool is never double-fired; canonical-UTC ``fire_at`` so the
  ``fire_at <= now`` comparison is correct; refuses secrets in args.
- :class:`CommitmentExecutor` + :func:`commitments_lifespan` — the background
  poller, wired as a lifespan extra with graceful shutdown.
- :class:`CommitmentsSource` — the tool-facing scheduling API (a non-HTTP
  ``SourceAdapter`` a tool annotates to schedule/list/cancel).

Wiring (the integrator owns this; the m365 port is the first consumer)::

    from agent_sdk.contrib.commitments import (
        CommitmentsSource, commitments_lifespan,
    )

    agent.register_source(CommitmentsSource)
    agent = Agent(..., lifespan_extras=[commitments_lifespan(poll_interval=30)])

**Fire-time credentials — the ``fire_auth`` hook.** Commitments fire with NO
request context (no inbound assertion, no per-request auth). A tool needing live
credentials at fire time must re-mint them. ``commitments`` stays credential-
agnostic: pass ``commitments_lifespan(fire_auth=...)`` — an async-context-manager
factory entered around each tool invocation — and re-establish auth there from
the commitment's persisted, re-mintable ``auth_context`` (NOT a stored token).

**Carried-forward OBO contract (SECURITY).** ``OboExchanger.token_for_account``
mints a delegated token for a ``home_account_id`` with no fresh assertion — a
bearer-grade capability. When bridging OBO into commitments via ``fire_auth``:
the scheduling tool MUST capture ``home_account_id`` from the *live* OBO exchange
(never from LLM/user-supplied args), persist it as the commitment's
``identity_binding`` / ``auth_context``, and the ``fire_auth`` hook MUST re-mint
ONLY for that persisted value. This binds a commitment to its creator's identity
so user A's commitment can never re-mint a token for user B — the contract
``commitments`` exists to honor but cannot itself enforce.

**Secrets hygiene:** args with a secret-named key are refused at ``schedule``;
``auth_context`` secret-named values are masked before persistence; the executor
logs only ids, tool names, error categories, and exception type names.

**Operational notes (known, deliberate trade-offs — not defects):**

- *One poller per store.* The at-most-once claim and the guarded terminal
  transition are correct across processes, but the lease-based reaper can move a
  *still-running* fire to ``failed`` if a tool outruns ``lease_seconds`` — set the
  lease above the slowest tool's runtime, and prefer a single poller per DB.
- *Synchronous SQLite shares the event loop.* The store uses one stdlib
  ``sqlite3`` connection under a ``threading.Lock`` (the house pattern, matching
  ``EncryptedSqliteStore``), called directly from async code. A slow or
  cross-process-contended query blocks the loop for up to ``busy_timeout`` (5 s).
  Keep the store off the request hot path; this is an SDK-wide characteristic,
  not specific to commitments.
- *``identity_binding=None`` is the unscoped admin view.* A tool that forgets to
  thread the owner key gets the admin/unbound scope by default, not safe-denied
  (locked Approach 2). Empty/blank bindings are rejected; ``None`` is the explicit
  admin path — pass a real owner key for per-user scoping.
"""

from __future__ import annotations

from .azure_table import AzureTableCommitmentStore, create_commitment_backend
from .backend import CommitmentBackend
from .executor import CommitmentExecutor, FireAuth, commitments_lifespan
from .source import CommitmentsSource
from .store import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_FIRED,
    STATUS_FIRING,
    STATUS_PENDING,
    Commitment,
    CommitmentStore,
)

__all__ = [
    # backend ABC
    "CommitmentBackend",
    # SQLite store
    "CommitmentStore",
    "Commitment",
    "STATUS_PENDING",
    "STATUS_FIRING",
    "STATUS_FIRED",
    "STATUS_FAILED",
    "STATUS_CANCELLED",
    # Azure Table store + factory
    "AzureTableCommitmentStore",
    "create_commitment_backend",
    # executor / wiring
    "CommitmentExecutor",
    "commitments_lifespan",
    "FireAuth",
    # source
    "CommitmentsSource",
]
