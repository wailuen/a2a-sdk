"""GH-152-C: AuthRuntime.idp_disable_api_keys (non-admin API keys only)."""

from __future__ import annotations

import httpx
import pytest

from agent_sdk.auth.middleware import require_identity

ADR_D3_MIN_ROUTES = 13


def _iter_routes(routes):
    for r in routes:
        inner = getattr(r, "original_router", None)
        if inner is not None:
            yield from _iter_routes(inner.routes)
        else:
            yield r


def _covered_routes(app):
    def walks(dep):
        return any(d.call is require_identity or walks(d) for d in dep.dependencies)

    out = []
    for r in _iter_routes(app.routes):
        dep = getattr(r, "dependant", None)
        if dep is not None and walks(dep):
            for m in sorted(r.methods - {"HEAD", "OPTIONS"}):
                out.append((m, r.path))
    return out


async def _call(app, method, path, token):
    path = path.replace("{task_id}", "t1").replace("{session_id}", "s1")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        return await c.request(
            method, path, headers={"Authorization": f"Bearer {token}"}, content=b"{}"
        )


@pytest.fixture
def keys(client):
    ak = client.app.state.auth.api_keys
    return client.app, ak.mint("user", admin=False)[1], ak.mint("adm", admin=True)[1]


def test_covered_route_set_is_complete(client):
    assert len(_covered_routes(client.app)) >= ADR_D3_MIN_ROUTES


async def test_user_api_key_rejected_on_every_require_identity_route(keys):
    app, user_key, _ = keys
    routes = _covered_routes(app)
    assert len(routes) >= ADR_D3_MIN_ROUTES
    app.state.auth.idp_disable_api_keys = True
    for method, path in routes:
        r = await _call(app, method, path, user_key)
        assert r.status_code == 401, (method, path, r.status_code)
        assert "resource_metadata" in r.headers["www-authenticate"]


async def test_admin_key_still_accepted_on_protocol_routes_with_switch_on(keys):
    app, _, admin_key = keys
    app.state.auth.idp_disable_api_keys = True
    r = await _call(app, "GET", "/v1/tasks", admin_key)
    assert r.status_code == 200


async def test_admin_routes_still_accept_admin_key_with_switch_on(keys):
    app, user_key, admin_key = keys
    app.state.auth.idp_disable_api_keys = True
    assert (await _call(app, "GET", "/admin/api/keys", admin_key)).status_code == 200
    assert (await _call(app, "GET", "/admin/api/keys", user_key)).status_code == 403


async def test_oauth_revoke_still_accepts_api_key_with_switch_on(keys):
    app, user_key, _ = keys
    app.state.auth.idp_disable_api_keys = True
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/oauth/revoke",
            data={"token": "whatever"},
            headers={"Authorization": f"Bearer {user_key}"},
        )
    assert r.status_code == 200


async def test_api_keys_accepted_when_switch_off(keys):
    app, user_key, _ = keys
    assert app.state.auth.idp_disable_api_keys is False
    assert (await _call(app, "GET", "/v1/tasks", user_key)).status_code == 200


async def test_api_key_switch_401_detail_is_generic(keys):
    app, user_key, _ = keys
    app.state.auth.idp_disable_api_keys = True
    r = await _call(app, "GET", "/v1/tasks", user_key)
    assert r.status_code == 401
    assert user_key not in r.text
    assert "invalid credentials" in r.text


async def test_switch_rejections_count_against_unauth_limiter(keys):
    from agent_sdk.common.limits import RateLimiter

    app, user_key, _ = keys
    app.state.auth.idp_disable_api_keys = True
    app.state.auth.bearer_limiter = RateLimiter(1)
    assert (await _call(app, "GET", "/v1/tasks", user_key)).status_code == 401
    assert (await _call(app, "GET", "/v1/tasks", user_key)).status_code == 429
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post(
            "/oauth/register",
            json={"redirect_uris": ["https://c.example.com/cb"], "client_name": "x"},
        )
    assert r.status_code == 201
