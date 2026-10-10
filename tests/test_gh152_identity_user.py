"""GH-152-C: Identity.user, user-carrying tokens, per-user isolation."""

from __future__ import annotations

import json

import httpx

from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.auth.oauth_tokens import OAuthTokenStore, verify_pkce_s256
from agent_sdk.common.admission import identity_key
from agent_sdk.credentials.store import NS_OAUTH_REFRESH
from agent_sdk.tasks.memory import InMemoryTaskStore

import base64
import hashlib

VERIFIER = "v" * 50
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)


def _store(app) -> OAuthTokenStore:
    return OAuthTokenStore(
        app.state.credential_store, issuer="http://test", canonical_resource="http://test/mcp"
    )


def _pair(store, *, user=None, label=None, client="c1"):
    code = store.mint_code(
        client_id=client,
        redirect_uri="https://x.example/cb",
        code_challenge=CHALLENGE,
        scope="",
        audience=store.canonical_resource,
        **({"user": user, "label": label} if user is not None else {}),
    )
    meta = store.consume_code(
        code, client_id=client, redirect_uri="https://x.example/cb", code_verifier=VERIFIER
    )
    assert meta is not None
    return meta, store.mint_token_pair(
        client_id=client,
        scope="",
        audience=store.canonical_resource,
        user=meta.get("user"),
        label=meta.get("label"),
    )


def test_identity_keys_unchanged_without_user():
    ident = Identity(kind="oauth", subject="c1")
    assert ident.user is None
    assert ident.binding == ("oauth", "c1")
    assert ident.principal_key == "oauth:c1"
    assert identity_key(ident) == "oauth:c1"


def test_user_changes_binding_and_principal_key():
    ident = Identity(kind="oauth", subject="c1", user="t:o")
    assert ident.binding == ("oauth", "c1|t:o")
    assert isinstance(ident.binding, tuple) and len(ident.binding) == 2
    assert ident.principal_key == "oauth:c1|t:o"
    assert identity_key(ident) == "oauth:c1|t:o"


def test_two_users_same_client_isolated_tasks():
    a = Identity(kind="oauth", subject="c1", user="u-a")
    b = Identity(kind="oauth", subject="c1", user="u-b")
    ts = InMemoryTaskStore()
    task = new_task()
    ts.create(task, a)
    assert ts.get(task.id, a) is not None
    assert ts.get(task.id, b) is None


async def test_two_users_same_client_separate_rate_limits(client):
    from agent_sdk.common.limits import RateLimiter

    app = client.app
    app.state.auth.identity_limiter = RateLimiter(1)
    store = app.state.oauth
    _, pa = _pair(store, user="u-a", label="A")
    _, pb = _pair(store, user="u-b", label="B")

    async def get(tok):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            return await c.get("/v1/tasks", headers={"Authorization": f"Bearer {tok}"})

    assert (await get(pa["access_token"])).status_code == 200
    assert (await get(pa["access_token"])).status_code == 429
    assert (await get(pb["access_token"])).status_code == 200


def test_verify_returns_user(app):
    store = _store(app)
    _, pair = _pair(store, user="t:o", label="Alice")
    ident = store.verify(pair["access_token"])
    assert ident == Identity(kind="oauth", subject="c1", user="t:o", label="Alice")


def test_refresh_keeps_user(app):
    store = _store(app)
    _, pair = _pair(store, user="t:o", label="Alice")
    new = store.rotate_refresh(pair["refresh_token"], client_id="c1")
    assert new is not None
    assert store.verify(new["access_token"]).user == "t:o"


def test_refresh_record_shape_unchanged_without_user(app):
    store = _store(app)
    _, pair = _pair(store)
    h = hashlib.sha256(pair["refresh_token"].encode()).hexdigest()
    rec = json.loads(app.state.credential_store.get(NS_OAUTH_REFRESH, h))
    assert set(rec) == {
        "client_id", "scope", "audience", "family_id", "label",
        "rotated", "created_at", "expires_at",
    }
    assert store.verify(pair["access_token"]).user is None


def test_oauth_user_cannot_revoke_other_users_token(app):
    store = _store(app)
    _, pa = _pair(store, user="u-a")
    _, pb = _pair(store, user="u-b")
    caller_b = store.verify(pb["access_token"])
    store.revoke_by_value(pa["access_token"], caller=caller_b)
    assert store.verify(pa["access_token"]) is not None
    store.revoke_by_value(pa["refresh_token"], caller=caller_b)
    assert store.rotate_refresh(pa["refresh_token"], client_id="c1") is not None
    caller_a = store.verify(pa["access_token"])
    store.revoke_by_value(pa["access_token"], caller=caller_a)
    assert store.verify(pa["access_token"]) is None


def test_userless_client_revoke_unchanged(app):
    store = _store(app)
    _, p = _pair(store)
    store.revoke_by_value(p["access_token"], caller=Identity(kind="oauth", subject="c1"))
    assert store.verify(p["access_token"]) is None


def test_pkce_helper_still_importable():
    assert verify_pkce_s256(VERIFIER, CHALLENGE)
