"""GH-152-D: federated /oauth/authorize, /oauth/idp/callback, /oauth/idp/consent."""

from __future__ import annotations

import base64
import gc
import hashlib
import html as html_mod
import json
import re
import secrets
import time
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from agent_sdk import BaseAgentSettings
from agent_sdk.auth.oidc import IdpFlowStore, OidcRelyingParty
from agent_sdk.credentials.store import NS_OAUTH_IDP
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient

TENANT = "11111111-2222-3333-4444-555555555555"
OID = "99999999-8888-7777-6666-555555555555"
LOGIN = "https://login.microsoftonline.com"
ISSUER = f"{LOGIN}/{TENANT}/v2.0"
IDP_CLIENT_ID = "idp-client"
CB = "https://client.example.com/cb"
COOKIE = "__Host-agent_sdk_idp"


def cookie_name(state: str) -> str:
    return f"{COOKIE}_{hashlib.sha256(state.encode()).hexdigest()[:16]}"


class FlowCookie(str):
    name: str
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
FORM = {"Content-Type": "application/x-www-form-urlencoded"}


def _jwk():
    d = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key()))
    d.update(kid="k1", use="sig", alg="RS256")
    return d


class FakeIdp:
    def __init__(self):
        self.down = False
        self.claims: dict = {}
        self.token_calls = 0
        self.token_status = 200
        self.access_token = "AT"
        self.refresh_token: str | None = None
        self.last_token_form: dict[str, list[str]] = {}

    def id_token(self, _nonce: str, **over) -> str:
        now = int(time.time())
        c = {
            "iss": ISSUER, "aud": IDP_CLIENT_ID, "sub": "s", "iat": now, "nbf": now,
            "exp": now + 600, "nonce": _nonce, "tid": TENANT, "oid": OID,
            "preferred_username": "alice@example.com",
        }
        c.update(over)
        return jwt.encode(c, KEY, algorithm="RS256", headers={"kid": "k1"})

    def handler(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("down")
        p = request.url.path
        if p.endswith("openid-configuration"):
            return httpx.Response(200, json={
                "issuer": ISSUER,
                "authorization_endpoint": f"{LOGIN}/authorize",
                "token_endpoint": f"{LOGIN}/token",
                "jwks_uri": f"{LOGIN}/keys",
            })
        if p == "/keys":
            return httpx.Response(200, json={"keys": [_jwk()]})
        if p == "/token":
            self.token_calls += 1
            self.last_token_form = parse_qs(request.content.decode())
            if self.token_status != 200:
                return httpx.Response(self.token_status, json={
                    "error": "invalid_grant", "error_description": self.access_token})
            body = {"id_token": self.claims["id_token"], "access_token": self.access_token}
            if self.refresh_token:
                body["refresh_token"] = self.refresh_token
            return httpx.Response(200, json=body)
        return httpx.Response(404)


def idp_settings(tmp_path, **extra):
    return BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent",
        AGENT_SDK_OAUTH_IDP="oidc",
        AGENT_SDK_OAUTH_IDP_ISSUER=ISSUER,
        AGENT_SDK_OAUTH_IDP_CLIENT_ID=IDP_CLIENT_ID,
        **extra,
    )


@pytest.fixture
def idp():
    return FakeIdp()


@pytest.fixture
def idp_app(tmp_path, idp):
    app = make_agent(idp_settings(tmp_path), model_client=FakeModelClient()).build_app()
    rp = app.state.idp_rp
    assert isinstance(rp, OidcRelyingParty)
    rp._transport = httpx.MockTransport(idp.handler)
    app.state.credential_store.set(NS_OAUTH_IDP, "client_secret", "the-secret")
    yield app
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def ic(idp_app):
    async with idp_app.router.lifespan_context(idp_app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=idp_app), base_url="http://test"
        ) as c:
            c.app = idp_app  # type: ignore[attr-defined]
            yield c


def pkce() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(48)
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


async def register(c, redirect_uri=CB) -> str:
    r = await c.post("/oauth/register", json={"redirect_uris": [redirect_uri], "client_name": "Claude"})
    assert r.status_code == 201
    return r.json()["client_id"]


def authorize_params(client_id, challenge, **over):
    p = {
        "client_id": client_id, "redirect_uri": CB, "response_type": "code",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "client-state",
    }
    p.update(over)
    return p


