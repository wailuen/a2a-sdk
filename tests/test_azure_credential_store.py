"""Tests for AzureTableCredentialStore (P1-04 + P1-05).

All Azure SDK calls are mocked — no live Azure connections required.
Azure packages (azure-data-tables, azure-identity) must be installed.
"""

from __future__ import annotations

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from agent_sdk.credentials.crypto import derive_key, encrypt as crypto_encrypt
from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore
from agent_sdk.models.errors import AgentError, ErrorCategory
from azure.core.exceptions import ResourceNotFoundError
from azure.data.tables import UpdateMode

MASTER_KEY = "test-master-key-0123456789abcdef-extra"  # >= 32 chars


# ---------------------------------------------------------------------------
# Factory: build a fully-mocked AzureTableCredentialStore
# ---------------------------------------------------------------------------


def _make_store(
    *,
    connection_string: str | None = "DefaultEndpointsProtocol=https;AccountName=test",
    account_name: str | None = None,
    prefix: str = "agent",
    existing_salt: bytes | None = None,
    wrong_key: bool = False,
) -> tuple["AzureTableCredentialStore", MagicMock]:
    """Build a store with all network calls mocked.

    If *wrong_key* is True the check entity in the table was written with a
    different AES key, so the store should raise AgentError(AUTH).

    Returns (store, table_client_mock).
    """
    from agent_sdk.credentials.azure_table import AzureTableCredentialStore
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = existing_salt if existing_salt is not None else os.urandom(16)
    aes_key = derive_key(MASTER_KEY, salt)
    aes = AESGCM(aes_key)

    if wrong_key:
        # Build check blob with a DIFFERENT key
        bad_key = derive_key("completely-different-key-0123456789!!", salt)
        bad_aes = AESGCM(bad_key)
        check_blob = crypto_encrypt(bad_aes, "__meta__", "__check__", "agent-sdk-store-check")
    else:
        check_blob = crypto_encrypt(aes, "__meta__", "__check__", "agent-sdk-store-check")

    salt_entity = {"PartitionKey": "__meta__", "RowKey": "salt", "Value": salt.hex()}
    check_entity = {
        "PartitionKey": "__meta__",
        "RowKey": "check",
        "Value": check_blob.decode(),
    }

    table_mock = MagicMock()
    table_mock.get_entity.side_effect = [salt_entity, check_entity]

    service_mock = MagicMock()
    service_mock.create_table_if_not_exists.return_value = table_mock

    with patch("azure.data.tables.TableServiceClient") as mock_tsc, \
         patch("azure.identity.DefaultAzureCredential", return_value=MagicMock()), \
         patch("agent_sdk.credentials.azure_table.require_azure_packages"):

        mock_tsc.from_connection_string.return_value = service_mock
        mock_tsc.return_value = service_mock

        store = AzureTableCredentialStore(
            MASTER_KEY,
            connection_string=connection_string,
            account_name=account_name,
            prefix=prefix,
        )

    # Wire the real AES instance so crypto round-trips work
    store._aes = aes

    # Reset mock for clean state in tests
    table_mock.get_entity.side_effect = None
    table_mock.get_entity.reset_mock()
    table_mock.upsert_entity.reset_mock()

    return store, table_mock


@pytest.fixture()
def store_and_table():
    return _make_store()


# ---------------------------------------------------------------------------
# P1-04: Unit tests
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_set_and_get_roundtrip(self, store_and_table):
        store, table = store_and_table

        store.set("myns", "api_key", "secret123")

        # Capture what was written
        assert table.upsert_entity.called
        entity_written = table.upsert_entity.call_args[0][0]
        assert entity_written["PartitionKey"] == "myns"
        assert entity_written["RowKey"] == "api_key"

        # Configure get_entity to return the stored entity
        table.get_entity.return_value = entity_written
        table.get_entity.side_effect = None

        result = store.get("myns", "api_key")
        assert result == "secret123"

    def test_delete(self, store_and_table):
        store, table = store_and_table
        store.delete("myns", "api_key")
        table.delete_entity.assert_called_once_with(
            partition_key="myns", row_key="api_key"
        )

    def test_list_fields(self, store_and_table):
        store, table = store_and_table
        table.query_entities.return_value = [
            {"RowKey": "token"},
            {"RowKey": "secret"},
            {"RowKey": "__check__"},  # should be filtered out
        ]
        result = store.list_fields("myns")
        assert result == ["secret", "token"]  # sorted, __ entries excluded

    def test_close_is_noop(self, store_and_table):
        store, _ = store_and_table
        store.close()  # Must not raise


