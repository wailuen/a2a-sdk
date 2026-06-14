"""AzureTableCommitmentStore — unit tests using mocked Azure Table SDK.

All Azure SDK calls are mocked so these tests run without azure-data-tables
or azure-identity installed (the guard in require_azure_packages is bypassed by
patching at the module level before the class is instantiated).

Coverage:
  1. add() happy path; secret-in-args raises ValueError
  2. claim_due() race: ResourceModifiedError on second update → only one caller wins
  3. mark_fired() returns True on success, False if not in "firing"
  4. mark_failed() reason bearer-scrubbed and truncated
  5. cancel() identity-binding mismatch returns False
  6. reap_stale_firing() skips entity on ResourceModifiedError
  7. get() returns None on missing entity
  8. list() filters by identity_binding and status
  9. create_commitment_backend() returns AzureTableCommitmentStore when
     connection_string set, CommitmentStore otherwise
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ── Pre-load real azure modules before stubs can be injected ─────────────────
# test_azure_subscription_store.py injects minimal azure stubs via
# sys.modules.setdefault() AT MODULE LOAD TIME. Those stubs lack
# ResourceModifiedError/ResourceExistsError/MatchConditions which our
# azure_table.py needs.
#
# By importing the real azure sub-modules here (before that file is collected),
# we fill sys.modules with the real implementations so setdefault() is a no-op.
# If azure packages are not installed, we install minimal stubs ourselves.

def _preload_or_stub_azure() -> None:
    """Ensure azure.core.exceptions, azure.core, and azure.data.tables are in
    sys.modules with the exception classes our implementation requires.

    Strategy:
    - Try to import the real modules (works when azure-core / azure-data-tables
      are installed).
    - If that fails, or if a bare stub is already present (injected by another
      test file), augment sys.modules with our needed symbols.
    """
    # 1. Try to populate with the real modules.
    try:
        import azure.core  # noqa: F401
        import azure.core.exceptions  # noqa: F401
        from azure.core.exceptions import (  # noqa: F401
            ResourceModifiedError,
            ResourceExistsError,
            ResourceNotFoundError,
        )
        from azure.core import MatchConditions  # noqa: F401
        # Real modules loaded successfully — we're done.
        return
    except (ImportError, ModuleNotFoundError):
        pass  # fall through to stub injection

    # 2. Real packages not available (or stub already loaded). Build/augment stubs.
    core_mod = sys.modules.get("azure.core")
    if core_mod is None:
        core_mod = ModuleType("azure.core")
        sys.modules["azure.core"] = core_mod

    exc_mod = sys.modules.get("azure.core.exceptions")
    if exc_mod is None:
        exc_mod = ModuleType("azure.core.exceptions")
        sys.modules["azure.core.exceptions"] = exc_mod

    for exc_name in ("ResourceModifiedError", "ResourceExistsError", "ResourceNotFoundError"):
        if not hasattr(exc_mod, exc_name):
            exc_cls = type(exc_name, (Exception,), {})
            setattr(exc_mod, exc_name, exc_cls)

    if not hasattr(core_mod, "MatchConditions"):
        class MatchConditions:
            IfNotModified = "if_not_modified"
        core_mod.MatchConditions = MatchConditions  # type: ignore[attr-defined]

    tables_mod = sys.modules.get("azure.data.tables")
    if tables_mod is not None and not hasattr(tables_mod, "UpdateMode"):
        class UpdateMode:
            REPLACE = "replace"
            MERGE = "merge"
        tables_mod.UpdateMode = UpdateMode  # type: ignore[attr-defined]


_preload_or_stub_azure()


# ── helpers ──────────────────────────────────────────────────────────────────

def _past(seconds: int = 60) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def _future(seconds: int = 3600) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=seconds)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


class _FakeEntity(dict):
    """A dict subclass that also supports attribute-style access for metadata,
    mirroring how azure-data-tables SDK entities expose .metadata / ._metadata."""

    def __init__(self, *args, etag: str = "W/\"etag-abc\"", **kwargs):
        super().__init__(*args, **kwargs)
        self.metadata = {"etag": etag}
        self._metadata = {"etag": etag}


def _make_entity(
    commitment_id: str | None = None,
    *,
    tool: str = "send",
    fire_at: str | None = None,
    status: str = "pending",
    identity_binding: str | None = None,
    claimed_at: str | None = None,
    attempts: int = 0,
    last_error: str | None = None,
    etag: str = "W/\"etag-abc\"",
) -> _FakeEntity:
    """Build a _FakeEntity that looks like an Azure Table entity returned by the SDK."""
    row_key = commitment_id or str(uuid.uuid4())
    return _FakeEntity(
        {
            "PartitionKey": "commitments",
            "RowKey": row_key,
            "tool": tool,
            "args_json": json.dumps({}),
            "fire_at": fire_at or _future(),
            "status": status,
            "created_at": "2026-01-01T00:00:00Z",
            "identity_binding": identity_binding,
            "auth_context_json": "{}",
            "claimed_at": claimed_at,
            "attempts": attempts,
            "last_error": last_error,
        },
        etag=etag,
    )


# ── factory for the store under test ─────────────────────────────────────────

def _make_store(table_client: MagicMock, service_client: MagicMock | None = None):
    """Return an AzureTableCommitmentStore with mocked Azure clients.

    We bypass require_azure_packages() and the TableServiceClient constructor by
    patching at import time.
    """
    with (
        patch("agent_sdk.contrib.azure_utils.require_azure_packages"),
        patch(
            "azure.data.tables.TableServiceClient.from_connection_string",
            return_value=service_client or MagicMock(
                get_table_client=MagicMock(return_value=table_client)
            ),
        ),
    ):
        from agent_sdk.contrib.commitments.azure_table import AzureTableCommitmentStore

        store = AzureTableCommitmentStore.__new__(AzureTableCommitmentStore)
        store._table_name = "agentcommitments"
        store._table = table_client
        # Provide a minimal _service for initialize()
        svc = service_client or MagicMock()
        store._service = svc
        return store


# ── 1. add() ──────────────────────────────────────────────────────────────────

def test_add_happy_path_calls_create_entity():
    table = MagicMock()
    store = _make_store(table)

    cid = store.add(tool="send", args={"x": 1}, fire_at=_future())

    assert isinstance(cid, str) and len(cid) == 36  # UUID
    assert table.create_entity.call_count == 1
    entity_arg = table.create_entity.call_args[0][0]
    assert entity_arg["tool"] == "send"
    assert entity_arg["status"] == "pending"
    assert entity_arg["RowKey"] == cid
    assert entity_arg["PartitionKey"] == "commitments"
    assert json.loads(entity_arg["args_json"]) == {"x": 1}


def test_add_secret_in_args_raises_valueerror():
    table = MagicMock()
    store = _make_store(table)

    with pytest.raises(ValueError, match="secret"):
        store.add(tool="send", args={"api_key": "s3cr3t"}, fire_at=_future())

    table.create_entity.assert_not_called()


def test_add_normalizes_fire_at_to_utc():
    table = MagicMock()
    store = _make_store(table)

    store.add(tool="t", args={}, fire_at="2099-06-01T10:00:00+05:00")

    entity_arg = table.create_entity.call_args[0][0]
    assert entity_arg["fire_at"] == "2099-06-01T05:00:00Z"


def test_add_blank_identity_binding_raises():
    table = MagicMock()
    store = _make_store(table)

    for blank in ("", "   "):
        with pytest.raises(ValueError):
            store.add(tool="t", args={}, fire_at=_future(), identity_binding=blank)


def test_add_auth_context_secrets_are_redacted():
    table = MagicMock()
    store = _make_store(table)

    store.add(
        tool="t",
        args={},
        fire_at=_future(),
        auth_context={"home_account_id": "oid.tid", "access_token": "LIVE_TOKEN"},
    )

    entity_arg = table.create_entity.call_args[0][0]
    ctx = json.loads(entity_arg["auth_context_json"])
    assert ctx["home_account_id"] == "oid.tid"
    assert "LIVE_TOKEN" not in json.dumps(ctx)
    assert ctx["access_token"] == "[redacted]"


# ── 2. claim_due() race ───────────────────────────────────────────────────────

def test_claim_due_race_only_one_winner():
    """Two callers see the same pending entity; the second update raises
    ResourceModifiedError — only the first caller's entity is returned."""
    from azure.core.exceptions import ResourceModifiedError

    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="pending", fire_at=_past())

    table = MagicMock()
    table.query_entities.return_value = iter([entity])
    # First update succeeds, second raises ResourceModifiedError
    table.update_entity.side_effect = [None, ResourceModifiedError("conflict")]

    store = _make_store(table)
    # Call claim_due twice (simulating two callers with the same candidate list)
    # First call wins:
    claimed1 = store.claim_due(now="2099-01-01T00:00:00Z")

    # Reset to simulate second caller seeing same entity still
    table.query_entities.return_value = iter([entity])
    table.update_entity.side_effect = ResourceModifiedError("conflict")
    claimed2 = store.claim_due(now="2099-01-01T00:00:00Z")

    assert len(claimed1) == 1
    assert claimed1[0].id == commitment_id
    assert len(claimed2) == 0  # second caller lost the race


