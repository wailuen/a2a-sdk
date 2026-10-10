"""GH-152-B: OidcRelyingParty — discovery, JWKS cache, host pinning, ID-token checks."""

from __future__ import annotations

import json
import logging
import sys
import time
from urllib.parse import parse_qs, urlparse

import httpx
import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from agent_sdk.auth import oidc
from agent_sdk.auth.oidc import IdpDenied, IdpUnavailable, OidcConfig, OidcRelyingParty

TENANT = "11111111-2222-3333-4444-555555555555"
ISSUER = f"https://login.example.com/{TENANT}/v2.0"
CLIENT_ID = "client-abc"
REDIRECT = "https://agent.example.com/oauth/idp/callback"
OID = "99999999-8888-7777-6666-555555555555"


def _key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


KEY = _key()
OTHER_KEY = _key()


def _jwk(key, kid):
    d = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    d.update(kid=kid, use="sig", alg="RS256")
    return d


def _discovery(**over):
    doc = {
        "issuer": ISSUER,
        "authorization_endpoint": "https://login.example.com/authorize",
        "token_endpoint": "https://login.example.com/token",
        "jwks_uri": "https://login.example.com/keys",
    }
    doc.update(over)
    return doc


class Idp:
    """Scriptable fake IdP behind an httpx.MockTransport."""

    def __init__(self):
        self.discovery = _discovery()
        self.jwks = {"keys": [_jwk(KEY, "k1")]}
        self.token_status = 200
        self.token_body: bytes | dict = {"id_token": "x"}
        self.requests: list[httpx.Request] = []
        self.hits = {"disc": 0, "jwks": 0, "token": 0}
        self.fail_all = False
        self.raw: dict[str, httpx.Response] = {}

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if self.fail_all:
            raise httpx.ConnectError("boom")
        if path.endswith("openid-configuration"):
            self.hits["disc"] += 1
            return self.raw.get("disc") or httpx.Response(200, json=self.discovery)
        if path == "/keys":
            self.hits["jwks"] += 1
            return self.raw.get("jwks") or httpx.Response(200, json=self.jwks)
        if path == "/token":
            self.hits["token"] += 1
            body = self.token_body
            if isinstance(body, bytes):
                return httpx.Response(self.token_status, content=body)
            return httpx.Response(self.token_status, json=body)
        return httpx.Response(404)

    def transport(self):
        return httpx.MockTransport(self.handler)


def _rp(idp: Idp, secret="s3cret", **cfg) -> OidcRelyingParty:
    base = dict(
        issuer=ISSUER, client_id=CLIENT_ID, tenant_id=TENANT,
        required_role=None, required_group=None, redirect_uri=REDIRECT,
    )
    base.update(cfg)
    return OidcRelyingParty(OidcConfig(**base), lambda: secret, transport=idp.transport())


def _claims(**over):
    now = int(time.time())
    c = {
        "iss": ISSUER, "aud": CLIENT_ID, "sub": "sub-1", "iat": now, "nbf": now,
        "exp": now + 600, "nonce": "n-1", "tid": TENANT, "oid": OID,
        "preferred_username": "alice@example.com",
    }
    c.update(over)
    return {k: v for k, v in c.items() if v is not None}


def _tok(claims=None, key=KEY, kid="k1", alg="RS256", **hdr):
    return jwt.encode(claims if claims is not None else _claims(), key, algorithm=alg,
                      headers={"kid": kid, **hdr})


# ── discovery ──────────────────────────────────────────────────────────────

async def test_discovery_ok_and_authorize_url():
    idp = Idp()
    url = await _rp(idp).build_authorize_url("st", "no", "chal")
    u = urlparse(url)
    q = {k: v[0] for k, v in parse_qs(u.query).items()}
    assert f"{u.scheme}://{u.netloc}{u.path}" == "https://login.example.com/authorize"
    assert q == {
        "response_type": "code", "response_mode": "query", "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT, "scope": "openid profile email", "state": "st",
        "nonce": "no", "code_challenge": "chal", "code_challenge_method": "S256",
    }
    assert "offline_access" not in url


async def test_discovery_rejects_issuer_mismatch():
    idp = Idp()
    idp.discovery = _discovery(issuer="https://login.example.com/other/v2.0")
    with pytest.raises(IdpUnavailable):
        await _rp(idp).build_authorize_url("s", "n", "c")


