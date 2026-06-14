"""Azure Table Storage credential store (DESIGN.md §6).

- KDF pinned: PBKDF2-HMAC-SHA256, 600k iterations, per-store random salt
  persisted in the (plaintext) ``__meta__`` partition.
- Values encrypted with AES-256-GCM; the ``{namespace}/{field}`` slot is
  bound as AAD so a ciphertext moved between rows fails to decrypt.
- A check value written at store creation detects a wrong MASTER_KEY at
  startup with a clear error instead of garbage reads.
- 5-minute TTL in-memory read cache (thread-safe) reduces Table Storage round
  trips for hot-path adapter lookups.

Security invariants:
- SI-4: get() never exposes plaintext in exceptions or logs.
- SI-6: connection_string never logged; master_key never in error messages.
"""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from ..contrib.azure_utils import require_azure_packages
from ..models.errors import AgentError, ErrorCategory
from .crypto import decrypt, derive_key, encrypt
from .store import RESERVED_NAMESPACES, CredentialStore

_CHECK_FIELD = "__check__"
_CHECK_VALUE = "agent-sdk-store-check"
_CACHE_TTL = 300  # 5 minutes in seconds

# Reserved namespaces hold security-sensitive credentials (API keys, OAuth tokens,
# model keys). Bypass the in-process cache for these so revocations on one replica
# are visible immediately on every other replica (no 5-min stale window).
_UNCACHED_NAMESPACES = RESERVED_NAMESPACES