class TestMissingEntity:
    def test_get_returns_none_for_missing(self, store_and_table):
        store, table = store_and_table
        table.get_entity.side_effect = ResourceNotFoundError("not found")
        result = store.get("myns", "missing_field")
        assert result is None

    def test_delete_swallows_not_found(self, store_and_table):
        store, table = store_and_table
        table.delete_entity.side_effect = ResourceNotFoundError("not found")
        store.delete("myns", "nonexistent")  # Must not raise


class TestCache:
    def test_cache_hit_skips_table_call(self, store_and_table):
        store, table = store_and_table
        # Pre-populate cache
        store._cache[("ns", "field")] = ("cached_value", time.monotonic() + 300)

        result = store.get("ns", "field")
        assert result == "cached_value"
        table.get_entity.assert_not_called()

    def test_cache_miss_after_expiry(self, store_and_table):
        store, table = store_and_table

        # Put an expired entry in the cache
        store._cache[("ns", "field")] = ("stale_value", time.monotonic() - 1)

        # Prepare fresh blob from Table Storage
        real_blob = crypto_encrypt(store._aes, "ns", "field", "fresh_value")
        table.get_entity.return_value = {
            "PartitionKey": "ns",
            "RowKey": "field",
            "Value": real_blob.decode(),
        }
        table.get_entity.side_effect = None

        result = store.get("ns", "field")
        assert result == "fresh_value"
        table.get_entity.assert_called_once()

    def test_cache_invalidated_on_set(self, store_and_table):
        store, table = store_and_table
        store._cache[("ns", "field")] = ("old_value", time.monotonic() + 300)

        store.set("ns", "field", "new_value")
        assert ("ns", "field") not in store._cache

    def test_cache_invalidated_on_delete(self, store_and_table):
        store, table = store_and_table
        store._cache[("ns", "field")] = ("value", time.monotonic() + 300)

        store.delete("ns", "field")
        assert ("ns", "field") not in store._cache


class TestMasterKeyVerification:
    def test_wrong_master_key_raises_auth_error(self):
        with pytest.raises(AgentError) as exc_info:
            _make_store(wrong_key=True)

        err = exc_info.value
        assert err.category == ErrorCategory.AUTH
        # SI-6: no key material in the message
        assert "MASTER_KEY" in err.message
        assert MASTER_KEY not in err.message


class TestInstantiationPaths:
    def test_connection_string_path(self):
        store, _ = _make_store(
            connection_string="DefaultEndpointsProtocol=https;AccountName=x"
        )
        assert store is not None

    def test_account_name_path(self):
        store, _ = _make_store(connection_string=None, account_name="mystorageaccount")
        assert store is not None

    def test_both_raises_value_error(self):
        with patch("agent_sdk.credentials.azure_table.require_azure_packages"):
            from agent_sdk.credentials.azure_table import AzureTableCredentialStore

            with pytest.raises(ValueError, match="not both"):
                AzureTableCredentialStore(
                    MASTER_KEY,
                    connection_string="conn",
                    account_name="acct",
                )

    def test_neither_raises_value_error(self):
        with patch("agent_sdk.credentials.azure_table.require_azure_packages"):
            from agent_sdk.credentials.azure_table import AzureTableCredentialStore

            with pytest.raises(ValueError, match="either"):
                AzureTableCredentialStore(MASTER_KEY)


# ---------------------------------------------------------------------------
# P1-05: Parameterized contract fixture — both stores must pass identically
# ---------------------------------------------------------------------------


def make_sqlite_store(tmp_path):
    db = tmp_path / "creds.db"
    return EncryptedSqliteStore(db, MASTER_KEY)


