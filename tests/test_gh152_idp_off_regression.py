"""GH-152-D: with AGENT_SDK_OAUTH_IDP=none nothing about the OAuth surface changes."""

from __future__ import annotations

import hashlib
import json
from urllib.parse import urlencode

CB = "https://client.example.com/cb"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}

# Captured from the pre-GH-152-D code (client_id normalised to "CID").
# GOLDEN_PAGE_SHA re-captured for the v0.17.4 consent page redesign
# (routes/_consent_ui.py); headers, CSP and metadata goldens are unchanged.
GOLDEN_PAGE_SHA = "2f845c327d3a9436cb1f7c2e0c9eb7e4522ff7507a0f7fd96b3aae6c14c9eedd"
GOLDEN_HEADERS_SHA = "5f7b58a2285f74070fa7f269df9d18bdc47875025ecf8a5b6f3a0243567d3ea6"
GOLDEN_METADATA = {
    "/.well-known/oauth-protected-resource": "069fbf6e2a3e60df506cdd56b8386b5d06421a38b30dd805b2291db28c2e8ab5",
    "/.well-known/oauth-protected-resource/mcp": "661ef4ff5930e6ba9bc20172830c89cec3316981fe5772c3bc59bf30c94e13cd",
    "/.well-known/oauth-authorization-server": "456c95e48989fc7419c95098ead2a4cca09a0b4e7cdfeae874c0a7539191d876",
}


async def _register(client) -> str:
    r = await client.post("/oauth/register", json={"redirect_uris": [CB], "client_name": "Claude"})
    return r.json()["client_id"]


async def test_idp_off_authorize_page_byte_identical(client):
    cid = await _register(client)
    r = await client.get("/oauth/authorize", params={
        "client_id": cid, "redirect_uri": CB, "response_type": "code",
        "code_challenge": "A" * 43, "code_challenge_method": "S256", "state": "st",
    })
    assert r.status_code == 200
    assert hashlib.sha256(r.text.replace(cid, "CID").encode()).hexdigest() == GOLDEN_PAGE_SHA
    headers = sorted((k, v) for k, v in r.headers.items() if k not in ("content-length", "x-request-id"))
    assert hashlib.sha256(json.dumps(headers).encode()).hexdigest() == GOLDEN_HEADERS_SHA
    assert "set-cookie" not in r.headers


async def test_idp_off_metadata_byte_identical(client):
    for path, sha in GOLDEN_METADATA.items():
        r = await client.get(path)
        assert hashlib.sha256(r.content).hexdigest() == sha, path


async def test_idp_off_idp_routes_404(client):
    assert (await client.get("/oauth/idp/callback", params={"state": "x", "code": "y"})).status_code == 404
    assert (await client.post("/oauth/idp/consent", content="ticket=x", headers=FORM)).status_code == 404


async def test_idp_off_nothing_constructed(client):
    app = client.app
    assert getattr(app.state, "idp_rp", None) is None
    assert getattr(app.state, "idp_flows", None) is None
    assert app.state.auth.idp_disable_api_keys is False
    assert app.state.oauth._session_ttl is None
    assert app.state.oauth._require_user is False


async def test_idp_off_admin_key_approve_and_token_have_no_user(client):
    cid = await _register(client)
    from tests.test_gh152_idp_authorize_flow import pkce
    verifier, challenge = pkce()
    _, key = client.app.state.auth.api_keys.mint("adm", admin=True)
    body = urlencode({
        "client_id": cid, "redirect_uri": CB, "response_type": "code",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "st", "api_key": key,
    })
    r = await client.post("/oauth/authorize", content=body, headers=FORM)
    assert r.status_code == 303
    from urllib.parse import parse_qs, urlparse
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    t = await client.post("/oauth/token", content=urlencode({
        "grant_type": "authorization_code", "code": code, "client_id": cid,
        "redirect_uri": CB, "code_verifier": verifier,
    }), headers=FORM)
    assert t.status_code == 200
    ident = client.app.state.oauth.verify(t.json()["access_token"])
    assert ident is not None and ident.user is None


def test_idp_off_dcr_flood_keeps_consented_client_without_tokens(tmp_path):
    from agent_sdk.auth.oauth_tokens import MAX_CLIENTS, OAuthTokenStore
    from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore

    store = EncryptedSqliteStore(tmp_path / "c.db", "k" * 32)
    oauth = OAuthTokenStore(store, issuer="https://a.example", canonical_resource="https://a.example/mcp")
    org = oauth.register_client([CB], client_name="org")
    oauth.mark_consented(org["client_id"])
    for _ in range(MAX_CLIENTS + 5):
        oauth.register_client([CB])
    assert oauth.get_client(org["client_id"]) is not None
