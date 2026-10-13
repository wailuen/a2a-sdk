"""GH-163 — operator revocation of a signed-in user (list + revoke by user)."""

from __future__ import annotations

import logging
from urllib.parse import quote

from agent_sdk.auth.oauth_tokens import _hash

VERIFIER = "v" * 50
REDIRECT = "https://x.example/cb"


def _pair(store, *, user, client="c1"):
    return store.mint_token_pair(
        client_id=client,
        scope="",
        audience=store.canonical_resource,
        user=user,
        label=user,
    )


def test_list_identities_summaries_without_token_material(client):
    store = client.app.state.oauth
    a1 = _pair(store, user="t1:alice")
    _pair(store, user="t1:alice", client="c2")
    b = _pair(store, user="t1:bob")
    rows = {r["user"]: r for r in store.list_identities()}
    assert set(rows) == {"t1:alice", "t1:bob"}
    assert rows["t1:alice"]["families"] == 2
    assert rows["t1:alice"]["client_ids"] == ["c1", "c2"]
    assert rows["t1:bob"]["families"] == 1
    assert rows["t1:alice"]["earliest_created"] <= rows["t1:alice"]["latest_expiry"]
    blob = repr(rows)
    for tok in (a1, b):
        for v in (tok["access_token"], tok["refresh_token"]):
            assert v not in blob and _hash(v) not in blob


def test_list_identities_skips_users_without_user_and_rotated_tombstones(client):
    store = client.app.state.oauth
    _pair(store, user=None)
    pair = _pair(store, user="t1:alice")
    store.rotate_refresh(pair["refresh_token"], client_id="c1")
    rows = store.list_identities()
    assert [r["user"] for r in rows] == ["t1:alice"]
    assert rows[0]["families"] == 1


def test_revoke_user_only_target(client):
    store = client.app.state.oauth
    a1 = _pair(store, user="t1:alice")
    a2 = _pair(store, user="t1:alice", client="c2")
    b = _pair(store, user="t1:bob")
    assert store.verify(a1["access_token"]) is not None
    assert store.revoke_user("t1:alice") == 2
    assert store.verify(a1["access_token"]) is None
    assert store.verify(a2["access_token"]) is None
    assert store.rotate_refresh(a1["refresh_token"], client_id="c1") is None
    assert store.verify(b["access_token"]) is not None
    assert store.rotate_refresh(b["refresh_token"], client_id="c1") is not None
    assert store.revoke_user("t1:alice") == 0
    assert [r["user"] for r in store.list_identities()] == ["t1:bob"]


async def test_admin_list_and_revoke_endpoints(client, caplog):
    store = client.app.state.oauth
    a = _pair(store, user="t1:alice")
    _pair(store, user="t1:bob")
    r = await client.get("/admin/api/oauth/identities")
    assert r.status_code == 200
    body = r.json()
    assert {i["user"] for i in body["identities"]} == {"t1:alice", "t1:bob"}
    assert a["refresh_token"] not in r.text and _hash(a["refresh_token"]) not in r.text
    assert a["access_token"] not in r.text

    with caplog.at_level(logging.INFO, logger="agent_sdk"):
        d = await client.delete(f"/admin/api/oauth/identities/{quote('t1:alice', safe='')}")
    assert d.status_code == 200
    assert d.json() == {"user": "t1:alice", "revoked": 1}
    assert a["refresh_token"] not in caplog.text and a["access_token"] not in caplog.text
    assert store.rotate_refresh(a["refresh_token"], client_id="c1") is None

    again = await client.delete(f"/admin/api/oauth/identities/{quote('t1:alice', safe='')}")
    assert again.status_code == 200 and again.json()["revoked"] == 0
    assert [i["user"] for i in (await client.get("/admin/api/oauth/identities")).json()["identities"]] == ["t1:bob"]


async def test_non_admin_and_oauth_callers_refused(client):
    store = client.app.state.oauth
    pair = _pair(store, user="t1:alice")
    _, std = client.app.state.auth.api_keys.mint("std", admin=False)
    path = "/admin/api/oauth/identities"
    target = f"{path}/{quote('t1:alice', safe='')}"
    for headers, codes in (
        ({"Authorization": f"Bearer {std}"}, {403}),
        ({"Authorization": f"Bearer {pair['access_token']}"}, {401, 403}),
        ({"Authorization": "Bearer nope"}, {401}),
    ):
        assert (await client.get(path, headers=headers)).status_code in codes
        assert (await client.delete(target, headers=headers)).status_code in codes
    assert store.list_identities()[0]["families"] == 1


def test_revoke_user_burns_unredeemed_codes(client):
    import base64
    import hashlib

    store = client.app.state.oauth
    challenge = base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()

    def code(user):
        return store.mint_code(
            client_id="c1", redirect_uri=REDIRECT, code_challenge=challenge,
            scope="", audience=store.canonical_resource, user=user, label=user,
        )

    alice, bob = code("t1:alice"), code("t1:bob")
    store.revoke_user("t1:alice")
    redeem = dict(client_id="c1", redirect_uri=REDIRECT, code_verifier=VERIFIER)
    assert store.consume_code(alice, **redeem) is None
    assert store.consume_code(bob, **redeem) is not None


def test_drop_user_removes_only_that_users_consent_tickets():
    from types import SimpleNamespace

    from agent_sdk.auth.oidc import IdpFlowStore

    flows = IdpFlowStore()
    flow = SimpleNamespace()
    a = flows.put_consent(flow, user="t1:alice", label=None, binding="b")  # type: ignore[arg-type]
    b = flows.put_consent(flow, user="t1:bob", label=None, binding="b")  # type: ignore[arg-type]
    assert flows.drop_user("t1:alice") == 1
    assert flows.pop_consent(a, "b") is None
    assert flows.pop_consent(b, "b") is not None
