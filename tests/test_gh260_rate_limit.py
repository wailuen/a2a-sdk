"""GH-260: separate failed-bearer limiter, 429 surface split, invalid_token challenge.

Ruling: https://github.com/wailuen/a2a-sdk/issues/265#issuecomment-6395232689
"""

from __future__ import annotations

import gc

import httpx
import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.common.limits import RateLimiter
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient

BAD = "sk-this-bearer-is-bad-123456"
BARE = 'Bearer resource_metadata="'
INVALID = 'Bearer error="invalid_token", resource_metadata="'


def _make(tmp_path, **kw):
    settings = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "d"), AGENT_NAME="t", **kw
    )
    return make_agent(settings, model_client=FakeModelClient()).build_app()


@pytest.fixture
def app(tmp_path):
    built = _make(tmp_path)
    yield built
    built.state.credential_store.close()
    gc.collect()


async def _req(app, method, path, **kw):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        return await c.request(method, path, **kw)


async def test_drained_bearer_limiter_does_not_block_register(app):
    app.state.auth.bearer_limiter = RateLimiter(1)
    h = {"Authorization": f"Bearer {BAD}"}
    assert (await _req(app, "GET", "/v1/tasks", headers=h)).status_code == 401
    assert (await _req(app, "GET", "/v1/tasks", headers=h)).status_code == 429
    r = await _req(
        app, "POST", "/oauth/register",
        json={"redirect_uris": ["https://c.example.com/cb"], "client_name": "x"},
    )
    assert r.status_code == 201


async def test_bearer_limiter_wired_from_setting(tmp_path):
    app = _make(tmp_path, AGENT_SDK_UNAUTH_RATE_LIMIT=3)
    try:
        h = {"Authorization": f"Bearer {BAD}"}
        codes = [(await _req(app, "GET", "/v1/tasks", headers=h)).status_code for _ in range(5)]
        assert codes == [401, 401, 401, 429, 429]
    finally:
        app.state.credential_store.close()
        gc.collect()


async def test_oauth_bucket_does_not_drain_bearer_bucket(app):
    app.state.auth.unauth_limiter = RateLimiter(1)
    await _req(app, "POST", "/oauth/token", data={})
    h = {"Authorization": f"Bearer {BAD}"}
    assert (await _req(app, "GET", "/v1/tasks", headers=h)).status_code == 401


async def test_invalid_and_missing_challenges(app):
    inv = await _req(app, "GET", "/v1/tasks", headers={"Authorization": f"Bearer {BAD}"})
    assert inv.status_code == 401
    assert inv.headers["www-authenticate"].startswith(INVALID)
    assert BAD not in inv.headers["www-authenticate"] and BAD not in inv.text
    miss = await _req(app, "GET", "/v1/tasks")
    assert miss.headers["www-authenticate"].startswith(BARE)
    mcp = await _req(app, "POST", "/mcp", headers={"Authorization": f"Bearer {BAD}"}, json={})
    assert mcp.headers["www-authenticate"].startswith(INVALID)
    assert "oauth-protected-resource/mcp" in mcp.headers["www-authenticate"]


async def test_refused_key_same_challenge_and_body_as_invalid(app):
    ak = app.state.auth.api_keys
    user_key = ak.mint("u", admin=False)[1]
    app.state.auth.idp_disable_api_keys = True
    h = {"Authorization": f"Bearer {user_key}"}
    refused = await _req(app, "GET", "/v1/tasks", headers=h)
    invalid = await _req(app, "GET", "/v1/tasks", headers={"Authorization": f"Bearer {BAD}"})
    assert refused.status_code == invalid.status_code == 401
    assert refused.headers["www-authenticate"] == invalid.headers["www-authenticate"]
    assert refused.headers["www-authenticate"].startswith(INVALID)
    assert refused.text == invalid.text
    assert user_key not in refused.text


async def test_revoke_challenges(app):
    bad = await _req(
        app, "POST", "/oauth/revoke", data={"token": "x"},
        headers={"Authorization": f"Bearer {BAD}"},
    )
    assert bad.status_code == 401
    assert bad.headers["www-authenticate"].startswith(INVALID)
    none = await _req(app, "POST", "/oauth/revoke", data={"token": "x"})
    assert none.status_code == 401
    assert none.headers["www-authenticate"].startswith(BARE)


async def test_consent_post_rerender_keeps_bare_challenge(app):
    ak = app.state.auth.api_keys
    user_key = ak.mint("u", admin=False)[1]
    reg = await _req(
        app, "POST", "/oauth/register",
        json={"redirect_uris": ["https://c.example.com/cb"], "client_name": "x"},
    )
    assert reg.status_code == 201
    r = await _req(
        app, "POST", "/oauth/authorize",
        data={"api_key": user_key, "client_id": reg.json()["client_id"],
              "redirect_uri": "https://c.example.com/cb", "response_type": "code",
              "code_challenge": "a" * 43, "code_challenge_method": "S256"},
    )
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith(BARE)


async def test_bootstrap_401_keeps_bare_challenge(app):
    r = await _req(
        app, "POST", "/admin/api/keys", json={"label": "x"},
        headers={"X-Bootstrap-Token": BAD},
    )
    assert r.status_code == 401
    assert r.headers["www-authenticate"].startswith(BARE)


