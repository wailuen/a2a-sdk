"""Client-table cap under IdP sign-in (GH-152).

RT-001 (earlier round): user-consented clients without a live refresh family
stay evictable, so IdP Allow clicks cannot fill the table for good.
RT-002 (round 5): admin-approved clients (``consented``) are never evicted in
any mode — including org clients approved before IdP sign-in existed, which
carry no other marker and lose their userless refresh families when IdP is on.
"""

from __future__ import annotations

import pytest

from agent_sdk.auth.oauth_tokens import MAX_CLIENTS, OAuthTokenStore
from agent_sdk.models.errors import AgentError

URIS = ["https://x.example/cb"]


def _store(app, *, require_user: bool = True) -> OAuthTokenStore:
    return OAuthTokenStore(
        app.state.credential_store, issuer="http://test", canonical_resource="http://test/mcp",
        require_user=require_user,
    )


def test_user_consented_clients_without_tokens_do_not_fill_table(app):
    store = _store(app)
    for _ in range(MAX_CLIENTS):
        store.mark_user_consented(store.register_client(URIS)["client_id"])
    fresh = store.register_client(URIS)
    assert store.get_client(fresh["client_id"]) is not None


def test_user_consented_client_with_live_refresh_is_protected(app):
    store = _store(app)
    live = store.register_client(URIS)["client_id"]
    store.mark_user_consented(live)
    store.mint_token_pair(
        client_id=live, scope="", audience="http://test/mcp", user="u", label="L"
    )
    for _ in range(MAX_CLIENTS + 5):
        store.mark_user_consented(store.register_client(URIS)["client_id"])
    assert store.get_client(live) is not None


def test_table_full_of_live_clients_refuses(app):
    store = _store(app)
    for _ in range(MAX_CLIENTS):
        cid = store.register_client(URIS)["client_id"]
        store.mark_user_consented(cid)
        store.mint_token_pair(
            client_id=cid, scope="", audience="http://test/mcp", user="u", label="L"
        )
    with pytest.raises(AgentError):
        store.register_client(URIS)


def test_pre_upgrade_admin_client_survives_dcr_flood_after_idp_on(app):
    """RT-002: an org client admin-approved before the upgrade (no new marker,
    no live refresh family once IdP is on) must survive an anonymous DCR flood."""
    before = _store(app, require_user=False)
    org = before.register_client(URIS, client_name="org")["client_id"]
    before.mark_consented(org)
    # Simulate the pre-upgrade record shape exactly: only the legacy fields.
    record = before.get_client(org)
    assert set(record) == {
        "client_id", "client_name", "redirect_uris",
        "token_endpoint_auth_method", "consented", "created_at",
    }
    after = _store(app, require_user=True)
    for _ in range(MAX_CLIENTS + 5):
        after.register_client(URIS)
    assert after.get_client(org) is not None


def test_user_consent_does_not_grant_admin_approval(app):
    store = _store(app)
    cid = store.register_client(URIS)["client_id"]
    store.mark_user_consented(cid)
    assert not store.get_client(cid).get("consented")
