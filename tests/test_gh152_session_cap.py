"""GH-152-C: absolute session (family) cap and require_user."""

from __future__ import annotations

import base64
import hashlib

import pytest

from agent_sdk.auth import oauth_tokens
from agent_sdk.auth.oauth_tokens import OAuthTokenStore

VERIFIER = "v" * 50
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).rstrip(b"=").decode()
)
HOUR = 3600


@pytest.fixture
def clock(monkeypatch):
    state = {"t": 1_000_000.0}
    monkeypatch.setattr(oauth_tokens, "_now", lambda: state["t"])
    return state


def _store(app, **kw) -> OAuthTokenStore:
    return OAuthTokenStore(
        app.state.credential_store,
        issuer="http://test",
        canonical_resource="http://test/mcp",
        **kw,
    )


def _pair(store, user="u"):
    return store.mint_token_pair(
        client_id="c1", scope="", audience="http://test/mcp", user=user, label="L"
    )


def test_family_expires_absolute_despite_rotation(app, clock):
    store = _store(app, session_ttl_seconds=3 * HOUR)
    pair = _pair(store)
    for _ in range(2):
        clock["t"] += HOUR - 60
        pair = store.rotate_refresh(pair["refresh_token"], client_id="c1")
        assert pair is not None
    clock["t"] += 2 * HOUR
    assert store.rotate_refresh(pair["refresh_token"], client_id="c1") is None


def test_access_token_clamped_to_family_expiry(app, clock):
    store = _store(app, session_ttl_seconds=HOUR // 2)
    pair = _pair(store)
    assert pair["expires_in"] <= HOUR // 2
    assert store.verify(pair["access_token"]) is not None
    clock["t"] += HOUR // 2 + 1
    assert store.verify(pair["access_token"]) is None


def test_legacy_userless_refresh_refused_when_user_required(app, clock):
    legacy = _store(app)
    pair = legacy.mint_token_pair(client_id="c1", scope="", audience="http://test/mcp")
    strict = _store(app, session_ttl_seconds=HOUR, require_user=True)
    assert strict.rotate_refresh(pair["refresh_token"], client_id="c1") is None
    assert legacy.rotate_refresh(pair["refresh_token"], client_id="c1") is None


def test_no_family_cap_when_session_ttl_unset(app, clock):
    store = _store(app)
    pair = _pair(store)
    for _ in range(3):
        clock["t"] += 40 * 24 * HOUR
        pair = store.rotate_refresh(pair["refresh_token"], client_id="c1")
        assert pair is not None
