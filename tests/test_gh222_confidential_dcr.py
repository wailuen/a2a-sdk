"""GH-222 — confidential DCR (client_secret_post / client_secret_basic)."""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import secrets
from urllib.parse import quote, urlencode

import pytest

REDIRECT = "https://claude.ai/api/mcp/auth_callback"
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def _pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


async def _register(client, method=None, **extra):
    body = {"redirect_uris": [REDIRECT], "client_name": "c", **extra}
    if method is not None:
        body["token_endpoint_auth_method"] = method
    return await client.post("/oauth/register", json=body)


def _basic(cid: str, secret: str) -> dict[str, str]:
    raw = f"{quote(cid, safe='')}:{quote(secret, safe='')}".encode()
    return {"Authorization": "Basic " + base64.b64encode(raw).decode()}


def _code(client, cid: str) -> tuple[str, str]:
    verifier, challenge = _pkce()
    store = client.app.state.oauth
    code = store.mint_code(
        client_id=cid, redirect_uri=REDIRECT, code_challenge=challenge,
        scope="", audience=store.canonical_resource, label="x",
    )
    return code, verifier


def _auth(method: str, cid: str, secret: str | None):
    """(extra form fields, headers) presenting the secret via ``method``."""
    if secret is None:
        return {}, {}
    if method == "client_secret_post":
        return {"client_secret": secret}, {}
    return {}, _basic(cid, secret)


async def _token(client, cid, code, verifier, fields=None, headers=None):
    data = {
        "grant_type": "authorization_code", "code": code, "client_id": cid,
        "redirect_uri": REDIRECT, "code_verifier": verifier, **(fields or {}),
    }
    return await client.post(
        "/oauth/token", content=urlencode(data).encode(), headers={**FORM, **(headers or {})}
    )


async def _refresh(client, cid, rt, fields=None, headers=None):
    data = {"grant_type": "refresh_token", "refresh_token": rt, "client_id": cid, **(fields or {})}
    return await client.post(
        "/oauth/token", content=urlencode(data).encode(), headers={**FORM, **(headers or {})}
    )


async def _revoke(client, cid, token, fields=None, headers=None):
    data = {"token": token, "client_id": cid, **(fields or {})}
    return await client.post(
        "/oauth/revoke",
        content=urlencode(data).encode(),
        headers={**FORM, "Authorization": "", **(headers or {})},
    )


async def _confidential(client, method):
    r = await _register(client, method)
    assert r.status_code == 201, r.text
    body = r.json()
    return body["client_id"], body["client_secret"]


async def test_metadata(client):
    meta = (await client.get("/.well-known/oauth-authorization-server")).json()
    assert meta["token_endpoint_auth_methods_supported"] == [
        "none", "client_secret_post", "client_secret_basic",
    ]
    assert meta["code_challenge_methods_supported"] == ["S256"]


async def test_public_default_unchanged(client):
    body = (await _register(client)).json()
    assert body["token_endpoint_auth_method"] == "none"
    assert "client_secret" not in body
    assert "client_secret_expires_at" not in body
    record = client.app.state.oauth.get_client(body["client_id"])
    assert set(record) == {
        "client_id", "client_name", "redirect_uris",
        "token_endpoint_auth_method", "consented", "created_at",
    }
    explicit = (await _register(client, "none")).json()
    assert explicit["token_endpoint_auth_method"] == "none"


@pytest.mark.parametrize("bad", ["private_key_jwt", "client_secret_jwt", "", 5, None, "NONE"])
async def test_unknown_method_400(client, bad):
    r = await client.post(
        "/oauth/register",
        json={"redirect_uris": [REDIRECT], "token_endpoint_auth_method": bad},
    )
    if bad is None:
        assert r.status_code == 201
        return
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_client_metadata"


@pytest.mark.parametrize("method", ["client_secret_post", "client_secret_basic"])
async def test_confidential_registration_shape(client, method, caplog):
    caplog.set_level(logging.DEBUG)
    r = await _register(client, method)
    body = r.json()
    assert r.status_code == 201
    assert body["token_endpoint_auth_method"] == method
    assert body["client_secret_expires_at"] == 0
    secret = body["client_secret"]
    assert len(secret) >= 43
    record = client.app.state.oauth.get_client(body["client_id"])
    assert record["token_endpoint_auth_method"] == method
    assert record["client_secret_hash"] == hashlib.sha256(secret.encode()).hexdigest()
    assert secret not in json.dumps(record)
    assert secret not in caplog.text
    raw = client.app.state.credential_store.get("__oauth_clients__", body["client_id"])
    assert secret not in raw