def test_claim_due_only_returns_due_pending():
    """Entities with status != pending or fire_at in future are not returned
    (the filter_expr is forwarded to query_entities)."""
    table = MagicMock()
    # query_entities returns empty list (all filtered by the OData filter)
    table.query_entities.return_value = iter([])

    store = _make_store(table)
    result = store.claim_due()

    assert result == []
    # Verify the filter expression is correct
    call_args = table.query_entities.call_args
    filter_str = call_args[0][0] if call_args[0] else call_args[1].get("query_filter", "")
    assert "status eq 'pending'" in filter_str
    assert "fire_at le" in filter_str


def test_claim_due_increments_attempts():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="pending", fire_at=_past(), attempts=2)

    table = MagicMock()
    table.query_entities.return_value = iter([entity])
    table.update_entity.return_value = None

    store = _make_store(table)
    claimed = store.claim_due()

    assert claimed[0].attempts == 3


# ── 3. mark_fired() ───────────────────────────────────────────────────────────

def test_mark_fired_returns_true_on_success():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="firing")

    table = MagicMock()
    table.get_entity.return_value = entity
    table.update_entity.return_value = None

    store = _make_store(table)
    result = store.mark_fired(commitment_id)

    assert result is True
    entity_arg = table.update_entity.call_args[0][0]
    assert entity_arg["status"] == "fired"