def cookie_value(r: httpx.Response) -> FlowCookie:
    sc = r.headers["set-cookie"]
    m = re.match(rf"({re.escape(COOKIE)}_[0-9a-f]{{16}})=([^;]+)", sc)
    assert m, sc
    c = FlowCookie(m.group(2))
    c.name = m.group(1)
    return c


async def start(c, idp, **over):
    """Run authorize; return (client_id, verifier, idp_query, cookie)."""
    cid = await register(c)
    verifier, challenge = pkce()
    r = await c.get("/oauth/authorize", params=authorize_params(cid, challenge, **over))
    assert r.status_code == 302, r.text
    loc = urlparse(r.headers["location"])
    q = {k: v[0] for k, v in parse_qs(loc.query).items()}
    return cid, verifier, q, cookie_value(r)


async def callback(c, idp, q, cookie, *, claims=None, code="idp-code", **extra):
    idp.claims = {"id_token": idp.id_token(q["nonce"], **(claims or {}))}
    params = {"code": code, "state": q["state"], **extra}
    return await c.get("/oauth/idp/callback", params=params, headers={"Cookie": f"{cookie_name(q['state'])}={cookie}"})


def ticket_of(r: httpx.Response) -> str:
    m = re.search(r'name="ticket" value="([^"]+)"', r.text)
    assert m, r.text
    return html_mod.unescape(m.group(1))


# ── authorize ───────────────────────────────────────────────────────────────

async def test_unknown_client_never_redirects_to_idp(ic):
    _, ch = pkce()
    r = await ic.get("/oauth/authorize", params=authorize_params("nope", ch))
    assert r.status_code == 400
    assert "location" not in r.headers
    assert "set-cookie" not in r.headers


async def test_unregistered_redirect_uri_never_redirects_to_idp(ic):
    cid = await register(ic)
    _, ch = pkce()
    r = await ic.get("/oauth/authorize", params=authorize_params(cid, ch, redirect_uri="https://evil.example.com/cb"))
    assert r.status_code == 400
    assert "location" not in r.headers


@pytest.mark.parametrize("surface", ["root", "mcp"])
async def test_authorize_redirects_to_idp_with_pkce_s256_and_nonce(ic, idp, surface):
    base = ic.app.state.settings.resolved_base_url
    over = {"resource": base if surface == "root" else f"{base}/mcp"}
    _, _, q, cookie = await start(ic, idp, **over)
    assert q["code_challenge_method"] == "S256"
    assert len(q["code_challenge"]) == 43
    assert q["nonce"] and q["state"]
    assert q["client_id"] == IDP_CLIENT_ID
    assert q["redirect_uri"] == f"{ic.app.state.settings.resolved_base_url}/oauth/idp/callback"
    assert cookie not in q.values()


async def test_authorize_sets_host_cookie_attributes(ic, idp):
    cid = await register(ic)
    _, ch = pkce()
    r = await ic.get("/oauth/authorize", params=authorize_params(cid, ch))
    sc = r.headers["set-cookie"]
    assert sc.startswith(f"{COOKIE}_")
    for attr in ("HttpOnly", "Secure", "SameSite=lax", "Path=/", "Max-Age=600"):
        assert attr.lower() in sc.lower()
    assert "domain" not in sc.lower()


async def test_authorize_missing_secret_is_temporarily_unavailable(ic, idp):
    ic.app.state.credential_store.delete(NS_OAUTH_IDP, "client_secret")
    cid = await register(ic)
    _, ch = pkce()
    r = await ic.get("/oauth/authorize", params=authorize_params(cid, ch))
    assert r.status_code == 302
    loc = urlparse(r.headers["location"])
    assert f"{loc.scheme}://{loc.netloc}{loc.path}" == CB
    q = parse_qs(loc.query)
    assert q["error"] == ["temporarily_unavailable"]
    assert q["state"] == ["client-state"]
    assert "set-cookie" not in r.headers


async def test_idp_outage_is_temporarily_unavailable_not_500(ic, idp):
    idp.down = True
    cid = await register(ic)
    _, ch = pkce()
    r = await ic.get("/oauth/authorize", params=authorize_params(cid, ch))
    assert r.status_code == 302
    assert parse_qs(urlparse(r.headers["location"]).query)["error"] == ["temporarily_unavailable"]