@pytest.mark.parametrize("field", ["authorization_endpoint", "token_endpoint", "jwks_uri"])
@pytest.mark.parametrize("bad", [
    "https://evil.example.net/x", "http://login.example.com/x", "https://login.example.com.evil.net/x",
    "https://user@evil.net/x", "",
])
async def test_discovery_rejects_endpoint_off_issuer_host(field, bad):
    idp = Idp()
    idp.discovery = _discovery(**{field: bad})
    with pytest.raises(IdpUnavailable):
        await _rp(idp).build_authorize_url("s", "n", "c")


async def test_discovery_missing_endpoint_unavailable():
    idp = Idp()
    d = _discovery()
    del d["jwks_uri"]
    idp.discovery = d
    with pytest.raises(IdpUnavailable):
        await _rp(idp).build_authorize_url("s", "n", "c")


async def test_discovery_rejects_redirect_response():
    idp = Idp()
    idp.raw["disc"] = httpx.Response(302, headers={"location": "https://evil.net/"})
    with pytest.raises(IdpUnavailable):
        await _rp(idp).build_authorize_url("s", "n", "c")
    assert all(r.url.host == "login.example.com" for r in idp.requests)


async def test_oversize_response_is_unavailable():
    idp = Idp()
    idp.raw["disc"] = httpx.Response(200, content=b"{" + b" " * (600 * 1024) + b"}")
    with pytest.raises(IdpUnavailable):
        await _rp(idp).build_authorize_url("s", "n", "c")


async def test_oversize_cap_enforced_while_streaming():
    consumed = 0

    class Stream(httpx.AsyncByteStream):
        async def __aiter__(self):
            nonlocal consumed
            for _ in range(1000):
                consumed += 64 * 1024
                yield b" " * (64 * 1024)

    idp = Idp()
    idp.raw["disc"] = httpx.Response(200, stream=Stream())
    with pytest.raises(IdpUnavailable):
        await _rp(idp).build_authorize_url("s", "n", "c")
    assert consumed < 2 * 1024 * 1024


async def test_discovery_malformed_json_unavailable():
    idp = Idp()
    idp.raw["disc"] = httpx.Response(200, content=b"not json")
    with pytest.raises(IdpUnavailable):
        await _rp(idp).build_authorize_url("s", "n", "c")


async def test_client_flags_follow_redirects_off_and_timeout(monkeypatch):
    seen: dict = {}
    real = httpx.AsyncClient

    def spy(*a, **kw):
        seen.update(kw)
        return real(*a, **kw)

    monkeypatch.setattr(oidc.httpx, "AsyncClient", spy)
    await _rp(Idp()).build_authorize_url("s", "n", "c")
    assert seen["follow_redirects"] is False
    assert seen["timeout"] == 10.0


def test_no_client_constructed_at_import(monkeypatch):
    calls = []
    monkeypatch.setattr(httpx, "AsyncClient", lambda *a, **k: calls.append(1))
    monkeypatch.delitem(sys.modules, "agent_sdk.auth.oidc")
    import importlib
    importlib.import_module("agent_sdk.auth.oidc")
    assert calls == []


def test_jwt_not_imported_at_module_import():
    import subprocess
    code = ("import sys, agent_sdk.auth.oidc; "
            "sys.exit(1 if 'jwt' in sys.modules else 0)")
    assert subprocess.run([sys.executable, "-c", code]).returncode == 0


@pytest.mark.parametrize("issuer", ["https://127.0.0.1/t", "https://169.254.169.254/t", "https://[::1]/t"])
async def test_non_public_issuer_ip_refused(issuer):
    idp = Idp()
    rp = OidcRelyingParty(
        OidcConfig(issuer=issuer, client_id="c", tenant_id=None, required_role=None,
                   required_group=None, redirect_uri=REDIRECT),
        lambda: "s", transport=idp.transport())
    with pytest.raises(IdpUnavailable):
        await rp.build_authorize_url("s", "n", "c")
    assert idp.requests == []


# ── cache ──────────────────────────────────────────────────────────────────