def test_mark_fired_returns_false_if_not_firing():
    """If the row is 'pending' (never claimed) or already 'fired', mark_fired
    must return False without calling update_entity."""
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="pending")

    table = MagicMock()
    table.get_entity.return_value = entity

    store = _make_store(table)
    result = store.mark_fired(commitment_id)

    assert result is False
    table.update_entity.assert_not_called()


def test_mark_fired_returns_false_when_entity_missing():
    from azure.core.exceptions import ResourceNotFoundError

    table = MagicMock()
    table.get_entity.side_effect = ResourceNotFoundError("not found")

    store = _make_store(table)
    result = store.mark_fired("nonexistent-id")

    assert result is False


def test_mark_fired_returns_false_on_concurrent_update():
    """If another replica transitions the row first, IfNotModified raises
    ResourceModifiedError — mark_fired must return False."""
    from azure.core.exceptions import ResourceModifiedError

    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="firing")

    table = MagicMock()
    table.get_entity.return_value = entity
    table.update_entity.side_effect = ResourceModifiedError("conflict")

    store = _make_store(table)
    result = store.mark_fired(commitment_id)

    assert result is False


# ── 4. mark_failed() bearer-scrub + truncation ────────────────────────────────

def test_mark_failed_scrubs_bearer_and_truncates_reason():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="firing")

    table = MagicMock()
    table.get_entity.return_value = entity
    table.update_entity.return_value = None

    store = _make_store(table)
    long_secret_reason = "Bearer eyJraw.super.secret extra " + "z" * 500
    result = store.mark_failed(commitment_id, long_secret_reason)

    assert result is True
    entity_arg = table.update_entity.call_args[0][0]
    stored_reason = entity_arg["last_error"]
    assert "eyJraw.super.secret" not in stored_reason
    assert "[redacted]" in stored_reason
    assert len(stored_reason) <= 200