async def test_admin_key_consent_disabled_under_idp(ic, idp):
    cid = await register(ic)
    _, ch = pkce()
    _, token = ic.app.state.auth.api_keys.mint("adm", admin=True)
    body = urlencode({**authorize_params(cid, ch), "api_key": token})
    r = await ic.post("/oauth/authorize", content=body, headers=FORM)
    assert r.status_code == 400
    assert "location" not in r.headers
    assert token not in r.text


# ── callback ────────────────────────────────────────────────────────────────

async def test_callback_unknown_state_rejected(ic, idp):
    r = await ic.get("/oauth/idp/callback", params={"code": "c", "state": "nope"}, headers={"Cookie": f"{COOKIE}=x"})
    assert r.status_code == 400
    assert "location" not in r.headers


async def test_callback_missing_state_rejected(ic):
    r = await ic.get("/oauth/idp/callback", params={"code": "c"})
    assert r.status_code == 400


async def test_callback_cookie_mismatch_rejected(ic, idp):
    _, _, q, cookie = await start(ic, idp)
    r = await callback(ic, idp, q, "wrong-cookie")
    assert r.status_code == 400
    assert "location" not in r.headers
    assert idp.token_calls == 0


async def test_callback_missing_cookie_rejected(ic, idp):
    _, _, q, _ = await start(ic, idp)
    r = await ic.get("/oauth/idp/callback", params={"code": "c", "state": q["state"]})
    assert r.status_code == 400


async def test_callback_state_replay_rejected(ic, idp):
    _, _, q, cookie = await start(ic, idp)
    first = await callback(ic, idp, q, cookie)
    assert first.status_code == 200
    second = await callback(ic, idp, q, cookie)
    assert second.status_code == 400
    assert "location" not in second.headers


async def test_callback_success_shows_consent_page(ic, idp):
    _, _, q, cookie = await start(ic, idp)
    r = await callback(ic, idp, q, cookie)
    assert r.status_code == 200
    assert "Claude" in r.text
    assert "client.example.com" in r.text
    assert "alice@example.com" in r.text
    assert "Allow" in r.text and "Deny" in r.text
    csp = r.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in csp
    assert "https://client.example.com" in csp
    assert r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store"
    assert idp.last_token_form["code_verifier"]
    assert idp.last_token_form["client_secret"] == ["the-secret"]


async def test_callback_idp_error_param_access_denied(ic, idp):
    _, _, q, cookie = await start(ic, idp)
    r = await ic.get(
        "/oauth/idp/callback",
        params={"error": "access_denied", "error_description": "AADSTS-secret-detail", "state": q["state"]},
        headers={"Cookie": f"{cookie.name}={cookie}"},
    )
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith(CB)
    qs = parse_qs(urlparse(loc).query)
    assert qs["error"] == ["access_denied"]
    assert qs["state"] == ["client-state"]
    assert "AADSTS" not in loc


async def test_callback_invalid_id_token_access_denied(ic, idp):
    _, _, q, cookie = await start(ic, idp)
    r = await callback(ic, idp, q, cookie, claims={"tid": "00000000-0000-0000-0000-000000000000"})
    assert r.status_code == 302
    qs = parse_qs(urlparse(r.headers["location"]).query)
    assert qs["error"] == ["access_denied"]
    assert "code" not in qs


async def test_callback_wrong_nonce_access_denied(ic, idp):
    _, _, q, cookie = await start(ic, idp)
    r = await callback(ic, idp, q, cookie, claims={"nonce": "attacker-nonce"})
    assert r.status_code == 302
    assert parse_qs(urlparse(r.headers["location"]).query)["error"] == ["access_denied"]


async def test_callback_missing_required_role_access_denied(tmp_path, idp):
    app = make_agent(
        idp_settings(tmp_path, AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE="Agent.User"),
        model_client=FakeModelClient(),
    ).build_app()
    app.state.idp_rp._transport = httpx.MockTransport(idp.handler)
    app.state.credential_store.set(NS_OAUTH_IDP, "client_secret", "s")
    try:
        async with app.router.lifespan_context(app):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
                _, _, q, cookie = await start(c, idp)
                r = await callback(c, idp, q, cookie)
                assert r.status_code == 302
                assert parse_qs(urlparse(r.headers["location"]).query)["error"] == ["access_denied"]
    finally:
        app.state.credential_store.close()
        gc.collect()


