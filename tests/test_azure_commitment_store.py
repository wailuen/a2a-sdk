"""AzureTableCommitmentStore — unit tests using in-memory fakes for the Azure Table SDK.

All Azure SDK calls are intercepted via in-memory fake clients so these tests
run without azure-data-tables or azure-identity installed.

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

import contextlib
import json
import sys
import uuid
from datetime import datetime, timedelta, timezone
from types import ModuleType, SimpleNamespace
from typing import Any

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


# ── lightweight call-tracking spy ─────────────────────────────────────────────


class _CallArgs:
    """Minimal stand-in for unittest.mock.call returned by call_args.

    Supports both attribute-style (.args, .kwargs) and index-style access:
    - call_args[0]  → positional args tuple  (mirroring MagicMock.call_args[0])
    - call_args[1]  → keyword args dict      (mirroring MagicMock.call_args[1])
    - call_args.args    → positional args tuple
    - call_args.kwargs  → keyword args dict
    """

    def __init__(self, args: tuple, kwargs: dict) -> None:
        self._args = args
        self._kwargs = kwargs

    def __getitem__(self, index: int) -> Any:
        if index == 0:
            return self._args
        if index == 1:
            return self._kwargs
        raise IndexError(f"_CallArgs index out of range: {index}")

    @property
    def args(self) -> tuple:
        return self._args

    @property
    def kwargs(self) -> dict:
        return self._kwargs


class _MethodSpy:
    """Callable that records calls and supports side_effect / return_value.

    Compatible subset of unittest.mock.MagicMock's call-inspection API:
    - call_count
    - call_args (last call)
    - assert_not_called()
    - side_effect: Exception instance/class → raise; list → pop front each call;
                   callable → call with same args
    - return_value: returned when no side_effect raises
    """

    def __init__(self, return_value: Any = None, side_effect: Any = None) -> None:
        self.call_count: int = 0
        self.call_args: _CallArgs | None = None
        self._all_call_args: list[_CallArgs] = []
        self.return_value = return_value
        self.side_effect = side_effect

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self.call_count += 1
        ca = _CallArgs(args, kwargs)
        self.call_args = ca
        self._all_call_args.append(ca)

        effect = self.side_effect
        if effect is not None:
            if isinstance(effect, list):
                item = effect.pop(0)
                if isinstance(item, BaseException) or (
                    isinstance(item, type) and issubclass(item, BaseException)
                ):
                    raise item if isinstance(item, BaseException) else item()
                elif callable(item):
                    return item(*args, **kwargs)
                else:
                    return item
            elif isinstance(effect, BaseException):
                raise effect
            elif isinstance(effect, type) and issubclass(effect, BaseException):
                raise effect()
            elif callable(effect):
                return effect(*args, **kwargs)
        return self.return_value

    def assert_not_called(self) -> None:
        if self.call_count != 0:
            raise AssertionError(
                f"Expected not called, but was called {self.call_count} time(s)."
            )


# ── in-memory fake Azure Table client ────────────────────────────────────────


class _FakeTableClient:
    """In-memory dict-backed Azure Table client with call recording.

    Supports create_entity, get_entity, update_entity, delete_entity, and
    query_entities. All methods record calls for assertion inspection.

    ETag concurrency: update_entity checks the etag kwarg against the stored
    entity's etag; if mismatched, raises ResourceModifiedError (only when
    match_condition is set). Tests can pre-configure side_effect on individual
    methods to override behaviour for specific scenarios.
    """

    def __init__(self, initial_entities: list[_FakeEntity] | None = None) -> None:
        # Keyed by RowKey.
        self._store: dict[str, _FakeEntity] = {}
        self._etag_counter: int = 0

        # Per-method spies — tests can set .side_effect / .return_value on them.
        self.create_entity = _MethodSpy(side_effect=self._do_create_entity)
        self.get_entity = _MethodSpy(side_effect=self._do_get_entity)
        self.update_entity = _MethodSpy(side_effect=self._do_update_entity)
        self.delete_entity = _MethodSpy(side_effect=self._do_delete_entity)
        self.query_entities = _MethodSpy(side_effect=self._do_query_entities)

        if initial_entities:
            for e in initial_entities:
                self._store[e["RowKey"]] = e

    # ── internal implementations ──

    def _new_etag(self) -> str:
        self._etag_counter += 1
        return f"W/\"etag-{self._etag_counter}\""

    def _not_found(self) -> Exception:
        exc_cls = sys.modules["azure.core.exceptions"].ResourceNotFoundError
        return exc_cls("not found")

    def _do_create_entity(self, entity: dict, **kwargs: Any) -> None:
        key = entity["RowKey"]
        etag = self._new_etag()
        stored = _FakeEntity(entity, etag=etag)
        self._store[key] = stored

    def _do_get_entity(self, partition_key: str, row_key: str, **kwargs: Any) -> _FakeEntity:
        if row_key not in self._store:
            raise self._not_found()
        return self._store[row_key]

    def _do_update_entity(self, entity: dict, *, etag: str | None = None,
                          match_condition: Any = None, mode: Any = None, **kwargs: Any) -> None:
        key = entity["RowKey"]
        if key not in self._store:
            exc_cls = sys.modules["azure.core.exceptions"].ResourceNotFoundError
            raise exc_cls("not found")
        if etag is not None and match_condition is not None:
            stored_etag = self._store[key].metadata.get("etag", "")
            if etag != stored_etag:
                exc_cls = sys.modules["azure.core.exceptions"].ResourceModifiedError
                raise exc_cls("ETag mismatch")
        new_etag = self._new_etag()
        stored = _FakeEntity(entity, etag=new_etag)
        self._store[key] = stored

    def _do_delete_entity(self, partition_key: str, row_key: str, **kwargs: Any) -> None:
        if row_key not in self._store:
            raise self._not_found()
        del self._store[row_key]

    def _do_query_entities(self, filter_str: str, *, parameters: dict | None = None,
                           results_per_page: int | None = None, **kwargs: Any):
        # Return a copy of all stored entities (OData filtering is not simulated;
        # the store returns everything and the real code applies limits/sorting).
        return iter(list(self._store.values()))

    # ── override helpers for conflict-simulation tests ────────────────────────

    def set_query_result(self, entities: list[_FakeEntity]) -> None:
        """Override query_entities to return a fixed list (for conflict tests)."""
        captured = list(entities)

        def _fixed_query(filter_str: str, *, parameters: dict | None = None,
                         results_per_page: int | None = None, **kwargs: Any):
            return iter(captured)

        self.query_entities = _MethodSpy(side_effect=_fixed_query)

    def set_update_side_effect(self, effects: list | Exception | None) -> None:
        """Configure update_entity side_effect for conflict-simulation tests."""
        if isinstance(effects, list):
            self.update_entity = _MethodSpy(side_effect=list(effects))
        else:
            self.update_entity = _MethodSpy(side_effect=effects)

    def set_get_side_effect(self, effect: Exception) -> None:
        """Configure get_entity to raise on next call."""
        self.get_entity = _MethodSpy(side_effect=effect)

    def set_get_return_value(self, entity: _FakeEntity) -> None:
        """Configure get_entity to return a fixed entity."""
        self.get_entity = _MethodSpy(return_value=entity)


class _FakeServiceClient:
    """In-memory Azure TableServiceClient fake."""

    def __init__(self, table_client: _FakeTableClient | None = None) -> None:
        self._table_client = table_client or _FakeTableClient()
        self.create_table = _MethodSpy(side_effect=self._do_create_table)
        self.get_table_client = _MethodSpy(return_value=self._table_client)

    def _do_create_table(self, table_name: str, **kwargs: Any) -> None:
        pass  # no-op; tables always "exist" in memory


# ── factory for the store under test ─────────────────────────────────────────

def _make_store(
    table_client: _FakeTableClient,
    service_client: _FakeServiceClient | None = None,
):
    """Return an AzureTableCommitmentStore wired to in-memory fake clients.

    Uses __new__ to bypass __init__ (and the Azure SDK constructor chain),
    then manually injects _table and _service.
    """
    from agent_sdk.contrib.commitments.azure_table import AzureTableCommitmentStore

    store = AzureTableCommitmentStore.__new__(AzureTableCommitmentStore)
    store._table_name = "agentcommitments"
    store._table = table_client
    store._service = service_client or _FakeServiceClient(table_client)
    return store


# ── context manager for factory tests (replaces patch for constructor-level intercepts) ──


@contextlib.contextmanager
def _stub_azure_constructors(
    service_client: _FakeServiceClient | None = None,
    stub_require: bool = True,
):
    """Temporarily replace Azure SDK constructors in sys.modules so that
    AzureTableCommitmentStore.__init__ uses our fakes instead of real Azure clients.

    Restores originals on exit.
    """
    svc = service_client or _FakeServiceClient()
    tables_mod = sys.modules.get("azure.data.tables")
    identity_mod = sys.modules.get("azure.identity")
    azure_utils_mod = sys.modules.get("agent_sdk.contrib.azure_utils")

    # Save originals
    orig_tsc = getattr(tables_mod, "TableServiceClient", None) if tables_mod else None
    orig_dac = getattr(identity_mod, "DefaultAzureCredential", None) if identity_mod else None
    orig_req = getattr(azure_utils_mod, "require_azure_packages", None) if azure_utils_mod else None

    class _FakeTSC:
        @staticmethod
        def from_connection_string(cs: str, **kwargs: Any) -> _FakeServiceClient:
            return svc

        def __init__(self, endpoint: str = "", credential: Any = None, **kwargs: Any) -> None:
            pass

        def get_table_client(self, table_name: str) -> _FakeTableClient:
            return svc.get_table_client(table_name)

    class _FakeDAC:
        pass

    try:
        if tables_mod and orig_tsc is not None:
            tables_mod.TableServiceClient = _FakeTSC  # type: ignore[attr-defined]
        if identity_mod and orig_dac is not None:
            identity_mod.DefaultAzureCredential = _FakeDAC  # type: ignore[attr-defined]
        if stub_require and azure_utils_mod and orig_req is not None:
            azure_utils_mod.require_azure_packages = lambda: None  # type: ignore[attr-defined]
        yield svc
    finally:
        if tables_mod and orig_tsc is not None:
            tables_mod.TableServiceClient = orig_tsc
        if identity_mod and orig_dac is not None:
            identity_mod.DefaultAzureCredential = orig_dac
        if stub_require and azure_utils_mod and orig_req is not None:
            azure_utils_mod.require_azure_packages = orig_req


# ── 1. add() ──────────────────────────────────────────────────────────────────

def test_add_happy_path_calls_create_entity():
    table = _FakeTableClient()
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
    table = _FakeTableClient()
    store = _make_store(table)

    with pytest.raises(ValueError, match="secret"):
        store.add(tool="send", args={"api_key": "s3cr3t"}, fire_at=_future())

    table.create_entity.assert_not_called()


def test_add_normalizes_fire_at_to_utc():
    table = _FakeTableClient()
    store = _make_store(table)

    store.add(tool="t", args={}, fire_at="2099-06-01T10:00:00+05:00")

    entity_arg = table.create_entity.call_args[0][0]
    assert entity_arg["fire_at"] == "2099-06-01T05:00:00Z"


def test_add_blank_identity_binding_raises():
    table = _FakeTableClient()
    store = _make_store(table)

    for blank in ("", "   "):
        with pytest.raises(ValueError):
            store.add(tool="t", args={}, fire_at=_future(), identity_binding=blank)


def test_add_auth_context_secrets_are_redacted():
    table = _FakeTableClient()
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

    table = _FakeTableClient()
    # Pre-populate store with a _FakeEntity that has the same etag as entity
    table._store[commitment_id] = entity

    # First call: update succeeds normally
    store = _make_store(table)
    claimed1 = store.claim_due(now="2099-01-01T00:00:00Z")

    # Reset to simulate second caller seeing the same original entity (now with
    # a changed etag from the first claim). We override update_entity to raise.
    table.set_query_result([entity])
    table.set_update_side_effect(ResourceModifiedError("conflict"))
    claimed2 = store.claim_due(now="2099-01-01T00:00:00Z")

    assert len(claimed1) == 1
    assert claimed1[0].id == commitment_id
    assert len(claimed2) == 0  # second caller lost the race


def test_claim_due_only_returns_due_pending():
    """Entities with status != pending or fire_at in future are not returned
    (the filter_expr is forwarded to query_entities)."""
    table = _FakeTableClient()
    # query_entities returns empty list (all filtered by the OData filter)
    table.set_query_result([])

    store = _make_store(table)
    result = store.claim_due()

    assert result == []
    # Verify parameterized filter expression and parameters dict
    call_args = table.query_entities.call_args
    filter_str = call_args[0][0]
    params = call_args.kwargs["parameters"]
    assert "status eq @status" in filter_str
    assert "fire_at le @now" in filter_str
    assert params["status"] == "pending"
    assert params["partition_key"] == "commitments"


def test_claim_due_increments_attempts():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="pending", fire_at=_past(), attempts=2)

    table = _FakeTableClient()
    table._store[commitment_id] = entity
    table.set_query_result([entity])

    store = _make_store(table)
    claimed = store.claim_due()

    assert claimed[0].attempts == 3


# ── 3. mark_fired() ───────────────────────────────────────────────────────────

def test_mark_fired_returns_true_on_success():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="firing")

    table = _FakeTableClient()
    table.set_get_return_value(entity)
    table._store[commitment_id] = entity

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

    table = _FakeTableClient()
    table.set_get_return_value(entity)

    store = _make_store(table)
    result = store.mark_fired(commitment_id)

    assert result is False
    table.update_entity.assert_not_called()


def test_mark_fired_returns_false_when_entity_missing():
    from azure.core.exceptions import ResourceNotFoundError

    table = _FakeTableClient()
    table.set_get_side_effect(ResourceNotFoundError("not found"))

    store = _make_store(table)
    result = store.mark_fired("nonexistent-id")

    assert result is False


def test_mark_fired_returns_false_on_concurrent_update():
    """If another replica transitions the row first, IfNotModified raises
    ResourceModifiedError — mark_fired must return False."""
    from azure.core.exceptions import ResourceModifiedError

    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="firing")

    table = _FakeTableClient()
    table.set_get_return_value(entity)
    table._store[commitment_id] = entity
    table.set_update_side_effect(ResourceModifiedError("conflict"))

    store = _make_store(table)
    result = store.mark_fired(commitment_id)

    assert result is False


# ── 4. mark_failed() bearer-scrub + truncation ────────────────────────────────

def test_mark_failed_scrubs_bearer_and_truncates_reason():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="firing")

    table = _FakeTableClient()
    table.set_get_return_value(entity)
    table._store[commitment_id] = entity

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

    table = _FakeTableClient()
    table.set_get_return_value(entity)
    table._store[commitment_id] = entity

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

    table = _FakeTableClient()
    table.set_get_return_value(entity)

    store = _make_store(table)
    result = store.cancel(commitment_id, identity_binding="user:bob")

    assert result is False
    table.update_entity.assert_not_called()


def test_cancel_correct_identity_returns_true():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="pending", identity_binding="user:alice")

    table = _FakeTableClient()
    table.set_get_return_value(entity)
    table._store[commitment_id] = entity

    store = _make_store(table)
    result = store.cancel(commitment_id, identity_binding="user:alice")

    assert result is True
    entity_arg = table.update_entity.call_args[0][0]
    assert entity_arg["status"] == "cancelled"


def test_cancel_already_not_pending_returns_false():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, status="firing")  # not pending

    table = _FakeTableClient()
    table.set_get_return_value(entity)

    store = _make_store(table)
    result = store.cancel(commitment_id)

    assert result is False
    table.update_entity.assert_not_called()


def test_cancel_missing_entity_returns_false():
    from azure.core.exceptions import ResourceNotFoundError

    table = _FakeTableClient()
    table.set_get_side_effect(ResourceNotFoundError("not found"))

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

    table = _FakeTableClient()
    table._store[e1["RowKey"]] = e1
    table._store[e2["RowKey"]] = e2
    table.set_query_result([e1, e2])
    table.set_update_side_effect([ResourceModifiedError("conflict"), None])

    store = _make_store(table)
    count = store.reap_stale_firing(lease_seconds=0)

    assert count == 1  # only the successful update is counted
    assert table.update_entity.call_count == 2


def test_reap_stale_firing_returns_zero_on_no_candidates():
    table = _FakeTableClient()
    table.set_query_result([])

    store = _make_store(table)
    count = store.reap_stale_firing(lease_seconds=300)

    assert count == 0


# ── 7. get() returns None on missing entity ────────────────────────────────────

def test_get_returns_none_on_missing_entity():
    from azure.core.exceptions import ResourceNotFoundError

    table = _FakeTableClient()
    table.set_get_side_effect(ResourceNotFoundError("not found"))

    store = _make_store(table)
    result = store.get("nonexistent-id")

    assert result is None


def test_get_returns_commitment_when_found():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, tool="ping", status="pending")

    table = _FakeTableClient()
    table.set_get_return_value(entity)

    store = _make_store(table)
    result = store.get(commitment_id)

    assert result is not None
    assert result.id == commitment_id
    assert result.tool == "ping"
    assert result.status == "pending"


def test_get_identity_binding_mismatch_returns_none():
    commitment_id = str(uuid.uuid4())
    entity = _make_entity(commitment_id, identity_binding="user:alice")

    table = _FakeTableClient()
    table.set_get_return_value(entity)

    store = _make_store(table)
    result = store.get(commitment_id, identity_binding="user:bob")

    assert result is None


# ── 8. list() filtering ────────────────────────────────────────────────────────

def test_list_filters_by_identity_binding():
    alice_id = str(uuid.uuid4())
    alice_entity = _make_entity(alice_id, identity_binding="user:alice")

    table = _FakeTableClient()
    # Only alice's entity is returned (OData filter applied server-side)
    table.set_query_result([alice_entity])

    store = _make_store(table)
    results = store.list(identity_binding="user:alice")

    assert len(results) == 1
    assert results[0].identity_binding == "user:alice"

    # Verify filter expression uses parameterized form
    call_filter = table.query_entities.call_args[0][0]
    call_params = table.query_entities.call_args.kwargs["parameters"]
    assert "identity_binding eq @identity_binding" in call_filter
    assert call_params["identity_binding"] == "user:alice"
    assert call_params["partition_key"] == "commitments"


def test_list_filters_by_status():
    entity = _make_entity(status="pending")

    table = _FakeTableClient()
    table.set_query_result([entity])

    store = _make_store(table)
    results = store.list(status="pending")

    assert len(results) == 1
    assert results[0].status == "pending"

    call_filter = table.query_entities.call_args[0][0]
    call_params = table.query_entities.call_args.kwargs["parameters"]
    assert "status eq @status" in call_filter
    assert call_params["status"] == "pending"
    assert call_params["partition_key"] == "commitments"


def test_list_parameterizes_status_filter():
    table = _FakeTableClient()
    table.set_query_result([])

    store = _make_store(table)
    malicious = "pending' or status ne 'pending"
    assert store.list(status=malicious) == []

    call_filter = table.query_entities.call_args[0][0]
    call_params = table.query_entities.call_args.kwargs["parameters"]
    assert malicious not in call_filter
    assert call_params["status"] == malicious


def test_list_respects_limit():
    entities = [_make_entity() for _ in range(5)]
    # Assign distinct created_at values
    for i, e in enumerate(entities):
        e["created_at"] = f"2026-01-0{i+1}T00:00:00Z"

    table = _FakeTableClient()
    table.set_query_result(entities)

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

    table = _FakeTableClient()
    table.set_query_result([e1, e2, e3])

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

    with _stub_azure_constructors():
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

    with _stub_azure_constructors():
        from agent_sdk.contrib.commitments.azure_table import (
            AzureTableCommitmentStore,
            create_commitment_backend,
        )

        result = create_commitment_backend(settings)

    assert isinstance(result, AzureTableCommitmentStore)
    assert result._table_name == "myprefixcommitments"


# ── initialize() ──────────────────────────────────────────────────────────────

def test_initialize_creates_table():
    table = _FakeTableClient()
    svc = _FakeServiceClient(table)

    store = _make_store(table, service_client=svc)
    store.initialize()

    assert svc.create_table.call_count == 1
    assert svc.create_table.call_args[0][0] == "agentcommitments"


def test_initialize_is_idempotent_on_already_exists():
    """create_table raising an error containing 'TableAlreadyExists' or
    'ResourceExistsError' must be swallowed (idempotent)."""
    from azure.core.exceptions import ResourceExistsError

    table = _FakeTableClient()
    svc = _FakeServiceClient(table)
    svc.create_table = _MethodSpy(side_effect=ResourceExistsError("already exists"))

    store = _make_store(table, service_client=svc)
    store.initialize()  # must not raise


# ── close() ───────────────────────────────────────────────────────────────────

def test_close_is_noop():
    table = _FakeTableClient()
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


def test_list_parameterizes_single_quote_in_identity_binding():
    """The SDK passes raw values via parameters dict; azure-data-tables applies
    OData escaping client-side. The raw value must not appear in the filter template."""
    table = _FakeTableClient()
    store = _make_store(table)

    # Return an empty list for the query
    table.set_query_result([])

    store.list(identity_binding="O'Brien")

    assert table.query_entities.call_count >= 1
    filter_used = table.query_entities.call_args[0][0]
    params = table.query_entities.call_args.kwargs["parameters"]
    assert "identity_binding eq @identity_binding" in filter_used
    assert "O'Brien" not in filter_used
    assert params["identity_binding"] == "O'Brien"
