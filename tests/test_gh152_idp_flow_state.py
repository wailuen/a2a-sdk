"""GH-152-B: IdpFlowStore — single-use bounded flow state and consent tickets."""

from __future__ import annotations

import pytest

from agent_sdk.auth import oidc
from agent_sdk.auth.oidc import IdpFlowStore


def _put(store: IdpFlowStore, binding: str = "cookie-1") -> str:
    return store.put(
        params={"client_id": "c1", "redirect_uri": "https://x.example/cb", "state": "s"},
        code_verifier="v" * 43,
        nonce="n1",
        binding=binding,
    )


def test_state_single_use():
    store = IdpFlowStore()
    state = _put(store)
    flow = store.pop(state, "cookie-1")
    assert flow is not None
    assert flow.nonce == "n1"
    assert flow.params["client_id"] == "c1"
    assert store.pop(state, "cookie-1") is None


def test_state_expires_after_ttl(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(oidc, "_now", lambda: now[0])
    store = IdpFlowStore()
    state = _put(store)
    now[0] += 601
    assert store.pop(state, "cookie-1") is None


def test_state_valid_just_before_ttl(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(oidc, "_now", lambda: now[0])
    store = IdpFlowStore()
    state = _put(store)
    now[0] += 599
    assert store.pop(state, "cookie-1") is not None


def test_state_binding_mismatch_burns_entry():
    store = IdpFlowStore()
    state = _put(store)
    assert store.pop(state, "other-cookie") is None
    assert store.pop(state, "cookie-1") is None


def test_state_unknown_returns_none():
    assert IdpFlowStore().pop("nope", "cookie-1") is None


def test_state_store_bounded():
    store = IdpFlowStore(max_entries=3)
    states = [_put(store) for _ in range(5)]
    assert len(store) <= 3
    assert store.pop(states[0], "cookie-1") is None
    assert store.pop(states[-1], "cookie-1") is not None


def test_binding_is_not_stored_raw():
    store = IdpFlowStore()
    state = _put(store, binding="RAW-COOKIE-SENTINEL")
    flow = store._flows[state]
    assert "RAW-COOKIE-SENTINEL" not in repr(flow)


def test_consent_ticket_single_use_and_expiring(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(oidc, "_now", lambda: now[0])
    store = IdpFlowStore()
    state = _put(store)
    flow = store.pop(state, "cookie-1")
    assert flow is not None
    t1 = store.put_consent(flow, user="tid:oid", label="a@b", binding="cookie-1")
    ticket = store.pop_consent(t1, "cookie-1")
    assert ticket is not None
    assert ticket.user == "tid:oid"
    assert ticket.label == "a@b"
    assert ticket.flow.params["client_id"] == "c1"
    assert store.pop_consent(t1, "cookie-1") is None
    t2 = store.put_consent(flow, user="u", label=None, binding="cookie-1")
    now[0] += 301
    assert store.pop_consent(t2, "cookie-1") is None


def test_consent_ticket_cookie_mismatch_burns():
    store = IdpFlowStore()
    flow = store.pop(_put(store), "cookie-1")
    assert flow is not None
    t = store.put_consent(flow, user="u", label=None, binding="cookie-1")
    assert store.pop_consent(t, "attacker") is None
    assert store.pop_consent(t, "cookie-1") is None


def test_consent_store_bounded():
    store = IdpFlowStore(max_entries=2)
    flow = store.pop(_put(store), "cookie-1")
    assert flow is not None
    tickets = [store.put_consent(flow, user="u", label=None, binding="b") for _ in range(4)]
    assert store.pop_consent(tickets[0], "b") is None
    assert store.pop_consent(tickets[-1], "b") is not None


def test_state_is_random_and_long():
    store = IdpFlowStore()
    assert _put(store) != _put(store)
    assert len(_put(store)) >= 32


@pytest.mark.parametrize("bad", ["", "x" * 5000])
def test_pop_rejects_odd_inputs(bad):
    assert IdpFlowStore().pop(bad, "b") is None


def _put_from(store: IdpFlowStore, source: str, binding: str = "cookie-1") -> str:
    return store.put(
        params={"client_id": "c1", "redirect_uri": "https://x.example/cb", "state": "s"},
        code_verifier="v" * 43,
        nonce="n1",
        binding=binding,
        source=source,
    )


def test_one_ip_cannot_evict_another_ips_flows():
    store = IdpFlowStore(max_entries=20, per_source_max=5)
    victim = _put_from(store, "10.0.0.2", binding="victim")
    flood = [_put_from(store, "10.0.0.1") for _ in range(100)]
    assert store.pop(victim, "victim") is not None
    assert store.pop(flood[0], "cookie-1") is None
    assert store.pop(flood[-1], "cookie-1") is not None


def test_many_ips_flood_cannot_evict_smaller_source():
    store = IdpFlowStore(max_entries=20, per_source_max=10)
    victim = _put_from(store, "10.0.0.9", binding="victim")
    for i in range(4):
        for _ in range(10):
            try:
                _put_from(store, f"10.0.1.{i}")
            except oidc.IdpUnavailable:
                pass
    assert len(store) <= 20
    assert store.pop(victim, "victim") is not None


def test_overall_cap_still_enforced_across_sources():
    store = IdpFlowStore(max_entries=10, per_source_max=4)
    for i in range(50):
        try:
            _put_from(store, f"10.0.2.{i}")
        except oidc.IdpUnavailable:
            pass
    assert len(store) <= 10


def test_many_single_flow_sources_cannot_evict_victim():
    store = IdpFlowStore()
    victim = _put_from(store, "203.0.113.5", binding="victim")
    for i in range(1000):
        try:
            _put_from(store, f"198.51.{i // 250}.{i % 250}")
        except oidc.IdpUnavailable:
            pass
    assert store.pop(victim, "victim") is not None


def test_ipv6_slash64_shares_one_quota():
    store = IdpFlowStore()
    victim = _put_from(store, "203.0.113.5", binding="victim")
    for i in range(1000):
        try:
            _put_from(store, f"2001:db8::{i:x}")
        except oidc.IdpUnavailable:
            pass
    assert store.pop(victim, "victim") is not None
    assert len(store) <= 50


def test_ipv4_mapped_ipv6_groups_with_ipv4():
    store = IdpFlowStore(per_source_max=2)
    first = _put_from(store, "203.0.113.7")
    _put_from(store, "::ffff:203.0.113.7")
    _put_from(store, "203.0.113.7")
    assert store.pop(first, "cookie-1") is None


def test_fresh_source_cannot_evict_multi_flow_source_when_full():
    store = IdpFlowStore(max_entries=10, per_source_max=5)
    victims = [_put_from(store, "192.0.2.1", binding=f"v{i}") for i in range(3)]
    for i in range(7):
        _put_from(store, f"10.0.0.{i + 1}")
    with pytest.raises(oidc.IdpUnavailable):
        _put_from(store, "192.0.2.99")
    assert store.pop(victims[0], "v0") is not None


def test_security_doc_and_adr_describe_full_table_refusal():
    """W042-RT004: the prose must match _evict_for (full table refuses a new source)."""
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for rel in ("docs/security.md", "workspace/adr/a003-oauth-idp-sign-in.md"):
        text = (root / rel).read_text()
        assert "temporarily_unavailable" in text, rel
        assert "holding the most" not in text, rel
        assert "No refusal path" not in text, rel
        assert "sees no error" not in text, rel
