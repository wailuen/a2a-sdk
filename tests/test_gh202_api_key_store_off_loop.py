"""GH-202: API-key store calls run off the event loop, one query per listing.
Ruling: https://github.com/wailuen/a2a-sdk/issues/202#issuecomment-6259246006"""

from __future__ import annotations

import asyncio
import json
import threading
import time

import httpx
import pytest

from agent_sdk.auth import api_keys as api_keys_mod
from agent_sdk.auth.api_keys import ApiKeyStore
from agent_sdk.credentials.azure_table import AzureTableCredentialStore
from agent_sdk.credentials.crypto import derive_key, encrypt
from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore
from agent_sdk.credentials.store import NS_API_KEYS, CredentialStore
from agent_sdk.models.errors import AgentError
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

MASTER = "m" * 40


class MinimalStore(CredentialStore):
    def __init__(self) -> None:
        self.data: dict[tuple[str, str], str] = {}

    def get(self, namespace, field):
        return self.data.get((namespace, field))

    def set(self, namespace, field, value):
        self.data[(namespace, field)] = value

    def delete(self, namespace, field):
        self.data.pop((namespace, field), None)

    def list_fields(self, namespace):
        return sorted(f for ns, f in self.data if ns == namespace)

    def close(self):
        pass


class ListItemsStore(MinimalStore):
    """Counts calls; per-key get is a failure."""

    def __init__(self) -> None:
        super().__init__()
        self.list_items_calls = 0
        self.get_calls = 0

    def get(self, namespace, field):
        self.get_calls += 1
        return super().get(namespace, field)

    def list_items(self, namespace):
        self.list_items_calls += 1
        return {f: v for (ns, f), v in self.data.items() if ns == namespace}


def test_base_default_list_items_on_minimal_subclass():
    s = MinimalStore()
    s.set("ns", "a", "1")
    s.set("ns", "b", "2")
    s.set("other", "c", "3")
    assert s.list_items("ns") == {"a": "1", "b": "2"}
    assert s.list_items("empty") == {}


def test_sqlite_list_items(tmp_path):
    st = EncryptedSqliteStore(tmp_path / "c.db", MASTER)
    try:
        st.set("ns", "a", "1")
        st.set("ns", "b", "2")
        st.set("other", "c", "3")
        assert st.list_items("ns") == {"a": "1", "b": "2"}
        assert st.list_items("none") == {}
    finally:
        st.close()


class FakeTable:
    def __init__(self) -> None:
        self.rows: dict[tuple[str, str], str] = {}
        self.query_calls = 0
        self.get_calls = 0

    def query_entities(self, query, parameters=None, **_):
        self.query_calls += 1
        part = parameters["partition_key"]
        return iter(
            [
                {"PartitionKey": p, "RowKey": r, "Value": v}
                for (p, r), v in self.rows.items()
                if p == part
            ]
        )

    def get_entity(self, partition_key, row_key):
        self.get_calls += 1
        return {"Value": self.rows[(partition_key, row_key)]}


def _azure() -> tuple[AzureTableCredentialStore, FakeTable]:
    st = object.__new__(AzureTableCredentialStore)
    table = FakeTable()
    st._table = table  # type: ignore[attr-defined]
    st._cache = {}  # type: ignore[attr-defined]
    st._cache_lock = threading.Lock()  # type: ignore[attr-defined]
    st._aes = AESGCM(derive_key(MASTER, b"s" * 16))  # type: ignore[attr-defined]
    return st, table


def test_azure_list_items_single_query_aad_correct_no_cache():
    st, table = _azure()
    for ns, f, v in [
        (NS_API_KEYS, "k1", "v1"),
        (NS_API_KEYS, "k2", "v2"),
        (NS_API_KEYS, "__check__", "skip"),
        ("other", "x", "y"),
    ]:
        table.rows[(ns, f)] = encrypt(st._aes, ns, f, v).decode()
    assert st.list_items(NS_API_KEYS) == {"k1": "v1", "k2": "v2"}
    assert table.query_calls == 1
    assert table.get_calls == 0
    assert st._cache == {}
    assert st.list_items("__meta__") == {}
    assert table.query_calls == 1


def test_azure_list_items_decrypts_with_row_aad():
    st, table = _azure()
    table.rows[(NS_API_KEYS, "k1")] = encrypt(st._aes, NS_API_KEYS, "other", "v").decode()
    with pytest.raises(AgentError):
        st.list_items(NS_API_KEYS)


def _seed(keys: ApiKeyStore, n: int = 3) -> list[str]:
    ids = [keys.mint(f"k{i}")[0] for i in range(n)]
    ids.append(keys.mint("adm", admin=True)[0])
    return ids


