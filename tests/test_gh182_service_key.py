"""GH-182: 'service' API key kind. Ruling: https://github.com/wailuen/a2a-sdk/issues/182#issuecomment-6193941983"""

from __future__ import annotations

import asyncio
import json
import logging

import httpx
import pytest

from agent_sdk.auth.api_keys import ApiKeyStore
from agent_sdk.credentials.store import NS_API_KEYS


async def _call(app, method, path, token, body=None, headers=None):
    h = {"Authorization": f"Bearer {token}", **(headers or {})}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        if body is not None:
            return await c.request(method, path, headers=h, json=body)
        return await c.request(method, path, headers=h, content=b"{}")


@pytest.fixture
def keys(client):
    ak = client.app.state.auth.api_keys
    return (
        client.app,
        ak.mint("user")[1],
        ak.mint("adm", admin=True)[1],
    )


async def test_admin_mints_service_key_and_list_shows_kind(keys):
    app, _, admin = keys
    r = await _call(app, "POST", "/admin/api/keys", admin, {"label": "svc", "service": True})
    assert r.status_code == 200
    data = r.json()
    assert data["service"] is True and data["admin"] is False
    listed = (await _call(app, "GET", "/admin/api/keys", admin)).json()["keys"]
    by_id = {k["key_id"]: k for k in listed}
    assert by_id[data["key_id"]]["service"] is True
    assert all(k["service"] is False for i, k in by_id.items() if i != data["key_id"])


async def test_service_and_admin_both_refused(keys):
    app, _, admin = keys
    r = await _call(
        app, "POST", "/admin/api/keys", admin, {"label": "x", "service": True, "admin": True}
    )
    assert 400 <= r.status_code < 500


async def test_service_mint_requires_admin(keys):
    app, user, _ = keys
    svc = app.state.auth.api_keys.mint("s", service=True)[1]
    for tok in (user, svc):
        r = await _call(app, "POST", "/admin/api/keys", tok, {"label": "x", "service": True})
        assert r.status_code == 403


async def test_bootstrap_mint_is_admin_only(client):
    auth = client.app.state.auth
    auth.bootstrap._token = "boot-token"
    auth.bootstrap._expires_at = 1e18
    hdr = {"X-Bootstrap-Token": "boot-token"}
    r = await _call(client.app, "POST", "/admin/api/keys", "x", {"label": "b", "service": True}, hdr)
    assert 400 <= r.status_code < 500
    r = await _call(client.app, "POST", "/admin/api/keys", "x", {"label": "b"}, hdr)
    assert r.status_code == 200
    assert r.json()["admin"] is True and r.json()["service"] is False


async def test_service_key_accepted_on_protocol_routes_when_user_key_refused(keys):
    app, user, _ = keys
    svc = app.state.auth.api_keys.mint("s", service=True)[1]
    app.state.auth.idp_disable_api_keys = True
    assert (await _call(app, "GET", "/v1/tasks", user)).status_code == 401
    assert (await _call(app, "GET", "/v1/tasks", svc)).status_code == 200


async def test_service_key_accepted_on_every_require_identity_route(keys):
    from tests.test_gh152_api_key_optout import _call as call2
    from tests.test_gh152_api_key_optout import _covered_routes

    app, user, _ = keys
    svc = app.state.auth.api_keys.mint("s", service=True)[1]
    app.state.auth.idp_disable_api_keys = True
    assert len(_covered_routes(app)) >= 13
    for method, path in _covered_routes(app):
        try:
            r = await asyncio.wait_for(call2(app, method, path, svc), timeout=3)
        except asyncio.TimeoutError:
            continue  # handler is streaming: auth passed
        assert r.status_code != 401, (method, path)


def _admin_routes(app):
    from fastapi.routing import APIRoute

    from agent_sdk.auth.middleware import require_admin

    def walks(dep):
        return any(d.call is require_admin or walks(d) for d in dep.dependencies)

    out = []
    from tests.test_gh152_api_key_optout import _iter_routes

    for r in _iter_routes(app.routes):
        if isinstance(r, APIRoute) and r.path.startswith("/admin/api") and walks(r.dependant):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                out.append((m, r.path))
    return out


