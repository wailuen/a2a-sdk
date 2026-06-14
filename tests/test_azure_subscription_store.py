"""Tests for AzureTableSubscriptionStore and create_subscription_backend.

All tests use sys.modules injection to mock azure-data-tables and azure-identity
so that the tests run without those optional packages installed.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

# ── inject fake azure packages before any imports touch them ─────────────────

def _inject_azure_mocks():
    """Create minimal sys.modules stubs for azure.data.tables + azure.identity
    and azure.core.exceptions so the module can be imported without those
    packages installed.
    """

    # azure.core.exceptions
    exc_mod = ModuleType("azure.core.exceptions")

    class ResourceNotFoundError(Exception):
        pass

    exc_mod.ResourceNotFoundError = ResourceNotFoundError  # type: ignore[attr-defined]
    sys.modules.setdefault("azure.core", ModuleType("azure.core"))
    sys.modules.setdefault("azure.core.exceptions", exc_mod)

    # azure.data.tables
    tables_mod = ModuleType("azure.data.tables")

    class UpdateMode:
        MERGE = "merge"
        REPLACE = "replace"

    tables_mod.UpdateMode = UpdateMode  # type: ignore[attr-defined]

    class _FakeTableClient:
        pass

    class _FakeServiceClient:
        @classmethod
        def from_connection_string(cls, cs):
            return cls()

        def get_table_client(self, table_name):
            return _FakeTableClient()

    tables_mod.TableServiceClient = _FakeServiceClient  # type: ignore[attr-defined]

    azure_data_mod = ModuleType("azure.data")
    sys.modules.setdefault("azure.data", azure_data_mod)
    sys.modules.setdefault("azure.data.tables", tables_mod)

    # azure.identity
    identity_mod = ModuleType("azure.identity")

    class DefaultAzureCredential:
        pass

    identity_mod.DefaultAzureCredential = DefaultAzureCredential  # type: ignore[attr-defined]
    sys.modules.setdefault("azure.identity", identity_mod)

    return ResourceNotFoundError, UpdateMode


_ResourceNotFoundError, _UpdateMode = _inject_azure_mocks()

# Now safe to import the module under test.
from agent_sdk.contrib.webhooks.azure_table import (  # noqa: E402
    AzureTableSubscriptionStore,
    create_subscription_backend,
)

# ── constants ──────────────────────────────────────────────────────────────────

GUID = "11111111-2222-3333-4444-555555555555"
GUID2 = "22222222-2222-3333-4444-555555555555"
EXP_PAST = "2020-01-01T00:00:00Z"
EXP_FAR = "2099-01-01T00:00:00Z"


# ── fake entity builder ───────────────────────────────────────────────────────

def _make_entity(
    id: str = GUID,
    resource: str = "users/x/messages",
    change_type: str = "updated",
    notification_url: str = "https://h/cb",
    expiration: str = EXP_FAR,
    lifecycle_url: str | None = None,
    client_state_ref: str = "default",
    extra: dict | None = None,
) -> dict[str, Any]:
    """Return a fake Azure Table entity dict."""
    return {
        "PartitionKey": "subscriptions",
        "RowKey": id,
        "resource": resource,
        "change_type": change_type,
        "notification_url": notification_url,
        "lifecycle_url": lifecycle_url,
        "expiration": expiration,
        "client_state_ref": client_state_ref,
        "created_at": "2026-01-01T00:00:00Z",
        "extra_json": json.dumps(extra or {}),
    }


# ── mock table client ─────────────────────────────────────────────────────────

def _not_found() -> Exception:
    """Return a ResourceNotFoundError from whatever is currently in sys.modules.

    This ensures the exception class matches what the production code's
    ``except ResourceNotFoundError`` resolves to at call time, even when
    multiple test files inject different stubs into sys.modules.
    """
    return sys.modules["azure.core.exceptions"].ResourceNotFoundError("not found")


class _MockTableClient:
    """In-memory table client that behaves like azure.data.tables.TableClient."""

    def __init__(self, initial_entities: list[dict] | None = None):
        self._store: dict[str, dict] = {}
        self.upsert_entity = MagicMock(side_effect=self._upsert_entity)
        self.get_entity = MagicMock(side_effect=self._get_entity)
        self.delete_entity = MagicMock(side_effect=self._delete_entity)
        self.query_entities = MagicMock(side_effect=self._query_entities)
        self.create_table = MagicMock(return_value=None)
        if initial_entities:
            for e in initial_entities:
                self._store[e["RowKey"]] = dict(e)

    def _upsert_entity(self, entity, mode=None):
        self._store[entity["RowKey"]] = dict(entity)

    def _get_entity(self, partition_key, row_key):
        if row_key not in self._store:
            raise _not_found()
        return dict(self._store[row_key])

    def _delete_entity(self, partition_key, row_key):
        if row_key not in self._store:
            raise _not_found()
        del self._store[row_key]

    def _query_entities(self, filter_str):
        results = list(self._store.values())
        if "expiration le" in filter_str:
            cutoff = filter_str.split("expiration le '")[1].rstrip("'")
            results = [e for e in results if e.get("expiration", "") <= cutoff]
        return iter(results)


def _build_store(table_client=None, initial_entities=None):
    """Return an AzureTableSubscriptionStore wired to a mock table client."""
    tc = table_client or _MockTableClient(initial_entities)
    store = AzureTableSubscriptionStore.__new__(AzureTableSubscriptionStore)
    store._table_name = "agentsubscriptions"
    store._client = tc
    return store


# ─────────────────────────────────────────────────────────────────────────────
# 1. upsert() happy path — verify upsert_entity called with MERGE mode
# ─────────────────────────────────────────────────────────────────────────────

def test_upsert_calls_upsert_entity_with_merge_mode():
    tc = _MockTableClient()
    store = _build_store(tc)

    store.upsert(
        id=GUID,
        resource="users/x/messages",
        change_type="updated",
        notification_url="https://h/cb",
        expiration=EXP_FAR,
        extra={"k": "v"},
    )

    tc.upsert_entity.assert_called_once()
    call_kwargs = tc.upsert_entity.call_args
    entity = call_kwargs.kwargs.get("entity") or call_kwargs.args[0]
    mode = call_kwargs.kwargs.get("mode")

    assert entity["RowKey"] == GUID
    assert entity["PartitionKey"] == "subscriptions"
    assert json.loads(entity["extra_json"]) == {"k": "v"}
    assert mode == _UpdateMode.MERGE


# ─────────────────────────────────────────────────────────────────────────────
# 2. upsert() extra_json over 16 KB raises AgentError(VALIDATION)
# ─────────────────────────────────────────────────────────────────────────────

def test_upsert_extra_over_16kb_raises():
    from agent_sdk.models.errors import AgentError, ErrorCategory

    tc = _MockTableClient()
    store = _build_store(tc)

    big_extra = {"data": "x" * (16 * 1024 + 1)}
    with pytest.raises(AgentError) as ei:
        store.upsert(
            id=GUID,
            resource="r",
            change_type="updated",
            notification_url="https://h/cb",
            expiration=EXP_FAR,
            extra=big_extra,
        )
    assert ei.value.category == ErrorCategory.VALIDATION
    tc.upsert_entity.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 3. set_expiration() returns True on existing id, False on missing
# ─────────────────────────────────────────────────────────────────────────────

def test_set_expiration_existing_returns_true():
    tc = _MockTableClient(initial_entities=[_make_entity(id=GUID, expiration=EXP_FAR)])
    store = _build_store(tc)

    result = store.set_expiration(GUID, "2031-01-01T00:00:00Z")
    assert result is True
    assert tc._store[GUID]["expiration"] == "2031-01-01T00:00:00Z"


def test_set_expiration_missing_returns_false():
    tc = _MockTableClient()
    store = _build_store(tc)

    result = store.set_expiration(GUID, "2031-01-01T00:00:00Z")
    assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# 4. delete() on missing id does not raise
# ─────────────────────────────────────────────────────────────────────────────

def test_delete_missing_is_noop():
    tc = _MockTableClient()
    store = _build_store(tc)
    # Must not raise.
    store.delete(GUID)


def test_delete_existing_removes_entity():
    tc = _MockTableClient(initial_entities=[_make_entity(id=GUID)])
    store = _build_store(tc)

    store.delete(GUID)
    assert GUID not in tc._store


# ─────────────────────────────────────────────────────────────────────────────
# 5. get() returns None on missing
# ─────────────────────────────────────────────────────────────────────────────

def test_get_returns_none_on_missing():
    tc = _MockTableClient()
    store = _build_store(tc)
    assert store.get(GUID) is None


def test_get_returns_row_on_existing():
    tc = _MockTableClient(initial_entities=[_make_entity(id=GUID, extra={"foo": "bar"})])
    store = _build_store(tc)

    rec = store.get(GUID)
    assert rec is not None
    assert rec["id"] == GUID
    assert rec["resource"] == "users/x/messages"
    assert rec["extra"] == {"foo": "bar"}
    # Azure meta keys must not leak out.
    assert "PartitionKey" not in rec
    assert "RowKey" not in rec
    assert "extra_json" not in rec


# ─────────────────────────────────────────────────────────────────────────────
# 6. list() returns all entities ordered by expiration
# ─────────────────────────────────────────────────────────────────────────────

def test_list_returns_all_ordered_by_expiration():
    tc = _MockTableClient(initial_entities=[
        _make_entity(id=GUID2, expiration=EXP_FAR),
        _make_entity(id=GUID, expiration=EXP_PAST),
    ])
    store = _build_store(tc)

    rows = store.list()
    assert len(rows) == 2
    assert rows[0]["expiration"] == EXP_PAST
    assert rows[1]["expiration"] == EXP_FAR


# ─────────────────────────────────────────────────────────────────────────────
# 7. due_for_renewal(before_iso) returns only entities with expiration <= before_iso
# ─────────────────────────────────────────────────────────────────────────────

def test_due_for_renewal_filters_by_expiration():
    tc = _MockTableClient(initial_entities=[
        _make_entity(id=GUID, expiration=EXP_PAST),    # due
        _make_entity(id=GUID2, expiration=EXP_FAR),    # not due
    ])
    store = _build_store(tc)

    due = store.due_for_renewal("2025-01-01T00:00:00Z")
    assert len(due) == 1
    assert due[0]["id"] == GUID


def test_due_for_renewal_empty_when_none_due():
    tc = _MockTableClient(initial_entities=[_make_entity(id=GUID, expiration=EXP_FAR)])
    store = _build_store(tc)

    assert store.due_for_renewal("2025-01-01T00:00:00Z") == []


# ─────────────────────────────────────────────────────────────────────────────
# 8. create_subscription_backend() returns correct type based on settings
# ─────────────────────────────────────────────────────────────────────────────

def test_factory_returns_azure_store_when_connection_string(tmp_path):
    from pydantic import SecretStr

    settings = SimpleNamespace(
        azure_storage_connection_string=SecretStr(
            "DefaultEndpointsProtocol=https;AccountName=x;AccountKey=AAAA==;EndpointSuffix=core.windows.net"
        ),
        azure_storage_account_name=None,
        azure_storage_table_prefix="agent",
        data_dir=str(tmp_path),
    )

    # Patch the build_client so we don't actually connect.
    with patch.object(AzureTableSubscriptionStore, "_build_client", return_value=MagicMock()):
        backend = create_subscription_backend(settings)

    assert isinstance(backend, AzureTableSubscriptionStore)


def test_factory_returns_sqlite_store_when_no_azure(tmp_path):
    settings = SimpleNamespace(
        azure_storage_connection_string=None,
        azure_storage_account_name=None,
        azure_storage_table_prefix="agent",
        data_dir=str(tmp_path),
    )

    from agent_sdk.contrib.webhooks.subscriptions import SubscriptionStore

    backend = create_subscription_backend(settings)
    assert isinstance(backend, SubscriptionStore)
    backend.close()


# ─────────────────────────────────────────────────────────────────────────────
# 9. close() is a no-op
# ─────────────────────────────────────────────────────────────────────────────

def test_close_is_noop():
    tc = _MockTableClient()
    store = _build_store(tc)
    # Must not raise, must not interact with the client.
    store.close()
    tc.create_table.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 10. GraphSubscriptionManager works with mocked AzureTableSubscriptionStore
# ─────────────────────────────────────────────────────────────────────────────

class _FakeResp:
    def __init__(self, data: dict):
        self._data = data

    @property
    def content(self) -> bytes:
        return json.dumps(self._data).encode() if self._data else b""

    def json(self) -> dict:
        return self._data


class _FakeGraph:
    def __init__(self, response: dict | None = None):
        self.calls: list = []
        self._response = response or {}

    async def graph_request(self, method: str, path: str, **kwargs):
        self.calls.append((method, path, kwargs))
        return _FakeResp(self._response)


async def test_graph_manager_works_with_azure_store():
    from agent_sdk.contrib.webhooks.subscriptions import GraphSubscriptionManager

    tc = _MockTableClient()
    store = _build_store(tc)
    store.initialize()

    graph = _FakeGraph({"id": GUID, "expirationDateTime": EXP_FAR})
    mgr = GraphSubscriptionManager(graph, store, client_state="secret-123")

    created = await mgr.create(
        resource="users/x/messages",
        change_type="updated",
        notification_url="https://h/cb",
        expiration=datetime(2099, 1, 1, tzinfo=timezone.utc),
    )
    assert created["id"] == GUID
    # Secret must NOT appear in the persisted entity.
    rec = store.get(GUID)
    assert rec is not None
    assert "secret-123" not in str(rec)


# ─────────────────────────────────────────────────────────────────────────────
# 11. Parametrized contract fixture — same contract for both backends
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture(
    params=["sqlite", "azure"],
    ids=["SubscriptionStore(sqlite)", "AzureTableSubscriptionStore(mocked)"],
)
def sub_store(request, tmp_path):
    """Yield a ready SubscriptionBackend for each backend variant."""
    if request.param == "sqlite":
        from agent_sdk.contrib.webhooks.subscriptions import SubscriptionStore

        store = SubscriptionStore(tmp_path / "subs.db")
        store.initialize()
        yield store
        store.close()
    else:
        tc = _MockTableClient()
        store = _build_store(tc)
        store.initialize()
        yield store
        store.close()


def test_contract_upsert_and_get(sub_store):
    """upsert then get returns the expected record."""
    sub_store.upsert(
        id=GUID,
        resource="users/x/messages",
        change_type="updated",
        notification_url="https://h/cb",
        expiration=EXP_FAR,
        extra={"hello": "world"},
    )
    rec = sub_store.get(GUID)
    assert rec is not None
    assert rec["resource"] == "users/x/messages"
    assert rec["extra"] == {"hello": "world"}
    # clientState must NEVER appear in the persisted record.
    assert "client_state" not in str(rec).replace("client_state_ref", "CSR")


def test_contract_delete(sub_store):
    """upsert → delete → get returns None."""
    sub_store.upsert(
        id=GUID,
        resource="r",
        change_type="updated",
        notification_url="https://h/cb",
        expiration=EXP_FAR,
    )
    assert sub_store.get(GUID) is not None
    sub_store.delete(GUID)
    assert sub_store.get(GUID) is None


def test_contract_due_for_renewal(sub_store):
    """Only the past-expiration subscription appears in due_for_renewal."""
    sub_store.upsert(
        id=GUID,
        resource="r",
        change_type="updated",
        notification_url="https://h/cb",
        expiration=EXP_PAST,
    )
    sub_store.upsert(
        id=GUID2,
        resource="r2",
        change_type="created",
        notification_url="https://h/cb2",
        expiration=EXP_FAR,
    )
    due = sub_store.due_for_renewal("2025-01-01T00:00:00Z")
    assert len(due) == 1
    assert due[0]["id"] == GUID


# ---------------------------------------------------------------------------
# Redteam fix tests — findings from adversarial review
# ---------------------------------------------------------------------------


def test_both_set_raises_value_error():
    """Finding 4: AzureTableSubscriptionStore must reject both connection_string
    AND account_name being set (mirrors AzureTableCommitmentStore behaviour)."""
    from agent_sdk.contrib.webhooks.azure_table import AzureTableSubscriptionStore

    with patch("agent_sdk.contrib.azure_utils.require_azure_packages"):
        with pytest.raises(ValueError, match="not both"):
            AzureTableSubscriptionStore(
                connection_string="DefaultEndpointsProtocol=https;AccountName=x",
                account_name="x",
            )


def test_create_subscription_backend_calls_initialize_for_azure():
    """Finding 9: create_subscription_backend() must call store.initialize()
    on the Azure backend so the table exists before the first upsert."""
    store_mock = MagicMock()

    with patch(
        "agent_sdk.contrib.webhooks.azure_table.AzureTableSubscriptionStore",
        return_value=store_mock,
    ), patch("agent_sdk.contrib.azure_utils.require_azure_packages"):
        from agent_sdk.contrib.webhooks.azure_table import create_subscription_backend
        from pydantic import SecretStr

        settings = SimpleNamespace(
            azure_storage_connection_string=SecretStr("DefaultEndpointsProtocol=https;AccountName=x"),
            azure_storage_account_name=None,
            azure_storage_table_prefix="agent",
        )
        backend = create_subscription_backend(settings)

    store_mock.initialize.assert_called_once()
    assert backend is store_mock