def test_count_list_revoke_use_one_list_items_and_no_gets():
    store = ListItemsStore()
    keys = ApiKeyStore(store)
    ids = _seed(keys)
    other_admin = keys.mint("adm2", admin=True)[0]
    store.get_calls = 0

    # count() needs names only: one list_fields query, no decrypt, no gets.
    store.list_items_calls = 0
    assert keys.count() == 5
    assert store.list_items_calls == 0
    assert store.get_calls == 0

    store.list_items_calls = 0
    listed = keys.list_keys()
    assert len(listed) == 5
    assert {k.label for k in listed} >= {"k0", "adm", "adm2"}
    assert store.list_items_calls == 1
    assert store.get_calls == 0

    store.list_items_calls = 0
    store.get_calls = 0
    keys.revoke(ids[-1])  # admin, another admin exists
    assert store.list_items_calls == 1
    assert store.get_calls == 1  # only the target record
    assert (NS_API_KEYS, ids[-1]) not in store.data
    assert other_admin


def test_last_admin_refused():
    store = ListItemsStore()
    keys = ApiKeyStore(store)
    admin_id, _ = keys.mint("only", admin=True)
    keys.mint("user")
    with pytest.raises(AgentError):
        keys.revoke(admin_id)
    assert (NS_API_KEYS, admin_id) in store.data


def test_verify_last_used_throttle(monkeypatch):
    store = MinimalStore()
    keys = ApiKeyStore(store)
    key_id, token = keys.mint("k")
    clock = [1_000_000.0]
    monkeypatch.setattr(api_keys_mod.time, "time", lambda: clock[0])
    writes: list[str] = []
    real_set = store.set
    monkeypatch.setattr(store, "set", lambda ns, f, v: (writes.append(f), real_set(ns, f, v)))

    assert keys.verify(token) is not None
    assert len(writes) == 1
    clock[0] += 30
    assert keys.verify(token) is not None
    assert len(writes) == 1
    clock[0] += 31
    assert keys.verify(token) is not None
    assert len(writes) == 2
    assert json.loads(store.data[(NS_API_KEYS, key_id)])["last_used"] == clock[0]
    assert keys.verify(token + "x") is None


class SlowStore(ListItemsStore):
    """Only the namespace scans (list_items, list_fields) are slow, so auth
    (which uses get) stays fast and the slow window is exactly the code under
    test. Both record their thread in list_items_threads."""

    delay = 0.0

    def __init__(self) -> None:
        super().__init__()
        self.list_items_threads: list[int] = []

    def list_items(self, namespace):
        self.list_items_threads.append(threading.get_ident())
        time.sleep(self.delay)
        return super().list_items(namespace)

    def list_fields(self, namespace):
        self.list_items_threads.append(threading.get_ident())
        time.sleep(self.delay)
        return super().list_fields(namespace)


async def _run_with_probe(client, method, path, *, admins=1):
    app = client.app
    slow = SlowStore()
    keys = ApiKeyStore(slow)
    admin_ids = [keys.mint(f"adm{i}", admin=True) for i in range(admins)]
    app.state.auth.api_keys = keys
    headers = {"Authorization": f"Bearer {admin_ids[0][1]}"}
    path = path.replace("{admin}", admin_ids[-1][0])
    # warm up auth so last_used is fresh and verify does no store writes
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        await c.get("/health")
        keys.verify(admin_ids[0][1])
        slow.list_items_threads.clear()
        slow.delay = 0.5
        loop_thread = threading.get_ident()

        async def target():
            t0 = time.monotonic()
            r = await c.request(method, path, headers=headers)
            return r, time.monotonic() - t0

        async def health():
            await asyncio.sleep(0.1)
            t0 = time.monotonic()
            r = await c.get("/health")
            return r, time.monotonic() - t0

        (tr, ttime), (hr, htime) = await asyncio.gather(target(), health())
    assert hr.status_code == 200
    assert htime < 0.3, htime
    assert ttime >= 0.5
    assert slow.list_items_threads, "list_items was never called"
    assert loop_thread not in slow.list_items_threads
    return tr


async def test_admin_listing_does_not_block_event_loop(client):
    r = await _run_with_probe(client, "GET", "/admin/api/keys")
    assert r.status_code == 200 and r.json()["count"] == 1


async def test_admin_revoke_does_not_block_event_loop(client):
    r = await _run_with_probe(client, "DELETE", "/admin/api/keys/{admin}", admins=2)
    assert r.status_code == 200


async def test_admin_overview_does_not_block_event_loop(client):
    r = await _run_with_probe(client, "GET", "/admin/api/overview")
    assert r.status_code == 200
    assert r.json()["keys"]["count"] == 1


async def test_admin_revoke_error_mapping_unchanged(client):
    app = client.app
    keys = ApiKeyStore(ListItemsStore())
    admin_id, admin_token = keys.mint("only", admin=True)
    app.state.auth.api_keys = keys
    h = {"Authorization": f"Bearer {admin_token}"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.delete(f"/admin/api/keys/{admin_id}", headers=h)
        assert r.status_code == 400
        assert "last admin key" in r.json()["detail"]
        r = await c.delete("/admin/api/keys/deadbeef", headers=h)
        assert r.status_code == 404