def make_azure_store(tmp_path):
    """Build a mocked AzureTableCredentialStore backed by an in-memory dict.

    The mock wires real crypto so all round-trip assertions work.
    """
    from agent_sdk.credentials.azure_table import AzureTableCredentialStore
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    salt = os.urandom(16)
    aes_key = derive_key(MASTER_KEY, salt)
    aes = AESGCM(aes_key)
    check_blob = crypto_encrypt(aes, "__meta__", "__check__", "agent-sdk-store-check")

    salt_entity = {"PartitionKey": "__meta__", "RowKey": "salt", "Value": salt.hex()}
    check_entity = {
        "PartitionKey": "__meta__",
        "RowKey": "check",
        "Value": check_blob.decode(),
    }

    # In-memory backing store for mock table
    _data: dict[tuple[str, str], str] = {}

    table_mock = MagicMock()

    def _get_entity(*, partition_key: str, row_key: str, **kw):
        if (partition_key, row_key) == ("__meta__", "salt"):
            return salt_entity
        if (partition_key, row_key) == ("__meta__", "check"):
            return check_entity
        if (partition_key, row_key) in _data:
            return {
                "PartitionKey": partition_key,
                "RowKey": row_key,
                "Value": _data[(partition_key, row_key)],
            }
        raise ResourceNotFoundError("not found")

    def _upsert_entity(entity, **kw):
        pk, rk = entity["PartitionKey"], entity["RowKey"]
        if pk == "__meta__":
            return  # ignore meta writes from _derive_key / _verify_master_key
        _data[(pk, rk)] = entity["Value"]

    def _delete_entity(*, partition_key: str, row_key: str, **kw):
        key = (partition_key, row_key)
        if key not in _data:
            raise ResourceNotFoundError("not found")
        del _data[key]

    def _query_entities(filter_str, **kw):
        ns = filter_str.split("'")[1]
        return [
            {"PartitionKey": ns, "RowKey": rk, "Value": v}
            for (pk, rk), v in _data.items()
            if pk == ns
        ]

    table_mock.get_entity.side_effect = _get_entity
    table_mock.upsert_entity.side_effect = _upsert_entity
    table_mock.delete_entity.side_effect = _delete_entity
    table_mock.query_entities.side_effect = _query_entities

    service_mock = MagicMock()
    service_mock.create_table_if_not_exists.return_value = table_mock

    with patch("azure.data.tables.TableServiceClient") as mock_tsc, \
         patch("agent_sdk.credentials.azure_table.require_azure_packages"):
        mock_tsc.from_connection_string.return_value = service_mock

        store = AzureTableCredentialStore(
            MASTER_KEY,
            connection_string="DefaultEndpointsProtocol=https;AccountName=test",
        )

    # Wire the real AES so crypto round-trips work
    store._aes = aes
    store._table = table_mock
    return store


@pytest.mark.parametrize(
    "store_factory",
    [
        pytest.param(make_sqlite_store, id="sqlite"),
        pytest.param(make_azure_store, id="azure-table"),
    ],
)
class TestCredentialStoreContract:
    """Parameterized contract: both store implementations must behave identically."""

    def test_set_get_roundtrip(self, store_factory, tmp_path):
        store = store_factory(tmp_path)
        store.set("source1", "api_key", "my-secret")
        assert store.get("source1", "api_key") == "my-secret"

    def test_get_missing_returns_none(self, store_factory, tmp_path):
        store = store_factory(tmp_path)
        assert store.get("source1", "no_such_field") is None

    def test_delete_removes_field(self, store_factory, tmp_path):
        store = store_factory(tmp_path)
        store.set("source1", "api_key", "value")
        store.delete("source1", "api_key")
        assert store.get("source1", "api_key") is None

    def test_delete_nonexistent_is_noop(self, store_factory, tmp_path):
        store = store_factory(tmp_path)
        store.delete("source1", "ghost")  # Must not raise

    def test_list_fields_sorted(self, store_factory, tmp_path):
        store = store_factory(tmp_path)
        store.set("ns", "zebra", "v1")
        store.set("ns", "apple", "v2")
        store.set("ns", "mango", "v3")
        fields = store.list_fields("ns")
        assert fields == ["apple", "mango", "zebra"]

    def test_list_fields_empty(self, store_factory, tmp_path):
        store = store_factory(tmp_path)
        assert store.list_fields("empty_ns") == []

    def test_set_overwrites(self, store_factory, tmp_path):
        store = store_factory(tmp_path)
        store.set("ns", "key", "first")
        store.set("ns", "key", "second")
        assert store.get("ns", "key") == "second"

    def test_close_is_noop_or_clean(self, store_factory, tmp_path):
        store = store_factory(tmp_path)
        store.close()  # Must not raise


# ---------------------------------------------------------------------------
# Redteam fix tests — findings from adversarial review
# ---------------------------------------------------------------------------