async def test_discovery_cached_one_hour(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(oidc, "_now", lambda: now[0])
    idp = Idp()
    rp = _rp(idp)
    await rp.build_authorize_url("s", "n", "c")
    now[0] += 3500
    await rp.build_authorize_url("s", "n", "c")
    assert idp.hits["disc"] == 1
    now[0] += 200
    await rp.build_authorize_url("s", "n", "c")
    assert idp.hits["disc"] == 2


async def test_jwks_cached_across_validations():
    idp = Idp()
    rp = _rp(idp)
    await rp.validate_id_token(_tok(), "n-1")
    await rp.validate_id_token(_tok(), "n-1")
    assert idp.hits["jwks"] == 1


async def test_jwks_refetch_on_unknown_kid_once(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(oidc, "_now", lambda: now[0])
    idp = Idp()
    rp = _rp(idp)
    await rp.validate_id_token(_tok(), "n-1")
    idp.jwks = {"keys": [_jwk(KEY, "k1"), _jwk(OTHER_KEY, "k2")]}
    now[0] += 120
    await rp.validate_id_token(_tok(key=OTHER_KEY, kid="k2"), "n-1")
    assert idp.hits["jwks"] == 2


async def test_jwks_forced_refetch_rate_limited(monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(oidc, "_now", lambda: now[0])
    idp = Idp()
    rp = _rp(idp)
    await rp.validate_id_token(_tok(), "n-1")
    for _ in range(5):
        now[0] += 5
        with pytest.raises(IdpDenied):
            await rp.validate_id_token(_tok(kid="ghost"), "n-1")
    assert idp.hits["jwks"] == 2
    now[0] += 61
    with pytest.raises(IdpDenied):
        await rp.validate_id_token(_tok(kid="ghost"), "n-1")
    assert idp.hits["jwks"] == 3


async def test_stale_cache_served_on_refresh_failure(monkeypatch, caplog):
    now = [1000.0]
    monkeypatch.setattr(oidc, "_now", lambda: now[0])
    idp = Idp()
    rp = _rp(idp)
    await rp.validate_id_token(_tok(), "n-1")
    idp.fail_all = True
    now[0] += 3600 + 10
    with caplog.at_level(logging.WARNING, logger="agent_sdk"):
        long_lived = _tok(_claims(exp=int(time.time()) + 10 * 24 * 3600))
        user, _ = await rp.validate_id_token(long_lived, "n-1")
    assert user == f"{TENANT}:{OID}"
    assert any(r.levelno == logging.WARNING for r in caplog.records)
    now[0] += 24 * 3600
    with pytest.raises(IdpUnavailable):
        await rp.validate_id_token(long_lived, "n-1")


# ── token exchange ─────────────────────────────────────────────────────────

async def test_exchange_code_posts_client_secret_post_and_keeps_only_id_token():
    idp = Idp()
    idp.token_body = {"id_token": "the.id.token", "access_token": "AT-SENTINEL",
                      "refresh_token": "RT-SENTINEL"}
    rp = _rp(idp)
    out = await rp.exchange_code("code-1", "verifier-1")
    assert out == "the.id.token"
    req = [r for r in idp.requests if r.url.path == "/token"][0]
    form = {k: v[0] for k, v in parse_qs(req.content.decode()).items()}
    assert form == {
        "grant_type": "authorization_code", "code": "code-1", "redirect_uri": REDIRECT,
        "client_id": CLIENT_ID, "client_secret": "s3cret", "code_verifier": "verifier-1",
    }
    assert "authorization" not in req.headers
    assert "AT-SENTINEL" not in repr(rp.__dict__)


async def test_exchange_missing_secret_unavailable():
    idp = Idp()
    rp = _rp(idp, secret=None)
    with pytest.raises(IdpUnavailable):
        await rp.exchange_code("c", "v")
    assert idp.hits["token"] == 0


@pytest.mark.parametrize("status", [500, 502, 503, 302])
async def test_exchange_5xx_unavailable(status):
    idp = Idp()
    idp.token_status = status
    with pytest.raises(IdpUnavailable):
        await _rp(idp).exchange_code("c", "v")


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_exchange_4xx_denied(status):
    idp = Idp()
    idp.token_status = status
    idp.token_body = {"error": "invalid_grant"}
    with pytest.raises(IdpDenied):
        await _rp(idp).exchange_code("c", "v")


@pytest.mark.parametrize("body", [b"not json", b"[1]", b'{"no":"id_token"}', b'{"id_token": 5}'])
async def test_exchange_malformed_unavailable(body):
    idp = Idp()
    idp.token_body = body
    with pytest.raises(IdpUnavailable):
        await _rp(idp).exchange_code("c", "v")


async def test_exchange_network_error_unavailable():
    idp = Idp()
    rp = _rp(idp)
    await rp.build_authorize_url("s", "n", "c")
    idp.fail_all = True
    with pytest.raises(IdpUnavailable):
        await rp.exchange_code("c", "v")


# ── ID token ───────────────────────────────────────────────────────────────

async def test_id_token_valid_returns_user_and_label():
    user, label = await _rp(Idp()).validate_id_token(_tok(), "n-1")
    assert user == f"{TENANT}:{OID}"
    assert label == "alice@example.com"


async def test_user_key_is_tid_oid_not_email():
    user, _ = await _rp(Idp()).validate_id_token(_tok(_claims(email="x@y.z")), "n-1")
    assert "@" not in user and user == f"{TENANT}:{OID}"


async def test_non_entra_user_is_sub_and_label_falls_back_to_email():
    rp = _rp(Idp(), tenant_id=None)
    claims = _claims(tid=None, oid=None, nbf=None, preferred_username=None, email="e@x.io")
    user, label = await rp.validate_id_token(_tok(claims), "n-1")
    assert user == "sub-1"
    assert label == "e@x.io"


async def test_label_sanitised_and_capped():
    claims = _claims(preferred_username="a\x1b[31m\nb" + "z" * 400)
    _, label = await _rp(Idp()).validate_id_token(_tok(claims), "n-1")
    assert label is not None
    assert len(label) <= 128
    assert not any(ord(c) < 32 or 0x7F <= ord(c) < 0xA0 for c in label)


async def test_label_none_when_absent():
    _, label = await _rp(Idp()).validate_id_token(
        _tok(_claims(preferred_username=None)), "n-1")
    assert label is None


async def _denied(rp, token, nonce="n-1", reason=None):
    with pytest.raises(IdpDenied) as ei:
        await rp.validate_id_token(token, nonce)
    if reason:
        assert ei.value.reason_code == reason
    return ei.value


async def test_id_token_bad_signature_rejected():
    await _denied(_rp(Idp()), _tok(key=OTHER_KEY), reason="bad_signature")


async def test_id_token_alg_none_and_hs256_rejected():
    import base64
    import hashlib
    import hmac as hmac_mod

    from cryptography.hazmat.primitives import serialization

    rp = _rp(Idp())
    none_tok = jwt.encode(_claims(), None, algorithm="none", headers={"kid": "k1"})
    await _denied(rp, none_tok, reason="bad_alg")
    pub_pem = KEY.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    )

    def seg(b: bytes) -> bytes:
        return base64.urlsafe_b64encode(b).rstrip(b"=")

    head = seg(json.dumps({"alg": "HS256", "kid": "k1", "typ": "JWT"}).encode())
    body = seg(json.dumps(_claims()).encode())
    sig = seg(hmac_mod.new(pub_pem, head + b"." + body, hashlib.sha256).digest())
    await _denied(rp, (head + b"." + body + b"." + sig).decode(), reason="bad_alg")


async def test_id_token_expired_rejected():
    now = int(time.time())
    await _denied(_rp(Idp()), _tok(_claims(exp=now - 120, iat=now - 600, nbf=now - 600)),
                  reason="expired")


async def test_id_token_expired_within_leeway_accepted():
    now = int(time.time())
    await _rp(Idp()).validate_id_token(_tok(_claims(exp=now - 30)), "n-1")


async def test_id_token_nbf_future_rejected():
    now = int(time.time())
    await _denied(_rp(Idp()), _tok(_claims(nbf=now + 300)))


async def test_id_token_wrong_aud_rejected():
    await _denied(_rp(Idp()), _tok(_claims(aud="someone-else")), reason="bad_aud")


async def test_id_token_list_aud_requires_azp():
    rp = _rp(Idp())
    await _denied(rp, _tok(_claims(aud=[CLIENT_ID, "other"])))
    await _denied(rp, _tok(_claims(aud=[CLIENT_ID, "other"], azp="other")))
    await rp.validate_id_token(_tok(_claims(aud=[CLIENT_ID, "other"], azp=CLIENT_ID)), "n-1")


async def test_id_token_wrong_iss_rejected():
    await _denied(_rp(Idp()), _tok(_claims(iss="https://login.example.com/x/v2.0")),
                  reason="bad_iss")


async def test_id_token_wrong_tid_rejected():
    await _denied(_rp(Idp()), _tok(_claims(tid="00000000-0000-0000-0000-000000000000")),
                  reason="bad_tid")


async def test_id_token_wrong_nonce_rejected():
    await _denied(_rp(Idp()), _tok(), nonce="different", reason="bad_nonce")


async def test_id_token_missing_nonce_rejected():
    await _denied(_rp(Idp()), _tok(_claims(nonce=None)))


async def test_id_token_missing_oid_rejected_for_entra():
    await _denied(_rp(Idp()), _tok(_claims(oid=None)))


@pytest.mark.parametrize("claim", ["exp", "iat", "iss", "aud", "sub", "nbf", "tid"])
async def test_id_token_required_claims(claim):
    await _denied(_rp(Idp()), _tok(_claims(**{claim: None})))


async def test_id_token_unknown_kid_and_garbage_denied():
    rp = _rp(Idp())
    await _denied(rp, _tok(kid="nope"))
    await _denied(rp, "not-a-jwt")
    no_kid = jwt.encode(_claims(), KEY, algorithm="RS256")
    await _denied(rp, no_kid)


async def test_required_role_enforced():
    rp = _rp(Idp(), required_role="Agent.User")
    await _denied(rp, _tok(), reason="missing_role")
    await _denied(rp, _tok(_claims(roles=["Other"])), reason="missing_role")
    await _denied(rp, _tok(_claims(roles="Agent.User")), reason="missing_role")
    await rp.validate_id_token(_tok(_claims(roles=["Agent.User"])), "n-1")


async def test_required_group_enforced():
    rp = _rp(Idp(), required_group="g-1")
    await _denied(rp, _tok(), reason="missing_group")
    await _denied(rp, _tok(_claims(groups=["g-2"])), reason="missing_group")
    await rp.validate_id_token(_tok(_claims(groups=["g-1", "g-2"])), "n-1")


async def test_group_overage_denied():
    rp = _rp(Idp(), required_group="g-1")
    claims = _claims(_claim_names={"groups": "src1"}, groups=["g-1"])
    await _denied(rp, _tok(claims), reason="group_overage")


# ── SI-2 ───────────────────────────────────────────────────────────────────

async def test_oidc_errors_carry_no_upstream_text(caplog):
    sentinel = "UPSTREAM-SENTINEL-9f3a"
    idp = Idp()
    rp = _rp(idp)
    errs: list[BaseException] = []

    async def grab(coro):
        try:
            await coro
        except (IdpDenied, IdpUnavailable) as e:
            errs.append(e)
        else:
            raise AssertionError("expected failure")

    with caplog.at_level(logging.DEBUG, logger="agent_sdk"):
        idp.token_status = 400
        idp.token_body = {"error": sentinel, "error_description": sentinel}
        await grab(rp.exchange_code(sentinel, sentinel))
        idp.token_status = 500
        idp.token_body = sentinel.encode()
        await grab(rp.exchange_code(sentinel, sentinel))
        idp.token_status = 200
        idp.token_body = {"id_token": 1, "x": sentinel}
        await grab(rp.exchange_code(sentinel, sentinel))
        await grab(rp.validate_id_token(_tok(_claims(nonce=sentinel, sub=sentinel)), "other"))
        await grab(rp.validate_id_token(_tok(_claims(aud=sentinel)), "n-1"))
        await grab(rp.validate_id_token(sentinel, "n-1"))
        await grab(rp.validate_id_token(_tok(kid=sentinel), "n-1"))
        idp.fail_all = True
        rp2 = _rp(idp)
        await grab(rp2.build_authorize_url(sentinel, sentinel, sentinel))
        idp.fail_all = False
        idp.raw["disc"] = httpx.Response(200, content=sentinel.encode())
        await grab(_rp(idp).build_authorize_url("a", "b", "c"))
        await grab(_rp(idp, secret=None).exchange_code(sentinel, sentinel))
    for e in errs:
        assert sentinel not in str(e) and sentinel not in repr(e)
        assert "login.example.com" not in str(e)
    for r in caplog.records:
        assert sentinel not in r.getMessage()
        assert "s3cret" not in r.getMessage()
    assert len({str(e) for e in errs if isinstance(e, IdpUnavailable)}) == 1


def test_idp_denied_message_is_constant():
    assert str(IdpDenied("bad_aud")) == str(IdpDenied("expired"))
    assert IdpDenied("bad_aud").reason_code == "bad_aud"