async def test_callback_idp_outage_at_exchange_temporarily_unavailable(ic, idp):
    _, _, q, cookie = await start(ic, idp)
    idp.down = True
    r = await ic.get("/oauth/idp/callback", params={"code": "c", "state": q["state"]}, headers={"Cookie": f"{cookie_name(q['state'])}={cookie}"})
    assert r.status_code == 302
    assert parse_qs(urlparse(r.headers["location"]).query)["error"] == ["temporarily_unavailable"]


# ── consent ─────────────────────────────────────────────────────────────────

def _consent_body(ticket, decision="allow"):
    return urlencode({"ticket": ticket, "decision": decision})


async def _token(c, cid, verifier, code):
    return await c.post("/oauth/token", content=urlencode({
        "grant_type": "authorization_code", "code": code, "client_id": cid,
        "redirect_uri": CB, "code_verifier": verifier,
    }), headers=FORM)


async def _allowed(ic, idp):
    cid, verifier, q, cookie = await start(ic, idp)
    page = await callback(ic, idp, q, cookie)
    r = await ic.post("/oauth/idp/consent", content=_consent_body(ticket_of(page)),
                      headers={**FORM, "Cookie": f"{cookie.name}={cookie}"})
    return cid, verifier, cookie, page, r


async def test_full_idp_flow_mints_user_bound_token(ic, idp):
    cid, verifier, _, _, r = await _allowed(ic, idp)
    assert r.status_code == 303
    qs = parse_qs(urlparse(r.headers["location"]).query)
    assert qs["state"] == ["client-state"]
    tok = await _token(ic, cid, verifier, qs["code"][0])
    assert tok.status_code == 200
    ident = ic.app.state.oauth.verify(tok.json()["access_token"])
    assert ident is not None
    assert ident.kind == "oauth" and ident.subject == cid
    assert ident.user == f"{TENANT}:{OID}"


async def test_idp_consent_records_user_consent_not_admin_approval(ic, idp):
    """RT-001: IdP Allow is user consent — it must never set the admin-only
    ``consented`` bit that the one-time-consent shortcut trusts."""
    cid, _, _, _, r = await _allowed(ic, idp)
    assert r.status_code == 303
    record = ic.app.state.oauth.get_client(cid)
    assert not record.get("consented")
    assert record.get("user_consented_at")


async def test_idp_consent_not_promoted_when_switching_to_idp_off_one_time_consent(
    ic, idp, tmp_path
):
    """RT-001: consent under IdP, rebuild with idp=none + one-time consent —
    GET /oauth/authorize must render the admin-key page, never a code redirect."""
    cid, _, _, _, r = await _allowed(ic, idp)
    assert r.status_code == 303
    off = make_agent(
        BaseAgentSettings(
            DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent",
            AGENT_SDK_OAUTH_ONE_TIME_CONSENT=True,
        ),
        model_client=FakeModelClient(),
    ).build_app()
    try:
        assert off.state.oauth.get_client(cid) is not None  # same store
        async with off.router.lifespan_context(off):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=off), base_url="http://test"
            ) as c:
                _, ch = pkce()
                params = authorize_params(cid, ch)
                params.pop("resource", None)
                page = await c.get("/oauth/authorize", params=params)
        assert page.status_code == 200, page.headers.get("location")
        assert "location" not in page.headers
        assert 'name="api_key"' in page.text
    finally:
        off.state.credential_store.close()
        gc.collect()


async def test_idp_consented_client_survives_dcr_flood(ic, idp, monkeypatch):
    from agent_sdk.auth import oauth_tokens

    cid, _, _, _, r = await _allowed(ic, idp)
    assert r.status_code == 303
    store = ic.app.state.oauth
    store.mint_token_pair(
        client_id=cid, scope="", audience=store.canonical_resource, user="u", label="L"
    )
    monkeypatch.setattr(oauth_tokens, "MAX_CLIENTS", 5)
    for _ in range(oauth_tokens.MAX_CLIENTS + 1):
        await register(ic)
    assert ic.app.state.oauth.get_client(cid) is not None