class TestCacheBypassForReservedNamespaces:
    """Finding 1: get() must bypass cache for reserved namespaces (API keys,
    OAuth tokens, model keys) so revocations propagate immediately across replicas."""

    def test_reserved_namespace_bypasses_cache(self, store_and_table):
        """A stale cache entry for a reserved namespace must NOT be returned."""
        from agent_sdk.credentials.store import NS_API_KEYS

        store, table = store_and_table
        # Pre-populate cache (as if a prior read cached it)
        store._cache[(NS_API_KEYS, "admin")] = ("stale_value", time.monotonic() + 300)

        real_blob = crypto_encrypt(store._aes, NS_API_KEYS, "admin", "fresh_value")
        table.get_entity.return_value = {
            "PartitionKey": NS_API_KEYS,
            "RowKey": "admin",
            "Value": real_blob.decode(),
        }
        table.get_entity.side_effect = None

        result = store.get(NS_API_KEYS, "admin")
        assert result == "fresh_value"
        table.get_entity.assert_called_once()

    def test_non_reserved_namespace_uses_cache(self, store_and_table):
        """A hot cache entry for a non-reserved namespace SHOULD be returned without a table call."""
        store, table = store_and_table
        store._cache[("myservice", "api_key")] = ("cached", time.monotonic() + 300)

        result = store.get("myservice", "api_key")
        assert result == "cached"
        table.get_entity.assert_not_called()

    def test_all_reserved_namespaces_bypass_cache(self, store_and_table):
        """Every reserved namespace skips cache; every non-reserved one uses it."""
        from agent_sdk.credentials.store import RESERVED_NAMESPACES

        store, table = store_and_table
        for ns in RESERVED_NAMESPACES:
            store._cache[(ns, "f")] = ("stale", time.monotonic() + 300)
            table.get_entity.return_value = {"PartitionKey": ns, "RowKey": "f", "Value": "x"}
            table.get_entity.side_effect = ResourceNotFoundError("not found")
            result = store.get(ns, "f")
            assert result is None  # table returned not-found, cache was bypassed


class TestListFieldsGuard:
    """Finding 11: list_fields('__meta__') must always return [] — never expose internal entities."""

    def test_list_fields_meta_returns_empty(self, store_and_table):
        store, table = store_and_table
        result = store.list_fields("__meta__")
        assert result == []
        table.query_entities.assert_not_called()


class TestSaltRaceCondition:
    """Finding 2/7: _derive_key and _verify_master_key must use create_entity
    (not upsert) so concurrent first-opens converge on a single canonical salt."""

    def test_derive_key_retries_on_race(self):
        """When create_entity raises ResourceExistsError (another replica won),
        we must re-read the winner's salt and derive the same key."""
        from agent_sdk.credentials.azure_table import AzureTableCredentialStore
        from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError

        salt = os.urandom(16)
        aes_key = derive_key(MASTER_KEY, salt)
        aes = AESGCM(aes_key)
        salt_entity = {"PartitionKey": "__meta__", "RowKey": "salt", "Value": salt.hex()}
        check_blob = crypto_encrypt(aes, "__meta__", "__check__", "agent-sdk-store-check")
        check_entity = {"PartitionKey": "__meta__", "RowKey": "check", "Value": check_blob.decode()}

        table_mock = MagicMock()
        service_mock = MagicMock()
        service_mock.create_table_if_not_exists.return_value = table_mock

        # First get_entity (for salt) raises Not Found → triggers create_entity path.
        # create_entity raises ResourceExistsError (another replica won).
        # Second get_entity (re-read winner salt) → returns salt_entity.
        # Third get_entity (verify check) → returns check_entity.
        get_calls = [
            ResourceNotFoundError("no salt"),  # _derive_key initial lookup
            salt_entity,                        # _derive_key re-read after race
            check_entity,                       # _verify_master_key lookup
        ]
        table_mock.get_entity.side_effect = get_calls
        table_mock.create_entity.side_effect = ResourceExistsError("race")

        with patch("azure.data.tables.TableServiceClient") as mock_tsc, \
             patch("agent_sdk.credentials.azure_table.require_azure_packages"):
            mock_tsc.from_connection_string.return_value = service_mock

            store = AzureTableCredentialStore(
                MASTER_KEY, connection_string="DefaultEndpointsProtocol=https;AccountName=test"
            )

        # Must have derived the key from the winner's salt
        assert store._aes is not None
        # create_entity was called exactly once (for the salt)
        assert table_mock.create_entity.call_count == 1