def test_mark_failed_accepts_none_reason():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="firing")

    table = MagicMock()
    table.get_entity.return_value = entity
    table.update_entity.return_value = None

    store = _make_store(table)
    result = store.mark_failed(commitment_id, None)

    assert result is True
    entity_arg = table.update_entity.call_args[0][0]
    # None becomes empty string after str(None or "")[:200]
    assert entity_arg["last_error"] == ""


# ── 5. cancel() identity-binding mismatch ─────────────────────────────────────

def test_cancel_identity_mismatch_returns_false():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="pending", identity_binding="user:alice")

    table = MagicMock()
    table.get_entity.return_value = entity

    store = _make_store(table)
    result = store.cancel(commitment_id, identity_binding="user:bob")

    assert result is False
    table.update_entity.assert_not_called()


def test_cancel_correct_identity_returns_true():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="pending", identity_binding="user:alice")

    table = MagicMock()
    table.get_entity.return_value = entity
    table.update_entity.return_value = None

    store = _make_store(table)
    result = store.cancel(commitment_id, identity_binding="user:alice")

    assert result is True
    entity_arg = table.update_entity.call_args[0][0]
    assert entity_arg["status"] == "cancelled"


def test_cancel_already_not_pending_returns_false():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="firing")  # not pending

    table = MagicMock()
    table.get_entity.return_value = entity

    store = _make_store(table)
    result = store.cancel(commitment_id)

    assert result is False
    table.update_entity.assert_not_called()


def test_cancel_missing_entity_returns_false():
    from azure.core.exceptions import ResourceNotFoundError

    table = MagicMock()
    table.get_entity.side_effect = ResourceNotFoundError("not found")

    store = _make_store(table)
    result = store.cancel("nonexistent-id")

    assert result is False


# ── 6. reap_stale_firing() skips on ResourceModifiedError ─────────────────────

def test_reap_stale_firing_skips_on_resource_modified_error():
    """reap_stale_firing processes two stale entities; the first update raises
    ResourceModifiedError (benign — another replica already transitioned it).
    Only the second update succeeds, so the returned count is 1."""
    from azure.core.exceptions import ResourceModifiedError

    e1 = _make_entity(status="firing", claimed_at="2000-01-01T00:00:00Z")
    e2 = _make_entity(status="firing", claimed_at="2000-01-01T00:00:00Z")

    table = MagicMock()
    table.query_entities.return_value = iter([e1, e2])
    table.update_entity.side_effect = [ResourceModifiedError("conflict"), None]

    store = _make_store(table)
    count = store.reap_stale_firing(lease_seconds=0)

    assert count == 1  # only the successful update is counted
    assert table.update_entity.call_count == 2


def test_reap_stale_firing_returns_zero_on_no_candidates():
    table = MagicMock()
    table.query_entities.return_value = iter([])

    store = _make_store(table)
    count = store.reap_stale_firing(lease_seconds=300)

    assert count == 0


# ── 7. get() returns None on missing entity ────────────────────────────────────

def test_get_returns_none_on_missing_entity():
    from azure.core.exceptions import ResourceNotFoundError

    table = MagicMock()
    table.get_entity.side_effect = ResourceNotFoundError("not found")

    store = _make_store(table)
    result = store.get("nonexistent-id")

    assert result is None


def test_get_returns_commitment_when_found():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, tool="ping", status="pending")

    table = MagicMock()
    table.get_entity.return_value = entity

    store = _make_store(table)
    result = store.get(commitment_id)

    assert result is not None
    assert result.id == commitment_id
    assert result.tool == "ping"
    assert result.status == "pending"


def test_get_identity_binding_mismatch_returns_none():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, identity_binding="user:alice")

    table = MagicMock()
    table.get_entity.return_value = entity

    store = _make_store(table)
    result = store.get(commitment_id, identity_binding="user:bob")

    assert result is None


# ── 8. list() filtering ────────────────────────────────────────────────────────

