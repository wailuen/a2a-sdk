"""AzureTableSubscriptionStore — Azure Table Storage backend for Graph subscriptions.

Implements :class:`~agent_sdk.contrib.webhooks.backend.SubscriptionBackend` using
Azure Table Storage (azure-data-tables). Use
:func:`create_subscription_backend` to select the correct backend based on
:class:`~agent_sdk.config.BaseAgentSettings` values.

Install the optional extra before use::

    pip install agent-sdk[azure]

Entity layout::

    PartitionKey  = "subscriptions"
    RowKey        = <subscription_id GUID>
    resource          TEXT
    change_type       TEXT
    notification_url  TEXT
    lifecycle_url     TEXT | None
    expiration        TEXT  (ISO 8601 UTC)
    client_state_ref  TEXT
    created_at        TEXT  (ISO 8601 UTC)
    extra_json        TEXT  (JSON, default '{}')

Security note: the ``clientState`` secret is NEVER written to Azure Table
Storage. Only the non-secret ``client_state_ref`` label is persisted.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, List

from ...common.iso8601 import iso_utc
from ...models.errors import AgentError, ErrorCategory
from ..azure_utils import require_azure_packages
from .backend import SubscriptionBackend

_PARTITION_KEY = "subscriptions"
_MAX_EXTRA_BYTES = 16 * 1024


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _iso(dt: datetime) -> str:
    return iso_utc(dt)


class AzureTableSubscriptionStore(SubscriptionBackend):
    """Azure Table Storage backend for Graph webhook subscription records.

    Accepts EITHER a ``connection_string`` (shared-key / SAS) or an
    ``account_name`` (uses :class:`~azure.identity.DefaultAzureCredential`
    for managed-identity / workload-identity auth). Setting both is rejected
    by :class:`~agent_sdk.config.BaseAgentSettings` long before reaching here.

    The table name is ``{table_prefix}subscriptions`` (e.g. the default
    ``"agent"`` prefix yields ``"agentsubscriptions"``).

    All upserts use ``UpdateMode.MERGE`` so a partial update (e.g.
    ``set_expiration``) does not wipe unrelated columns.
    """

    def __init__(
        self,
        connection_string: str | None = None,
        account_name: str | None = None,
        table_prefix: str = "agent",
    ) -> None:
        require_azure_packages()
        if connection_string and account_name:
            raise ValueError(
                "Provide either connection_string or account_name, not both"
            )
        if not connection_string and not account_name:
            raise ValueError(
                "Either connection_string or account_name is required"
            )
        self._table_name = f"{table_prefix}subscriptions"
        self._client = self._build_client(connection_string, account_name)

    def _build_client(self, connection_string: str | None, account_name: str | None):
        from azure.data.tables import TableServiceClient  # type: ignore[import]

        if connection_string:
            service = TableServiceClient.from_connection_string(connection_string)
        else:
            from azure.identity import DefaultAzureCredential  # type: ignore[import]
            credential = DefaultAzureCredential()
            service = TableServiceClient(
                endpoint=f"https://{account_name}.table.core.windows.net",
                credential=credential,
            )
        return service.get_table_client(self._table_name)

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def initialize(self) -> None:
        """Create the table if it does not already exist."""
        try:
            self._client.create_table()
        except Exception:
            # Table already exists — swallow the conflict error.
            pass

    def close(self) -> None:
        """No-op: azure-data-tables uses stateless HTTP; nothing to release."""

    # ── writes ─────────────────────────────────────────────────────────────────

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
        """Insert or merge a subscription entity.

        Raises :class:`~agent_sdk.models.errors.AgentError` (VALIDATION) if
        the serialised ``extra`` dict exceeds 16 KB.
        """
        extra_json = json.dumps(extra or {})
        if len(extra_json.encode("utf-8")) > _MAX_EXTRA_BYTES:
            raise AgentError(ErrorCategory.VALIDATION, "extra exceeds size limit")

        from azure.data.tables import UpdateMode  # type: ignore[import]

        entity = {
            "PartitionKey": _PARTITION_KEY,
            "RowKey": id,
            "resource": resource,
            "change_type": change_type,
            "notification_url": notification_url,
            "lifecycle_url": lifecycle_url,
            "expiration": expiration,
            "client_state_ref": client_state_ref,
            "created_at": _iso(_utcnow()),
            "extra_json": extra_json,
        }
        self._client.upsert_entity(entity=entity, mode=UpdateMode.MERGE)

    def set_expiration(self, id: str, expiration: str) -> bool:
        """Update expiration for *id*.

        Returns ``True`` if the entity existed, ``False`` otherwise.
        """
        from azure.core.exceptions import ResourceNotFoundError  # type: ignore[import]
        from azure.data.tables import UpdateMode  # type: ignore[import]

        try:
            entity = self._client.get_entity(
                partition_key=_PARTITION_KEY, row_key=id
            )
        except ResourceNotFoundError:
            return False

        entity["expiration"] = expiration
        self._client.upsert_entity(entity=entity, mode=UpdateMode.MERGE)
        return True

    def delete(self, id: str) -> None:
        """Delete the subscription entity for *id* (no-op if absent)."""
        from azure.core.exceptions import ResourceNotFoundError  # type: ignore[import]

        try:
            self._client.delete_entity(partition_key=_PARTITION_KEY, row_key=id)
        except ResourceNotFoundError:
            pass

    # ── reads ──────────────────────────────────────────────────────────────────

    def get(self, id: str) -> dict[str, Any] | None:
        """Return the subscription record for *id*, or ``None`` if not found."""
        from azure.core.exceptions import ResourceNotFoundError  # type: ignore[import]

        try:
            entity = self._client.get_entity(
                partition_key=_PARTITION_KEY, row_key=id
            )
        except ResourceNotFoundError:
            return None
        return self._row(entity)

    def list(self) -> list[dict[str, Any]]:
        """Return all subscription records ordered by expiration ascending."""
        entities = self._client.query_entities(
            f"PartitionKey eq '{_PARTITION_KEY}'"
        )
        rows = [self._row(e) for e in entities]
        rows.sort(key=lambda r: r.get("expiration", ""))
        return rows

    def due_for_renewal(self, before_iso: str) -> List[dict[str, Any]]:
        """Return subscriptions expiring at or before *before_iso* (UTC ISO)."""
        entities = self._client.query_entities(
            f"PartitionKey eq '{_PARTITION_KEY}' and expiration le '{before_iso}'"
        )
        rows = [self._row(e) for e in entities]
        rows.sort(key=lambda r: r.get("expiration", ""))
        return rows

    # ── internal ───────────────────────────────────────────────────────────────

    @staticmethod
    def _row(entity: Any) -> dict[str, Any]:
        """Deserialize an Azure Table entity into a plain subscription dict."""
        # Convert to a plain dict (azure returns a TableEntity mapping).
        d = dict(entity)
        # Azure metadata keys — remove them from the result.
        for meta_key in ("PartitionKey", "RowKey", "etag", "Timestamp",
                         "odata.etag", "odata.metadata"):
            d.pop(meta_key, None)
        # Rename RowKey → id (already popped RowKey, recover id from entity).
        if "id" not in d:
            d["id"] = entity.get("RowKey") or entity.get("rowKey", "")
        # Deserialize extra_json → extra.
        try:
            d["extra"] = json.loads(d.pop("extra_json", "{}") or "{}")
        except (ValueError, TypeError):
            d["extra"] = {}
        return d


# ── factory ────────────────────────────────────────────────────────────────────


def create_subscription_backend(settings: Any) -> SubscriptionBackend:
    """Return the appropriate :class:`SubscriptionBackend` from *settings*.

    Priority:
    1. ``azure_storage_connection_string`` → :class:`AzureTableSubscriptionStore`
    2. ``azure_storage_account_name`` → :class:`AzureTableSubscriptionStore`
    3. Fallback → SQLite :class:`~agent_sdk.contrib.webhooks.subscriptions.SubscriptionStore`
    """
    if getattr(settings, "azure_storage_connection_string", None):
        store = AzureTableSubscriptionStore(
            connection_string=settings.azure_storage_connection_string.get_secret_value(),
            table_prefix=settings.azure_storage_table_prefix,
        )
        store.initialize()
        return store
    if getattr(settings, "azure_storage_account_name", None):
        store = AzureTableSubscriptionStore(
            account_name=settings.azure_storage_account_name,
            table_prefix=settings.azure_storage_table_prefix,
        )
        store.initialize()
        return store
    from .subscriptions import SubscriptionStore
    from pathlib import Path

    data_dir = getattr(settings, "data_dir", "./data")
    return SubscriptionStore(Path(data_dir) / "webhook_subscriptions.db")


__all__ = [
    "AzureTableSubscriptionStore",
    "create_subscription_backend",
]
