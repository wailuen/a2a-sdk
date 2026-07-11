"""AzureTableCommitmentStore — Azure Table Storage backend for durable commitments.

At-most-once semantics use ETag optimistic concurrency: the ``claim_due``
transition (``pending`` → ``firing``) is guarded by
``MatchConditions.IfNotModified`` on each entity's ETag, so two replicas racing
on the same row produce exactly one winner (the loser gets
``ResourceModifiedError`` and skips, mirroring SQLite's ``rowcount==1`` guard).

The terminal transitions (``mark_fired``, ``mark_failed``) are guarded the same
way: only the firer still holding the current ETag wins; a late completion
after a lease reap is a no-op.

Wiring::

    from agent_sdk.contrib.commitments.azure_table import (
        AzureTableCommitmentStore,
        create_commitment_backend,
    )

    store = AzureTableCommitmentStore(
        connection_string=settings.azure_storage_connection_string.get_secret_value(),
        table_prefix="agent",
    )
    store.initialize()

Or use the factory::

    store = create_commitment_backend(settings)  # auto-selects SQLite when no Azure config

**Secrets hygiene:** same rules as CommitmentStore — args with a secret-named
key are refused; auth_context is redacted before persistence; last_error is
bearer-scrubbed and truncated.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ...common.iso8601 import iso_utc
from ...common.redact import redact, redact_value
from .backend import Commitment, CommitmentBackend
from .store import (
    STATUS_CANCELLED,
    STATUS_FAILED,
    STATUS_FIRED,
    STATUS_FIRING,
    STATUS_PENDING,
    _MAX_REASON_LEN,
    _dump_json,
    _has_secret_key,
    _normalize_fire_at,
    _utcnow_iso,
)
from ..azure_utils import require_azure_packages


class AzureTableCommitmentStore(CommitmentBackend):
    """Azure Table Storage backed durable commitment store.

    Constructor accepts EITHER a ``connection_string`` (shared-key / SAS) OR an
    ``account_name`` (managed-identity / DefaultAzureCredential).  Setting both
    is an error (ambiguous auth — the caller's settings validator should have
    caught this already, but we enforce it here too).

    ``table_prefix`` controls the table name: ``{prefix}commitments`` (default
    ``agentcommitments``).
    """

    PARTITION_KEY = "commitments"

    def __init__(
        self,
        connection_string: str | None = None,
        account_name: str | None = None,
        table_prefix: str = "agent",
    ) -> None:
        require_azure_packages()
        if connection_string and account_name:
            raise ValueError(
                "Provide either connection_string or account_name, not both."
            )
        if not connection_string and not account_name:
            raise ValueError(
                "Provide either connection_string or account_name."
            )

        from azure.data.tables import TableServiceClient

        if connection_string:
            self._service = TableServiceClient.from_connection_string(connection_string)
        else:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
            endpoint = f"https://{account_name}.table.core.windows.net"
            self._service = TableServiceClient(endpoint=endpoint, credential=credential)

        self._table_name = f"{table_prefix}commitments"
        self._table = self._service.get_table_client(self._table_name)

    # ── lifecycle ──

    def initialize(self) -> None:
        """Create the Azure Table if it does not exist. Idempotent."""
        try:
            self._service.create_table(self._table_name)
        except Exception as exc:
            # Table already exists → not an error; re-raise anything else.
            exc_name = type(exc).__name__
            if "TableAlreadyExists" not in exc_name and "ResourceExistsError" not in exc_name:
                raise

    def close(self) -> None:
        """No-op: TableServiceClient does not require explicit release."""

    # ── write ──

    def add(
        self,
        *,
        tool: str,
        args: dict[str, Any],
        fire_at: str,
        identity_binding: str | None = None,
        auth_context: dict[str, Any] | None = None,
    ) -> str:
        """Insert a pending commitment and return its generated id.

        Validation mirrors CommitmentStore.add(): tool non-empty, args is a
        dict, identity_binding non-blank, no secret-named key in args,
        fire_at parseable ISO 8601, args JSON-serializable and ≤ 64 KiB,
        auth_context secret-values redacted before persisting.
        """
        if not tool or not isinstance(tool, str):
            raise ValueError("tool must be a non-empty registered tool name")
        if not isinstance(args, dict):
            raise ValueError("args must be a dict")
        if identity_binding is not None and not (
            isinstance(identity_binding, str) and identity_binding.strip()
        ):
            raise ValueError("identity_binding must be a non-empty owner key or None")
        if _has_secret_key(args):
            raise ValueError(
                "args must not contain a secret-named key; persist a re-mintable "
                "reference in auth_context and re-establish credentials in fire_auth"
            )
        norm_fire_at = _normalize_fire_at(fire_at)
        args_json = _dump_json(args, "args")
        auth_json = _dump_json(redact(auth_context or {}), "auth_context")
        commitment_id = str(uuid.uuid4())
        created_at = _utcnow_iso()

        entity: dict[str, Any] = {
            "PartitionKey": self.PARTITION_KEY,
            "RowKey": commitment_id,
            "tool": tool,
            "args_json": args_json,
            "fire_at": norm_fire_at,
            "status": STATUS_PENDING,
            "created_at": created_at,
            "identity_binding": identity_binding,
            "auth_context_json": auth_json,
            "claimed_at": None,
            "attempts": 0,
            "last_error": None,
        }
        self._table.create_entity(entity)
        return commitment_id

    def claim_due(self, now: str | None = None, limit: int = 50) -> list[Commitment]:
        """Atomically claim up to ``limit`` due pending commitments.

        Each row is updated ``pending`` → ``firing`` under its ETag; only the
        caller that wins the ``IfNotModified`` check gets the row — two replicas
        racing on the same entity produce exactly one winner.
        """
        from azure.core.exceptions import ResourceModifiedError
        from azure.core import MatchConditions
        from azure.data.tables import UpdateMode

        now = now or _utcnow_iso()
        claimed_at = _utcnow_iso()
        filter_expr = (
            "PartitionKey eq @partition_key"
            " and status eq @status"
            " and fire_at le @now"
        )
        candidates = list(
            self._table.query_entities(
                filter_expr,
                parameters={"partition_key": self.PARTITION_KEY, "status": STATUS_PENDING, "now": now},
                results_per_page=limit,
            )
        )[:limit]

        claimed = []
        for entity in candidates:
            etag = self._get_etag(entity)
            entity["status"] = STATUS_FIRING
            entity["claimed_at"] = claimed_at
            entity["attempts"] = int(entity.get("attempts", 0)) + 1
            try:
                self._table.update_entity(
                    entity,
                    mode=UpdateMode.REPLACE,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                )
                claimed.append(entity)
            except ResourceModifiedError:
                pass  # another replica won this row
        return [self._to_commitment(e) for e in claimed]

    def mark_fired(self, commitment_id: str) -> bool:
        """Transition a ``firing`` row to ``fired``; returns True iff this call won."""
        return self._set_terminal(commitment_id, STATUS_FIRED, None)

    def mark_failed(self, commitment_id: str, reason: str | None) -> bool:
        """Transition a ``firing`` row to ``failed``; bearer-scrubs and truncates
        ``reason``; returns True iff this call won the transition."""
        safe = redact_value(str(reason or ""))[:_MAX_REASON_LEN]
        return self._set_terminal(commitment_id, STATUS_FAILED, safe)

    def cancel(
        self, commitment_id: str, *, identity_binding: str | None = None
    ) -> bool:
        """Cancel a still-pending commitment.

        When ``identity_binding`` is supplied only a row with the matching
        binding is cancelled; a mismatch is a silent no-op (existence not
        leaked). ``identity_binding=None`` is the admin/unbound path.
        Returns True iff a row transitioned to cancelled.
        """
        from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
        from azure.core import MatchConditions
        from azure.data.tables import UpdateMode

        entity = self._get_entity(commitment_id)
        if entity is None:
            return False
        if entity.get("status") != STATUS_PENDING:
            return False
        if identity_binding is not None and entity.get("identity_binding") != identity_binding:
            return False

        etag = self._get_etag(entity)
        entity["status"] = STATUS_CANCELLED
        try:
            self._table.update_entity(
                entity,
                mode=UpdateMode.REPLACE,
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
            return True
        except (ResourceModifiedError, ResourceNotFoundError):
            return False

    def reap_stale_firing(self, lease_seconds: int) -> int:
        """Move rows stuck in ``firing`` beyond ``lease_seconds`` to ``failed``.

        ETag-guards each update; ``ResourceModifiedError`` is benign (another
        replica already transitioned it). Returns the count reaped by this call.
        """
        from azure.core.exceptions import ResourceModifiedError
        from azure.core import MatchConditions
        from azure.data.tables import UpdateMode

        cutoff = iso_utc(datetime.now(timezone.utc) - timedelta(seconds=max(0, lease_seconds)))

        filter_expr = (
            "PartitionKey eq @partition_key"
            " and status eq @status"
            " and claimed_at le @cutoff"
        )
        candidates = list(
            self._table.query_entities(
                filter_expr,
                parameters={"partition_key": self.PARTITION_KEY, "status": STATUS_FIRING, "cutoff": cutoff},
            )
        )

        count = 0
        for entity in candidates:
            etag = self._get_etag(entity)
            entity["status"] = STATUS_FAILED
            entity["last_error"] = "lease_expired"
            try:
                self._table.update_entity(
                    entity,
                    mode=UpdateMode.REPLACE,
                    etag=etag,
                    match_condition=MatchConditions.IfNotModified,
                )
                count += 1
            except ResourceModifiedError:
                pass  # another replica handled it; benign
        return count

    # ── read ──

    def get(
        self, commitment_id: str, *, identity_binding: str | None = None
    ) -> Commitment | None:
        """Identity-scoped lookup; a binding mismatch returns None (existence not
        leaked). ``identity_binding=None`` bypasses the check (admin/unbound)."""
        entity = self._get_entity(commitment_id)
        if entity is None:
            return None
        if identity_binding is not None and entity.get("identity_binding") != identity_binding:
            return None
        return self._to_commitment(entity)

    def list(
        self,
        *,
        identity_binding: str | None = None,
        status: str | None = None,
        limit: int = 100,
    ) -> list[Commitment]:
        """List commitments, newest first (by created_at), optionally scoped."""
        filters = ["PartitionKey eq @partition_key"]
        parameters: dict[str, Any] = {"partition_key": self.PARTITION_KEY}
        if identity_binding is not None:
            filters.append("identity_binding eq @identity_binding")
            parameters["identity_binding"] = identity_binding
        if status is not None:
            filters.append("status eq @status")
            parameters["status"] = status
        filter_expr = " and ".join(filters)

        entities = list(self._table.query_entities(filter_expr, parameters=parameters))
        # Sort newest first by created_at (lexicographically safe — canonical UTC Z).
        entities.sort(key=lambda e: e.get("created_at", ""), reverse=True)
        return [self._to_commitment(e) for e in entities[:limit]]

    # ── internals ──

    def _get_entity(self, commitment_id: str) -> dict[str, Any] | None:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            return self._table.get_entity(
                partition_key=self.PARTITION_KEY, row_key=commitment_id
            )
        except ResourceNotFoundError:
            return None

    @staticmethod
    def _get_etag(entity: Any) -> str:
        """Extract the ETag from an Azure Table entity (SDK may put it in
        ``metadata`` or ``_metadata`` depending on version).

        Raises ``RuntimeError`` if no ETag is found — returning the wildcard
        ``"*"`` would silently disable IfNotModified, defeating at-most-once.
        """
        meta = getattr(entity, "metadata", None) or {}
        etag = meta.get("etag")
        if not etag:
            meta2 = getattr(entity, "_metadata", None) or {}
            etag = meta2.get("etag")
        if not etag:
            raise RuntimeError(
                f"Azure Table entity has no ETag — cannot enforce at-most-once semantics: "
                f"RowKey={entity.get('RowKey', '?')!r}"
            )
        return etag

    def _set_terminal(
        self, commitment_id: str, status: str, reason: str | None
    ) -> bool:
        """Transition a ``firing`` row to a terminal status under ETag guard.

        Returns True iff this call owned the transition. Returns False if:
        - The entity does not exist.
        - The entity is not in ``firing`` state (e.g. already reaped).
        - The ETag guard fails (another caller transitioned it concurrently).
        """
        from azure.core.exceptions import ResourceModifiedError, ResourceNotFoundError
        from azure.core import MatchConditions
        from azure.data.tables import UpdateMode

        entity = self._get_entity(commitment_id)
        if entity is None:
            return False
        if entity.get("status") != STATUS_FIRING:
            return False

        etag = self._get_etag(entity)
        entity["status"] = status
        entity["last_error"] = reason
        try:
            self._table.update_entity(
                entity,
                mode=UpdateMode.REPLACE,
                etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
            return True
        except (ResourceModifiedError, ResourceNotFoundError):
            return False

    @staticmethod
    def _to_commitment(entity: Any) -> Commitment:
        """Convert an Azure Table entity dict to a Commitment dataclass."""
        return Commitment(
            id=entity["RowKey"],
            tool=entity["tool"],
            args=json.loads(entity.get("args_json", "{}")),
            fire_at=entity["fire_at"],
            status=entity["status"],
            created_at=entity["created_at"],
            identity_binding=entity.get("identity_binding"),
            auth_context=json.loads(entity.get("auth_context_json") or "{}"),
            attempts=int(entity.get("attempts", 0)),
        )


def create_commitment_backend(settings: Any) -> CommitmentBackend:
    """Factory: return an AzureTableCommitmentStore when Azure credentials are
    configured in ``settings``, otherwise fall back to SQLite CommitmentStore.

    Checks ``settings.azure_storage_connection_string`` first, then
    ``settings.azure_storage_account_name``; falls back to SQLite at
    ``{settings.data_dir}/commitments.db`` (or ``./data/commitments.db``).
    """
    conn_str = getattr(settings, "azure_storage_connection_string", None)
    if conn_str is not None:
        # SecretStr in prod; accept plain str for testing
        secret_val = (
            conn_str.get_secret_value()
            if hasattr(conn_str, "get_secret_value")
            else str(conn_str)
        )
        table_prefix = getattr(settings, "azure_storage_table_prefix", "agent")
        return AzureTableCommitmentStore(
            connection_string=secret_val,
            table_prefix=table_prefix,
        )

    account_name = getattr(settings, "azure_storage_account_name", None)
    if account_name is not None:
        table_prefix = getattr(settings, "azure_storage_table_prefix", "agent")
        return AzureTableCommitmentStore(
            account_name=account_name,
            table_prefix=table_prefix,
        )

    from .store import CommitmentStore
    from pathlib import Path

    data_dir = getattr(settings, "data_dir", "./data")
    return CommitmentStore(Path(data_dir) / "commitments.db")


__all__ = ["AzureTableCommitmentStore", "create_commitment_backend"]