class AzureTableCredentialStore(CredentialStore):
    """Credential store backed by Azure Table Storage.

    Accepts either *connection_string* OR *account_name* (with
    ``DefaultAzureCredential``), but not both.  Raises :class:`ValueError`
    if the caller passes both or neither.

    Args:
        master_key: Plaintext master key (min 32 chars) used to derive the
            AES-256 key via PBKDF2-HMAC-SHA256.
        connection_string: Full Azure Storage connection string.
        account_name: Azure Storage account name; uses DefaultAzureCredential.
        prefix: Table-name prefix (default ``"agent"``).  The table is named
            ``{prefix}credentials``.
    """

    def __init__(
        self,
        master_key: str,
        *,
        connection_string: str | None = None,
        account_name: str | None = None,
        prefix: str = "agent",
    ) -> None:
        require_azure_packages()

        if connection_string is not None and account_name is not None:
            raise ValueError(
                "Provide either 'connection_string' or 'account_name', not both"
            )
        if connection_string is None and account_name is None:
            raise ValueError(
                "Provide either 'connection_string' or 'account_name'"
            )
        if len(master_key) < 32:
            raise ValueError("MASTER_KEY must be at least 32 characters")

        from azure.data.tables import TableServiceClient

        if connection_string is not None:
            self._service = TableServiceClient.from_connection_string(connection_string)
        else:
            from azure.identity import DefaultAzureCredential

            credential = DefaultAzureCredential()
            self._service = TableServiceClient(
                endpoint=f"https://{account_name}.table.core.windows.net",
                credential=credential,
            )

        table_name = f"{prefix}credentials"
        self._table = self._service.create_table_if_not_exists(table_name)

        # 5-min TTL in-memory cache: (namespace, field) → (plaintext, expires_at)
        self._cache: dict[tuple[str, str], tuple[str, float]] = {}
        self._cache_lock = threading.Lock()

        self._aes = AESGCM(self._derive_key(master_key))
        self._verify_master_key()

    # ── key handling ──

    def _derive_key(self, master_key: str) -> bytes:
        """Read (or create) the per-store salt, then derive the AES key.

        Uses create_entity (not upsert) so concurrent first-opens on multiple
        replicas produce exactly one winning salt; the loser re-reads the winner's
        salt and derives the same key — avoiding a split-brain where two replicas
        end up with incompatible AES keys.
        """
        from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

        try:
            entity = self._table.get_entity(
                partition_key="__meta__", row_key="salt"
            )
            return derive_key(master_key, bytes.fromhex(entity["Value"]))
        except ResourceNotFoundError:
            pass

        salt = os.urandom(16)
        try:
            self._table.create_entity(
                {
                    "PartitionKey": "__meta__",
                    "RowKey": "salt",
                    "Value": salt.hex(),
                }
            )
        except ResourceExistsError:
            # Another replica won the race — use its salt.
            entity = self._table.get_entity(
                partition_key="__meta__", row_key="salt"
            )
            salt = bytes.fromhex(entity["Value"])
        return derive_key(master_key, salt)

    def _verify_master_key(self) -> None:
        """Write check entity on first open; decrypt it on subsequent opens.

        Uses create_entity (not upsert) so concurrent first-opens produce exactly
        one check entity — the loser re-reads and verifies against the winner's
        entity, preventing one replica's check from silently overwriting another's
        and creating a permanently inconsistent store.
        """
        from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

        try:
            entity = self._table.get_entity(
                partition_key="__meta__", row_key="check"
            )
        except ResourceNotFoundError:
            blob = encrypt(self._aes, "__meta__", _CHECK_FIELD, _CHECK_VALUE)
            try:
                self._table.create_entity(
                    {
                        "PartitionKey": "__meta__",
                        "RowKey": "check",
                        "Value": blob.decode(),
                    }
                )
                return
            except ResourceExistsError:
                # Another replica won the race — fall through to verify its entity.
                entity = self._table.get_entity(
                    partition_key="__meta__", row_key="check"
                )

        try:
            blob = entity["Value"].encode()
            decrypt(self._aes, "__meta__", _CHECK_FIELD, blob)
        except AgentError as err:
            raise AgentError(
                ErrorCategory.AUTH,
                "MASTER_KEY does not match the existing credential store; "
                "restore the original key or wipe the store",
            ) from err

    # ── CredentialStore ──

    def get(self, namespace: str, field: str) -> str | None:
        # Bypass cache for security-sensitive namespaces (API keys, OAuth tokens,
        # model keys). A revocation on one replica must be visible to all others
        # immediately — the 5-min TTL window is unacceptable for these.
        use_cache = namespace not in _UNCACHED_NAMESPACES

        if use_cache:
            key = (namespace, field)
            with self._cache_lock:
                cached = self._cache.get(key)
                if cached is not None:
                    plaintext, expires_at = cached
                    if time.monotonic() < expires_at:
                        return plaintext
                    del self._cache[key]

        from azure.core.exceptions import ResourceNotFoundError

        try:
            entity = self._table.get_entity(
                partition_key=namespace, row_key=field
            )
        except ResourceNotFoundError:
            return None

        plaintext = decrypt(self._aes, namespace, field, entity["Value"].encode())
        if use_cache:
            with self._cache_lock:
                self._cache[(namespace, field)] = (plaintext, time.monotonic() + _CACHE_TTL)
        return plaintext

    def set(self, namespace: str, field: str, value: str) -> None:
        blob = encrypt(self._aes, namespace, field, value)
        key = (namespace, field)
        with self._cache_lock:
            self._cache.pop(key, None)

        from azure.data.tables import UpdateMode

        self._table.upsert_entity(
            {
                "PartitionKey": namespace,
                "RowKey": field,
                "Value": blob.decode(),
            },
            mode=UpdateMode.MERGE,
        )

    def delete(self, namespace: str, field: str) -> None:
        key = (namespace, field)
        with self._cache_lock:
            self._cache.pop(key, None)

        from azure.core.exceptions import ResourceNotFoundError

        try:
            self._table.delete_entity(partition_key=namespace, row_key=field)
        except ResourceNotFoundError:
            pass

    def list_fields(self, namespace: str) -> list[str]:
        """Return sorted field names for *namespace*, excluding ``__meta__`` entries."""
        if namespace == "__meta__":
            return []
        entities = self._table.query_entities(
            "PartitionKey eq @partition_key",
            parameters={"partition_key": namespace},
        )
        return sorted(
            e["RowKey"]
            for e in entities
            if not e["RowKey"].startswith("__")
        )

    def close(self) -> None:
        """No-op: azure-data-tables client is stateless."""


__all__ = ["AzureTableCredentialStore"]