async def test_consent_deny_returns_access_denied(ic, idp):
    cid, _, q, cookie = await start(ic, idp)
    page = await callback(ic, idp, q, cookie)
    r = await ic.post("/oauth/idp/consent", content=_consent_body(ticket_of(page), "deny"),
                      headers={**FORM, "Cookie": f"{cookie.name}={cookie}"})
    assert r.status_code in (302, 303)
    qs = parse_qs(urlparse(r.headers["location"]).query)
    assert qs["error"] == ["access_denied"] and qs["state"] == ["client-state"]
    assert "code" not in qs


async def test_consent_ticket_replay_rejected(ic, idp):
    cid, verifier, cookie, page, first = await _allowed(ic, idp)
    assert first.status_code == 303
    again = await ic.post("/oauth/idp/consent", content=_consent_body(ticket_of(page)),
                          headers={**FORM, "Cookie": f"{cookie.name}={cookie}"})
    assert again.status_code == 400
    assert "location" not in again.headers


async def test_consent_ticket_cookie_mismatch_rejected(ic, idp):
    cid, _, q, cookie = await start(ic, idp)
    page = await callback(ic, idp, q, cookie)
    r = await ic.post("/oauth/idp/consent", content=_consent_body(ticket_of(page)),
                      headers={**FORM, "Cookie": f"{cookie.name}=other"})
    assert r.status_code == 400
    assert "location" not in r.headers
    ok = await ic.post("/oauth/idp/consent", content=_consent_body(ticket_of(page)),
                       headers={**FORM, "Cookie": f"{cookie.name}={cookie}"})
    assert ok.status_code == 400  # ticket burned by the failed attempt


async def test_consent_unknown_ticket_rejected(ic):
    r = await ic.post("/oauth/idp/consent", content=_consent_body("nope"), headers={**FORM, "Cookie": f"{COOKIE}=x"})
    assert r.status_code == 400


async def test_refresh_keeps_user_and_family_cap(ic, idp):
    cid, verifier, _, _, r = await _allowed(ic, idp)
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    tok = (await _token(ic, cid, verifier, code)).json()
    rr = await ic.post("/oauth/token", content=urlencode({
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": cid,
    }), headers=FORM)
    assert rr.status_code == 200
    ident = ic.app.state.oauth.verify(rr.json()["access_token"])
    assert ident is not None and ident.user == f"{TENANT}:{OID}"
    store = ic.app.state.credential_store
    from agent_sdk.credentials.store import NS_OAUTH_REFRESH
    recs = [json.loads(store.get(NS_OAUTH_REFRESH, k)) for k in store.list_fields(NS_OAUTH_REFRESH)]
    assert recs and all("family_expires_at" in rec and rec["user"] for rec in recs)


async def test_idp_routes_rate_limited(ic):
    from agent_sdk.common.limits import RateLimiter
    ic.app.state.auth.unauth_limiter = RateLimiter(1)
    codes = []
    for _ in range(4):
        codes.append((await ic.get("/oauth/idp/callback", params={"state": "x"})).status_code)
    assert 429 in codes
    codes = []
    for _ in range(4):
        codes.append((await ic.post("/oauth/idp/consent", content="ticket=x", headers=FORM)).status_code)
    assert 429 in codes