async def test_bearerless_mcp_never_429(app):
    for _ in range(31):
        r = await _req(app, "POST", "/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r.status_code == 401
        assert r.headers["www-authenticate"].startswith(BARE)


async def test_non_oauth_429_unchanged(app):
    r = None
    for _ in range(31):
        r = await _req(app, "GET", "/admin/api/keys", headers={"Authorization": "Bearer nope"})
    assert r is not None and r.status_code == 429
    assert r.json() == {"detail": "rate limit exceeded"}


def test_browser_route_set_is_fixed():
    from agent_sdk.routes.oauth import BROWSER_OAUTH_ROUTES

    assert BROWSER_OAUTH_ROUTES == frozenset({
        ("GET", "/oauth/authorize"),
        ("GET", "/oauth/idp/callback"),
        ("POST", "/oauth/idp/consent"),
        ("POST", "/oauth/authorize"),
    })


@pytest.mark.parametrize("method,path", sorted(
    [("GET", "/oauth/authorize"), ("GET", "/oauth/idp/callback"),
     ("POST", "/oauth/idp/consent"), ("POST", "/oauth/authorize")]))
async def test_browser_routes_429_is_branded_html(app, method, path):
    app.state.auth.unauth_limiter = RateLimiter(1)
    await _req(app, method, path)
    r = await _req(app, method, path)
    assert r.status_code == 429
    assert r.headers["content-type"].startswith("text/html")
    assert "Sign-in couldn" in r.text
    assert r.headers["retry-after"] == "60"
    assert r.headers["cache-control"] == "no-store"
    assert "temporarily_unavailable" not in r.text


@pytest.mark.parametrize("path", ["/oauth/register", "/oauth/token", "/oauth/revoke"])
async def test_api_routes_429_is_json_no_store(app, path):
    app.state.auth.unauth_limiter = RateLimiter(1)
    await _req(app, "POST", path, data={})
    r = await _req(app, "POST", path, data={})
    assert r.status_code == 429
    assert r.json() == {
        "error": "temporarily_unavailable",
        "error_description": "rate limit exceeded",
    }
    assert r.headers["cache-control"] == "no-store"
    assert r.headers["retry-after"] == "60"


async def test_token_responses_have_pragma_no_cache(app):
    r = await _req(app, "POST", "/oauth/token", data={"grant_type": "bogus"})
    assert r.status_code == 400
    assert r.headers["pragma"] == "no-cache"
    assert r.headers["cache-control"] == "no-store"


# GH-272 -------------------------------------------------------------------

async def _drain(app, method, path, **kw):
    app.state.auth.bearer_limiter = RateLimiter(1)
    h = {"Authorization": f"Bearer {BAD}"}
    first = await _req(app, method, path, headers=h, **kw)
    assert first.status_code == 401
    return await _req(app, method, path, headers=h, **kw)


@pytest.mark.parametrize("method,path,kw,mcp", [
    ("GET", "/v1/tasks", {}, False),
    ("POST", "/ag-ui/run", {"json": {}}, False),
    ("POST", "/mcp", {"json": {}}, True),
])
async def test_bearer_429_carries_invalid_token_challenge(app, method, path, kw, mcp):
    r = await _drain(app, method, path, **kw)
    assert r.status_code == 429
    assert r.headers["retry-after"] == "60"
    www = r.headers["www-authenticate"]
    assert www.startswith(INVALID)
    assert ("oauth-protected-resource/mcp" in www) is mcp
    assert BAD not in r.text and BAD not in str(dict(r.headers))


async def test_v1_429_body_is_fixed_minus_32000(app):
    r = await _drain(app, "GET", "/v1/tasks")
    assert r.json() == {"error": {"code": -32000, "message": "rate limit exceeded"}}


async def test_expired_token_429_carries_challenge(app, monkeypatch):
    from agent_sdk.auth import oauth_tokens

    pair = app.state.auth.oauth.mint_token_pair(
        client_id="c", scope="mcp", audience="http://test/mcp"
    )
    tok = pair["access_token"]
    real = oauth_tokens._now
    monkeypatch.setattr(oauth_tokens, "_now", lambda: real() + 10_000_000)
    app.state.auth.bearer_limiter = RateLimiter(1)
    h = {"Authorization": f"Bearer {tok}"}
    assert (await _req(app, "GET", "/v1/tasks", headers=h)).status_code == 401
    r = await _req(app, "GET", "/v1/tasks", headers=h)
    assert r.status_code == 429
    assert r.headers["www-authenticate"].startswith(INVALID)
    assert tok not in r.text and tok not in str(dict(r.headers))


async def test_revoke_bad_bearer_counts_and_429s(app):
    app.state.auth.bearer_limiter = RateLimiter(1)
    h = {"Authorization": f"Bearer {BAD}"}
    first = await _req(app, "POST", "/oauth/revoke", data={"token": "x"}, headers=h)
    assert first.status_code == 401
    r = await _req(app, "POST", "/oauth/revoke", data={"token": "x"}, headers=h)
    assert r.status_code == 429
    assert r.json() == {
        "error": "temporarily_unavailable",
        "error_description": "rate limit exceeded",
    }
    assert r.headers["retry-after"] == "60"
    assert r.headers["cache-control"] == "no-store"
    assert BAD not in r.text and BAD not in str(dict(r.headers))


async def test_revoke_without_bearer_not_counted(app):
    app.state.auth.bearer_limiter = RateLimiter(1)
    for _ in range(3):
        r = await _req(app, "POST", "/oauth/revoke", data={"token": "x"})
        assert r.status_code == 401
