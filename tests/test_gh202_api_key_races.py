"""RT-001/RT-002: verify/revoke run in worker threads; they must not race."""

from __future__ import annotations

import json
import threading
import time

import pytest

from agent_sdk.auth.api_keys import ApiKeyStore
from agent_sdk.credentials.store import NS_API_KEYS
from agent_sdk.models.errors import AgentError
from tests.test_gh202_api_key_store_off_loop import MinimalStore


class DictStore(MinimalStore):
    def list_items(self, namespace):
        return {f: v for (ns, f), v in self.data.items() if ns == namespace}


def test_revoked_key_is_not_resurrected_by_inflight_verify():
    store = DictStore()
    keys = ApiKeyStore(store)
    key_id, token = keys.mint("k", admin=False)
    record = json.loads(store.data[(NS_API_KEYS, key_id)])
    record["last_used"] = time.time() - 3600
    store.data[(NS_API_KEYS, key_id)] = json.dumps(record)

    got_record = threading.Event()
    release = threading.Event()
    real_get = store.get
    first = threading.local()

    def slow_get(namespace, field):
        value = real_get(namespace, field)
        if threading.current_thread().name == "verifier" and not getattr(
            first, "done", False
        ):
            first.done = True
            got_record.set()
            release.wait(5)
        return value

    store.get = slow_get  # type: ignore[method-assign]
    result: list = []
    t = threading.Thread(
        target=lambda: result.append(keys.verify(token)), name="verifier"
    )
    t.start()
    assert got_record.wait(5)
    keys.revoke(key_id)
    release.set()
    t.join(5)

    assert (NS_API_KEYS, key_id) not in store.data
    assert keys.verify(token) is None


def test_concurrent_revokes_cannot_remove_last_two_admins():
    store = DictStore()
    keys = ApiKeyStore(store)
    a, _ = keys.mint("a", admin=True)
    b, _ = keys.mint("b", admin=True)

    barrier = threading.Barrier(2)
    real_list = store.list_items

    def list_items(namespace):
        items = real_list(namespace)
        try:
            barrier.wait(0.5)
        except threading.BrokenBarrierError:
            pass
        return items

    store.list_items = list_items  # type: ignore[method-assign]
    outcomes: list[str] = []

    def run(key_id):
        try:
            keys.revoke(key_id)
            outcomes.append("ok")
        except AgentError:
            outcomes.append("refused")

    threads = [threading.Thread(target=run, args=(k,)) for k in (a, b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(5)

    assert sorted(outcomes) == ["ok", "refused"]
    remaining = [k for (ns, k) in store.data if ns == NS_API_KEYS]
    assert len(remaining) == 1


def test_admin_revoke_scan_does_not_block_touch_of_other_key():
    store = DictStore()
    keys = ApiKeyStore(store)
    admin_a, _ = keys.mint("a", admin=True)
    keys.mint("b", admin=True)
    ids = [keys.mint(f"u{i}")[0] for i in range(20)]
    stale_id, stale_token = next(
        (k, t) for k, t in (keys.mint(f"s{i}") for i in range(40))
        if keys._lock_for(k) is not keys._lock_for(admin_a)
    )
    record = json.loads(store.data[(NS_API_KEYS, stale_id)])
    record["last_used"] = time.time() - 3600
    store.data[(NS_API_KEYS, stale_id)] = json.dumps(record)

    in_scan = threading.Event()
    release = threading.Event()
    real_list = store.list_items

    def slow_list(namespace):
        in_scan.set()
        release.wait(5)
        return real_list(namespace)

    store.list_items = slow_list  # type: ignore[method-assign]
    revoker = threading.Thread(target=lambda: keys.revoke(admin_a))
    revoker.start()
    assert in_scan.wait(5)

    started = time.monotonic()
    result: list = []
    verifier = threading.Thread(target=lambda: result.append(keys.verify(stale_token)))
    verifier.start()
    verifier.join(1.0)
    elapsed = time.monotonic() - started
    release.set()
    revoker.join(5)

    assert not verifier.is_alive()
    assert elapsed < 1.0
    assert result and result[0] is not None
    assert ids