def test_list_filters_by_identity_binding():
    alice_id = str(uuid.uuid4())
    alice_entity = _make_entity(alice_id, identity_binding="user:alice")

    table = MagicMock()
    # Only alice's entity is returned (OData filter applied server-side)
    table.query_entities.return_value = iter([alice_entity])

    store = _make_store(table)
    results = store.list(identity_binding="user:alice")

    assert len(results) == 1
    assert results[0].identity_binding == "user:alice"

    # Verify filter expression includes identity_binding clause
    call_filter = table.query_entities.call_args[0][0]
    assert "identity_binding eq 'user:alice'" in call_filter


def test_list_filters_by_status():
    entity = _make_entity(status="pending")

    table = MagicMock()
    table.query_entities.return_value = iter([entity])

    store = _make_store(table)
    results = store.list(status="pending")

    assert len(results) == 1
    assert results[0].status == "pending"

    call_filter = table.query_entities.call_args[0][0]
    assert "status eq 'pending'" in call_filter


def test_list_respects_limit():
    entities = [_make_entity() for _ in range(5)]
    # Assign distinct created_at values
    for i, e in enumerate(entities):
        e["created_at"] = f"2026-01-0{i+1}T00:00:00Z"

    table = MagicMock()
    table.query_entities.return_value = iter(entities)

    store = _make_store(table)
    results = store.list(limit=3)

    assert len(results) == 3


def test_list_sorted_newest_first():
    e1 = _make_entity()
    e1["created_at"] = "2026-01-01T00:00:00Z"
    e2 = _make_entity()
    e2["created_at"] = "2026-03-01T00:00:00Z"
    e3 = _make_entity()
    e3["created_at"] = "2026-02-01T00:00:00Z"

    table = MagicMock()
    table.query_entities.return_value = iter([e1, e2, e3])

    store = _make_store(table)
    results = store.list()

    # Should be sorted newest first
    assert results[0].created_at == "2026-03-01T00:00:00Z"
    assert results[1].created_at == "2026-02-01T00:00:00Z"
    assert results[2].created_at == "2026-01-01T00:00:00Z"


# ── 9. create_commitment_backend() factory ─────────────────────────────────────

def test_factory_returns_azure_store_when_connection_string_set():
    """When settings.azure_storage_connection_string is set, the factory must
    return an AzureTableCommitmentStore."""
    settings = SimpleNamespace(
        azure_storage_connection_string=SimpleNamespace(
            get_secret_value=lambda: "DefaultEndpointsProtocol=https;AccountName=test;AccountKey=abc;EndpointSuffix=core.windows.net"
        ),
        azure_storage_account_name=None,
        azure_storage_table_prefix="agent",
        data_dir="./data",
    )

    with (
        patch("agent_sdk.contrib.azure_utils.require_azure_packages"),
        patch("azure.data.tables.TableServiceClient.from_connection_string") as mock_svc_fn,
    ):
        mock_svc = MagicMock()
        mock_svc.get_table_client.return_value = MagicMock()
        mock_svc_fn.return_value = mock_svc

        from agent_sdk.contrib.commitments.azure_table import (
            AzureTableCommitmentStore,
            create_commitment_backend,
        )

        result = create_commitment_backend(settings)

    assert isinstance(result, AzureTableCommitmentStore)


def test_factory_returns_sqlite_store_when_no_azure_config(tmp_path):
    """When neither Azure connection_string nor account_name is set, the factory
    must return a SQLite CommitmentStore."""
    settings = SimpleNamespace(
        azure_storage_connection_string=None,
        azure_storage_account_name=None,
        azure_storage_table_prefix="agent",
        data_dir=str(tmp_path),
    )

    from agent_sdk.contrib.commitments.azure_table import create_commitment_backend
    from agent_sdk.contrib.commitments.store import CommitmentStore

    result = create_commitment_backend(settings)

    assert isinstance(result, CommitmentStore)
    result.close()