async def test_service_key_refused_like_user_key_on_every_admin_route(keys):
    app, user, _ = keys
    svc = app.state.auth.api_keys.mint("s", service=True)[1]
    routes = _admin_routes(app)
    assert len(routes) >= 5
    for flag in (False, True):
        app.state.auth.idp_disable_api_keys = flag
        for method, path in routes:
            p = path.replace("{key_id}", "x").replace("{source}", "s").replace(
                "{field}", "f"
            )
            import re

            p = re.sub(r"\{[^}]+\}", "x", p)
            u = await _call(app, method, p, user)
            s = await _call(app, method, p, svc)
            assert u.status_code == 403, (method, path, u.status_code)
            assert s.status_code == u.status_code, (method, path, s.status_code)


async def test_console_credentials_route_refuses_service_key(keys):
    app, _, _ = keys
    svc = app.state.auth.api_keys.mint("s", service=True)[1]
    r = await _call(app, "GET", "/admin/api/credentials", svc)
    assert r.status_code == 403


async def test_revoked_service_key_stops_working(keys):
    app, _, admin = keys
    kid, svc = app.state.auth.api_keys.mint("s", service=True)
    app.state.auth.idp_disable_api_keys = True
    assert (await _call(app, "GET", "/v1/tasks", svc)).status_code == 200
    assert (await _call(app, "DELETE", f"/admin/api/keys/{kid}", admin)).status_code == 200
    assert (await _call(app, "GET", "/v1/tasks", svc)).status_code == 401


def test_kind_survives_reload_and_legacy_records_are_normal(client):
    ak = client.app.state.auth.api_keys
    kid, svc = ak.mint("s", service=True)
    again = ApiKeyStore(ak._store)
    ident = again.verify(svc)
    assert ident is not None and ident.service is True and ident.admin is False
    assert next(k for k in again.list_keys() if k.key_id == kid).service is True
    legacy_id, legacy = ak.mint("old")
    rec = json.loads(ak._store.get(NS_API_KEYS, legacy_id))
    rec.pop("service", None)
    ak._store.set(NS_API_KEYS, legacy_id, json.dumps(rec))
    assert again.verify(legacy).service is False


def test_mint_service_and_admin_raises(client):
    with pytest.raises(Exception):
        client.app.state.auth.api_keys.mint("x", admin=True, service=True)


async def test_service_mint_logged_without_plaintext(keys, caplog):
    app, _, admin = keys
    with caplog.at_level(logging.INFO, logger="agent_sdk.admin"):
        r = await _call(app, "POST", "/admin/api/keys", admin, {"label": "svc", "service": True})
    plaintext = r.json()["plaintext"]
    assert "service key" in caplog.text
    assert plaintext not in caplog.text


async def test_service_mint_label_is_capped_and_collapsed_in_log(keys, caplog):
    app, _, admin = keys
    label = "a\nb\x1bc" + "x" * 5000
    with caplog.at_level(logging.INFO, logger="agent_sdk.admin"):
        await _call(app, "POST", "/admin/api/keys", admin, {"label": label, "service": True})
    line = next(r.getMessage() for r in caplog.records if "service key" in r.getMessage())
    assert "\n" not in line and "\x1b" not in line
    assert len(line) < 1000
    assert "x" * 5000 not in caplog.text


async def test_service_key_plaintext_never_logged_or_leaked_on_any_path(keys, caplog):
    app, user, admin = keys
    key_id, svc = app.state.auth.api_keys.mint("s", service=True)
    ukey_id, ukey = app.state.auth.api_keys.mint("u2")
    app.state.auth.idp_disable_api_keys = True
    bodies = []
    with caplog.at_level(logging.DEBUG):
        r = await _call(app, "POST", "/admin/api/keys", admin, {"label": "m", "service": True})
        plaintext = r.json()["plaintext"]
        bodies.append((await _call(app, "GET", "/admin/api/keys", admin)).text)
        bodies.append((await _call(app, "DELETE", f"/admin/api/keys/{r.json()['key_id']}", admin)).text)
        s_prot = await _call(app, "GET", "/v1/tasks", plaintext)
        s_admin = await _call(app, "GET", "/admin/api/keys", svc)
        u_prot = await _call(app, "GET", "/v1/tasks", ukey)
        u_admin = await _call(app, "GET", "/admin/api/keys", ukey)
        bodies += [s_prot.text, s_admin.text]
    for secret in (plaintext, svc):
        assert secret not in caplog.text
        assert all(secret not in b for b in bodies)
    assert s_prot.status_code == u_prot.status_code == 401
    assert s_admin.status_code == u_admin.status_code == 403
    assert s_prot.content == u_prot.content
    assert s_admin.content == u_admin.content
    for a, b in ((s_prot, u_prot), (s_admin, u_admin)):
        assert a.headers.get("www-authenticate") == b.headers.get("www-authenticate")
        assert "service" not in a.text.lower()
        assert "service" not in a.headers.get("www-authenticate", "").lower()