@pytest.mark.parametrize("method", ["client_secret_post", "client_secret_basic"])
async def test_confidential_code_token_refresh_revoke(client, method, caplog):
    caplog.set_level(logging.DEBUG)
    cid, secret = await _confidential(client, method)
    fields, headers = _auth(method, cid, secret)
    code, verifier = _code(client, cid)
    r = await _token(client, cid, code, verifier, fields, headers)
    assert r.status_code == 200, r.text
    pair = r.json()
    r2 = await _refresh(client, cid, pair["refresh_token"], fields, headers)
    assert r2.status_code == 200, r2.text
    pair2 = r2.json()
    rv = await _revoke(client, cid, pair2["refresh_token"], fields, headers)
    assert rv.status_code == 200
    assert (await _refresh(client, cid, pair2["refresh_token"], fields, headers)).status_code == 400
    assert secret not in caplog.text


async def test_basic_without_form_client_id(client):
    cid, secret = await _confidential(client, "client_secret_basic")
    code, verifier = _code(client, cid)
    data = {
        "grant_type": "authorization_code", "code": code,
        "redirect_uri": REDIRECT, "code_verifier": verifier,
    }
    r = await client.post(
        "/oauth/token", content=urlencode(data).encode(),
        headers={**FORM, **_basic(cid, secret)},
    )
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("method", ["client_secret_post", "client_secret_basic"])
async def test_bad_secret_fails_everywhere(client, method):
    cid, secret = await _confidential(client, method)
    other = "client_secret_basic" if method == "client_secret_post" else "client_secret_post"
    good_f, good_h = _auth(method, cid, secret)
    pair = None
    cases = {
        "missing": _auth(method, cid, None),
        "wrong": _auth(method, cid, "nope"),
        "other-method": _auth(other, cid, secret),
        "both": ({**_auth("client_secret_post", cid, secret)[0]}, _auth("client_secret_basic", cid, secret)[1]),
    }
    code, verifier = _code(client, cid)
    for name, (f, h) in cases.items():
        r = await _token(client, cid, code, verifier, f, h)
        assert r.status_code == 401, name
        assert r.json()["error"] == "invalid_client", name
        if method == "client_secret_basic":
            assert r.headers["www-authenticate"].startswith("Basic"), name
    # the code was NOT burned by failed client auth
    r = await _token(client, cid, code, verifier, good_f, good_h)
    assert r.status_code == 200
    pair = r.json()
    for name, (f, h) in cases.items():
        r = await _refresh(client, cid, pair["refresh_token"], f, h)
        assert r.status_code == 401, name
        rv = await _revoke(client, cid, pair["refresh_token"], f, h)
        assert rv.status_code == 401, name
    # token survived all failed attempts
    assert (await _refresh(client, cid, pair["refresh_token"], good_f, good_h)).status_code == 200


async def test_basic_urldecodes_credentials(client):
    cid, secret = await _confidential(client, "client_secret_basic")
    # urlsafe secrets contain '-' and '_' only; ensure encoded form round-trips
    code, verifier = _code(client, cid)
    r = await _token(client, cid, code, verifier, {}, _basic(cid, secret))
    assert r.status_code == 200


async def test_public_client_presenting_secret_rejected(client):
    cid = (await _register(client)).json()["client_id"]
    for fields, headers in (({"client_secret": "x"}, {}), ({}, _basic(cid, "x"))):
        code, verifier = _code(client, cid)
        r = await _token(client, cid, code, verifier, fields, headers)
        assert r.status_code == 401
        assert r.json()["error"] == "invalid_client"
    code, verifier = _code(client, cid)
    assert (await _token(client, cid, code, verifier)).status_code == 200


async def test_pkce_still_required_for_confidential(client):
    cid, secret = await _confidential(client, "client_secret_post")
    code, _ = _code(client, cid)
    r = await _token(client, cid, code, "A" * 43, {"client_secret": secret})
    assert r.status_code == 400
    assert r.json()["error"] == "invalid_grant"


async def test_revoke_public_client_id_only_still_works(client):
    cid = (await _register(client)).json()["client_id"]
    code, verifier = _code(client, cid)
    pair = (await _token(client, cid, code, verifier)).json()
    assert (await _revoke(client, cid, pair["refresh_token"])).status_code == 200
    assert (await _refresh(client, cid, pair["refresh_token"])).status_code == 400


async def test_confidential_client_eviction_and_consent_same(client):
    from agent_sdk.auth.oauth_tokens import MAX_CLIENTS

    store = client.app.state.oauth
    cid, _ = await _confidential(client, "client_secret_post")
    store.mark_consented(cid)
    for _ in range(MAX_CLIENTS + 3):
        store.register_client([REDIRECT])
    assert store.get_client(cid)["consented"] is True
    unconsented, _ = await _confidential(client, "client_secret_basic")
    for _ in range(MAX_CLIENTS + 3):
        store.register_client([REDIRECT])
    assert store.get_client(unconsented) is None