def test_factory_returns_azure_store_when_account_name_set():
    """When settings.azure_storage_account_name is set (managed identity path),
    the factory must return an AzureTableCommitmentStore."""
    settings = SimpleNamespace(
        azure_storage_connection_string=None,
        azure_storage_account_name="mystorageaccount",
        azure_storage_table_prefix="myprefix",
        data_dir="./data",
    )

    with (
        patch("agent_sdk.contrib.azure_utils.require_azure_packages"),
        patch("azure.identity.DefaultAzureCredential") as mock_cred_cls,
        patch("azure.data.tables.TableServiceClient") as mock_svc_cls,
    ):
        mock_svc = MagicMock()
        mock_svc.get_table_client.return_value = MagicMock()
        mock_svc_cls.return_value = mock_svc

        from agent_sdk.contrib.commitments.azure_table import (
            AzureTableCommitmentStore,
            create_commitment_backend,
        )

        result = create_commitment_backend(settings)

    assert isinstance(result, AzureTableCommitmentStore)
    assert result._table_name == "myprefixcommitments"


# ── initialize() ──────────────────────────────────────────────────────────────

def test_initialize_creates_table():
    svc = MagicMock()
    table = MagicMock()
    svc.get_table_client.return_value = table

    store = _make_store(table, service_client=svc)
    store.initialize()

    svc.create_table.assert_called_once_with("agentcommitments")


def test_initialize_is_idempotent_on_already_exists():
    """create_table raising an error containing 'TableAlreadyExists' or
    'ResourceExistsError' must be swallowed (idempotent)."""
    from azure.core.exceptions import ResourceExistsError

    svc = MagicMock()
    svc.create_table.side_effect = ResourceExistsError("already exists")
    table = MagicMock()

    store = _make_store(table, service_client=svc)
    store.initialize()  # must not raise


# ── close() ───────────────────────────────────────────────────────────────────

def test_close_is_noop():
    table = MagicMock()
    store = _make_store(table)
    store.close()  # must not raise
    store.close()  # idempotent


# ── _to_commitment() round-trip ───────────────────────────────────────────────

def test_to_commitment_maps_entity_fields():
    from agent_sdk.contrib.commitments.azure_table import AzureTableCommitmentStore

    commitment_id = str(uuid.uuid4())
    entity = _make_entity(
        commitment_id,
        tool="greet",
        status="fired",
        identity_binding="user:carol",
        attempts=3,
    )
    entity["args_json"] = json.dumps({"msg": "hello"})
    entity["auth_context_json"] = json.dumps({"home_account_id": "oid"})

    result = AzureTableCommitmentStore._to_commitment(entity)

    assert result.id == commitment_id
    assert result.tool == "greet"
    assert result.status == "fired"
    assert result.identity_binding == "user:carol"
    assert result.args == {"msg": "hello"}
    assert result.auth_context == {"home_account_id": "oid"}
    assert result.attempts == 3


# ---------------------------------------------------------------------------
# Redteam fix tests — findings from adversarial review
# ---------------------------------------------------------------------------


def test_get_etag_raises_runtime_error_on_missing_etag():
    """Finding 3: _get_etag must raise RuntimeError (not return '*') when no
    ETag is present — a wildcard would silently disable at-most-once semantics."""
    from agent_sdk.contrib.commitments.azure_table import AzureTableCommitmentStore

    # Entity with no metadata attribute at all
    bare_entity = {"PartitionKey": "commitments", "RowKey": "some-id"}

    with pytest.raises(RuntimeError, match="no ETag"):
        AzureTableCommitmentStore._get_etag(bare_entity)


def test_list_odata_escapes_single_quote_in_identity_binding():
    """Finding 5: OData filter injection via single-quote in identity_binding.
    A value like "O'Brien" must not break the filter string."""
    from azure.core.exceptions import ResourceNotFoundError

    table = MagicMock()
    store = _make_store(table)

    # Return an empty list for the query
    table.query_entities.return_value = []

    store.list(identity_binding="O'Brien")

    assert table.query_entities.called
    filter_used = table.query_entities.call_args[0][0]
    # The single quote must be doubled per OData spec
    assert "O''Brien" in filter_used
    # The raw unescaped form must not appear in a way that would break the filter
    assert "O'Brien" not in filter_used.replace("O''Brien", "")