async def test_service_key_refused_on_oauth_consent(keys):
    from urllib.parse import urlencode

    from tests.test_gh152_idp_authorize_flow import pkce

    app, user, _ = keys
    svc = app.state.auth.api_keys.mint("s", service=True)[1]
    cb = "https://client.example.com/cb"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        cid = (await c.post("/oauth/register", json={"redirect_uris": [cb]})).json()["client_id"]
        _, challenge = pkce()
        form = {
            "client_id": cid, "redirect_uri": cb, "response_type": "code",
            "code_challenge": challenge, "code_challenge_method": "S256", "state": "st",
        }
        ct = {"Content-Type": "application/x-www-form-urlencoded"}
        results = []
        for token in (svc, user):
            results.append(await c.post(
                "/oauth/authorize", content=urlencode({**form, "api_key": token}), headers=ct))
            results.append(await c.post(
                "/oauth/authorize", content=urlencode(form),
                headers={**ct, "Authorization": f"Bearer {token}"}))
    svc_form, svc_bearer, user_form, user_bearer = results
    for r in results:
        assert r.status_code == 401
        assert "location" not in r.headers
    assert svc_form.status_code == user_form.status_code
    assert svc_bearer.status_code == user_bearer.status_code


async def test_service_key_cannot_read_other_identity_task(keys):
    import uuid

    app, user, admin = keys
    svc = app.state.auth.api_keys.mint("s", service=True)[1]
    body = {"message": {
        "role": "user", "parts": [{"kind": "text", "text": "hi"}], "messageId": uuid.uuid4().hex,
    }}
    r = await _call(app, "POST", "/v1/message:send", user, body)
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    assert (await _call(app, "GET", f"/v1/tasks/{task_id}", user)).status_code == 200
    assert (await _call(app, "GET", f"/v1/tasks/{task_id}", admin)).status_code == 200
    s = await _call(app, "GET", f"/v1/tasks/{task_id}", svc)
    missing = await _call(app, "GET", "/v1/tasks/does-not-exist", svc)
    assert s.status_code == 404
    assert s.content == missing.content


async def test_service_key_cannot_revoke_other_clients_oauth_token(keys):
    app, _, admin = keys
    svc = app.state.auth.api_keys.mint("s", service=True)[1]
    oauth = app.state.oauth
    cb = "https://client.example.com/cb"
    cid = oauth.register_client([cb])["client_id"]
    aud = next(iter(oauth.accepted_audiences))

    def pair():
        return oauth.mint_token_pair(client_id=cid, scope="mcp", audience=aud)

    t1 = pair()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/oauth/revoke", data={"token": t1["access_token"]},
            headers={"Authorization": f"Bearer {svc}"},
        )
        assert r.status_code == 200
        assert oauth.verify(t1["access_token"]) is not None
        r = await c.post(
            "/oauth/revoke", data={"token": t1["refresh_token"]},
            headers={"Authorization": f"Bearer {svc}"},
        )
        assert r.status_code == 200
        assert oauth.verify(t1["access_token"]) is not None
        r = await c.post(
            "/oauth/revoke", data={"token": t1["access_token"]},
            headers={"Authorization": f"Bearer {admin}"},
        )
        assert r.status_code == 200
        assert oauth.verify(t1["access_token"]) is None


async def test_user_key_revoke_behaviour_unchanged(keys):
    app, user, _ = keys
    oauth = app.state.oauth
    cid = oauth.register_client(["https://client.example.com/cb"])["client_id"]
    aud = next(iter(oauth.accepted_audiences))
    t1 = oauth.mint_token_pair(client_id=cid, scope="mcp", audience=aud)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/oauth/revoke", data={"token": t1["access_token"]},
            headers={"Authorization": f"Bearer {user}"},
        )
        assert r.status_code == 200
        assert oauth.verify(t1["access_token"]) is None


def test_identity_positional_order_keeps_service_false():
    from agent_sdk.auth import Identity

    ident = Identity("api_key", "sid", False, "my-label")
    assert ident.label == "my-label"
    assert ident.service is False