_ORIGIN = "https://claude.ai"
_DISCOVERY = (
    "/.well-known/oauth-protected-resource",
    "/.well-known/oauth-protected-resource/mcp",
    "/.well-known/oauth-authorization-server",
)
_PROTECTED = (
    ("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
    ("/v1/message:send", {"message": {
        "role": "user", "parts": [{"kind": "text", "text": "hi"}], "messageId": "m1"}}),
)
_VOLATILE = {"date", "content-length", "x-request-id"}


def _stable_headers(r: httpx.Response) -> list[tuple[str, str]]:
    return sorted((k, v) for k, v in r.headers.items() if k not in _VOLATILE)


async def _oauth_chain_probes(app) -> dict:
    """Run every /agent-verify OAuth-chain probe unauthenticated; return raw captures."""
    out: dict = {}
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            for path in _DISCOVERY:
                r = await c.get(path)
                out[f"GET {path}"] = (r.status_code, r.content, _stable_headers(r))
            for path, body in _PROTECTED:
                r = await c.post(path, json=body, headers={"Origin": _ORIGIN})
                out[f"POST {path}"] = (r.status_code, r.content, _stable_headers(r))
                r = await c.options(path, headers={
                    "Origin": _ORIGIN,
                    "Access-Control-Request-Method": "POST",
                    "Access-Control-Request-Headers": "authorization, content-type",
                })
                out[f"OPTIONS {path}"] = (r.status_code, r.content, _stable_headers(r))
    return out


async def test_idp_on_discovery_documents_unchanged(tmp_path, idp):
    """GH-152-D AC: PRM (both), AS metadata, 401 + WWW-Authenticate, and CORS
    preflight are identical with the IdP on and off."""
    from tests.test_gh152_idp_off_regression import GOLDEN_METADATA

    off_app = make_agent(
        BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path / "off"), AGENT_NAME="test-agent"),
        model_client=FakeModelClient(),
    ).build_app()
    on_app = make_agent(idp_settings(tmp_path), model_client=FakeModelClient()).build_app()
    assert getattr(off_app.state, "idp_rp", None) is None
    assert isinstance(on_app.state.idp_rp, OidcRelyingParty)
    on_app.state.idp_rp._transport = httpx.MockTransport(idp.handler)
    on_app.state.credential_store.set(NS_OAUTH_IDP, "client_secret", "the-secret")
    try:
        off = await _oauth_chain_probes(off_app)
        on = await _oauth_chain_probes(on_app)
    finally:
        off_app.state.credential_store.close()
        on_app.state.credential_store.close()
        gc.collect()

    # Each probe must look right on its own, so "equal" cannot mean "equally broken".
    for side in (off, on):
        for path, sha in GOLDEN_METADATA.items():
            status, body, _ = side[f"GET {path}"]
            assert status == 200, path
            assert hashlib.sha256(body).hexdigest() == sha, path
        for path, _ in _PROTECTED:
            status, _, hdrs = side[f"POST {path}"]
            h = dict(hdrs)
            assert status == 401, path
            assert 'resource_metadata="' in h["www-authenticate"], path
            assert "WWW-Authenticate" in h["access-control-expose-headers"], path
            assert h["access-control-allow-origin"] == _ORIGIN, path
            status, _, hdrs = side[f"OPTIONS {path}"]
            h = dict(hdrs)
            assert status == 204, path
            assert h["access-control-allow-origin"] == _ORIGIN, path
            assert "Authorization" in h["access-control-allow-headers"], path

    assert on.keys() == off.keys()
    for probe in off:
        assert on[probe] == off[probe], probe

    asm = json.loads(on["GET /.well-known/oauth-authorization-server"][1])
    assert "idp" not in json.dumps(asm).lower()
    assert urlparse(LOGIN).netloc not in json.dumps(asm)


# ── concurrent flows (RT-003) ───────────────────────────────────────────────

async def _begin(c, cid):
    verifier, challenge = pkce()
    r = await c.get("/oauth/authorize", params=authorize_params(cid, challenge))
    assert r.status_code == 302, r.text
    q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}
    return q, cookie_value(r)


async def test_two_concurrent_flows_same_browser_both_complete(ic, idp):
    cid = await register(ic)
    qa, ca = await _begin(ic, cid)
    qb, cb_ = await _begin(ic, cid)
    assert ca.name != cb_.name
    jar = {ca.name: str(ca), cb_.name: str(cb_)}
    ic.cookies.clear()

    async def finish(q, cookie):
        idp.claims = {"id_token": idp.id_token(q["nonce"])}
        h = {"Cookie": "; ".join(f"{k}={v}" for k, v in jar.items())}
        page = await ic.get("/oauth/idp/callback", params={"code": "c", "state": q["state"]}, headers=h)
        assert page.status_code == 200, page.text
        ok = await ic.post("/oauth/idp/consent", content=_consent_body(ticket_of(page)), headers={**FORM, **h})
        assert ok.status_code == 303, ok.text
        assert "code=" in ok.headers["location"]

    await finish(qb, cb_)
    await finish(qa, ca)


async def test_flow_binding_from_other_flow_rejected(ic, idp):
    cid = await register(ic)
    qa, ca = await _begin(ic, cid)
    qb, cb_ = await _begin(ic, cid)
    idp.claims = {"id_token": idp.id_token(qb["nonce"])}
    r = await ic.get(
        "/oauth/idp/callback",
        params={"code": "c", "state": qb["state"]},
        headers={"Cookie": f"{cookie_name(qb['state'])}={ca}"},
    )
    assert r.status_code == 400
    r = await ic.get(
        "/oauth/idp/callback",
        params={"code": "c", "state": qb["state"]},
        headers={"Cookie": f"{ca.name}={ca}"},
    )
    assert r.status_code == 400


async def test_flow_cookies_bounded_and_cleared(ic, idp):
    cid = await register(ic)
    jar = {}
    for _ in range(14):
        _, c = await _begin_with(ic, cid, jar)
        jar[c.name] = str(c)
    assert len(jar) <= 8


async def _begin_with(c, cid, jar):
    verifier, challenge = pkce()
    h = {"Cookie": "; ".join(f"{k}={v}" for k, v in jar.items())} if jar else {}
    r = await c.get("/oauth/authorize", params=authorize_params(cid, challenge), headers=h)
    assert r.status_code == 302, r.text
    for sc in r.headers.get_list("set-cookie"):
        m = re.match(r"([^=]+)=([^;]*);", sc)
        if "max-age=0" in sc.lower() or not m.group(2) or m.group(2) == '""':
            jar.pop(m.group(1), None)
    return None, cookie_value_of(r)


def cookie_value_of(r):
    for sc in r.headers.get_list("set-cookie"):
        m = re.match(rf"({re.escape(COOKIE)}_[0-9a-f]{{16}})=([^;]+)", sc)
        if m and "max-age=0" not in sc.lower() and m.group(2) != '""':
            c = FlowCookie(m.group(2))
            c.name = m.group(1)
            return c
    raise AssertionError(r.headers)


async def _routed_client(tmp_path, idp, peer, **extra):
    app = make_agent(
        idp_settings(tmp_path, AGENT_SDK_UNAUTH_RATE_LIMIT=1000, **extra),
        model_client=FakeModelClient(),
    ).build_app()
    app.state.idp_rp._transport = httpx.MockTransport(idp.handler)
    app.state.credential_store.set(NS_OAUTH_IDP, "client_secret", "the-secret")
    app.state.idp_flows = IdpFlowStore(per_source_max=3)
    return app, httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, client=(peer, 5000)), base_url="http://test"
    )


async def _authorize(c, cid, headers=None):
    _, challenge = pkce()
    r = await c.get(
        "/oauth/authorize", params=authorize_params(cid, challenge), headers=headers or {}
    )
    assert r.status_code == 302, r.text
    q = {k: v[0] for k, v in parse_qs(urlparse(r.headers["location"]).query).items()}
    return q, cookie_value(r)


async def test_spoofed_xff_from_untrusted_peer_billed_to_peer(tmp_path, idp):
    app, c = await _routed_client(tmp_path, idp, "198.51.100.7")
    try:
        async with app.router.lifespan_context(app):
            cid = await register(c)
            first = None
            for i in range(4):
                q, ck = await _authorize(c, cid, {"X-Forwarded-For": f"203.0.113.{i}"})
                first = first or (q, ck)
            r = await callback(c, idp, *first)
            assert r.status_code != 200 or "ticket" not in r.text
            assert app.state.idp_flows._flows.__len__() == 3
            other = httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app, client=("198.51.100.8", 1)),
                base_url="http://test",
            )
            q2, ck2 = await _authorize(other, cid)
            r2 = await callback(other, idp, q2, ck2)
            assert "ticket" in r2.text
            await other.aclose()
    finally:
        await c.aclose()
        app.state.credential_store.close()


async def test_trusted_proxy_xff_bills_real_client(tmp_path, idp):
    app, c = await _routed_client(
        tmp_path, idp, "10.0.0.1", AGENT_SDK_TRUSTED_PROXIES=["10.0.0.1"]
    )
    try:
        async with app.router.lifespan_context(app):
            cid = await register(c)
            a = await _authorize(c, cid, {"X-Forwarded-For": "203.0.113.1"})
            for _ in range(3):
                await _authorize(c, cid, {"X-Forwarded-For": "203.0.113.2"})
            r = await callback(c, idp, *a)
            assert "ticket" in r.text
    finally:
        await c.aclose()
        app.state.credential_store.close()
