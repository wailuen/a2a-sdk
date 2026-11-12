"""GH-277: the DCR client_name is never a display label."""

from __future__ import annotations

import gc
import logging
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest

import agent_sdk
from agent_sdk import BaseAgentSettings
from agent_sdk.auth.oauth_tokens import OAuthTokenStore
from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient
from tests.test_gh152_idp_authorize_flow import (
    CB,
    FORM,
    OID,
    TENANT,
    _token,
    idp,  # noqa: F401
    idp_app,  # noqa: F401
    ic,  # noqa: F401
    pkce,
    start,
    callback,
    ticket_of,
    _consent_body,
)

NAME = "alice@corp"


def _settings(tmp_path, **extra) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent", **extra
    )


@pytest.fixture
async def plain(tmp_path):
    app = make_agent(_settings(tmp_path), model_client=FakeModelClient()).build_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            c.app = app  # type: ignore[attr-defined]
            yield c
    app.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def onetime(tmp_path):
    app = make_agent(
        _settings(tmp_path, AGENT_SDK_OAUTH_ONE_TIME_CONSENT=True),
        model_client=FakeModelClient(),
    ).build_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            c.app = app  # type: ignore[attr-defined]
            yield c
    app.state.credential_store.close()
    gc.collect()


async def _register_named(c) -> str:
    r = await c.post("/oauth/register", json={"redirect_uris": [CB], "client_name": NAME})
    return r.json()["client_id"]


def _authorize_fields(cid, challenge, **extra):
    return {
        "client_id": cid, "redirect_uri": CB, "response_type": "code",
        "code_challenge": challenge, "code_challenge_method": "S256", "state": "st", **extra,
    }


def _code(r: httpx.Response) -> str:
    return parse_qs(urlparse(r.headers["location"]).query)["code"][0]


async def test_admin_key_consent_label_is_oauth_tag(plain):
    cid = await _register_named(plain)
    verifier, challenge = pkce()
    _, key = plain.app.state.auth.api_keys.mint("adm", admin=True)
    r = await plain.post(
        "/oauth/authorize",
        content=urlencode(_authorize_fields(cid, challenge, api_key=key)),
        headers=FORM,
    )
    assert r.status_code == 303
    t = await _token(plain, cid, verifier, _code(r))
    assert t.status_code == 200
    ident = plain.app.state.oauth.verify(t.json()["access_token"])
    assert ident is not None
    assert ident.label == f"oauth:{cid[:8]}"
    assert NAME not in ident.label


async def test_one_time_consent_label_is_oauth_tag(onetime):
    cid = await _register_named(onetime)
    onetime.app.state.oauth.mark_consented(cid)
    verifier, challenge = pkce()
    r = await onetime.get("/oauth/authorize", params=_authorize_fields(cid, challenge))
    assert r.status_code == 303, r.text
    t = await _token(onetime, cid, verifier, _code(r))
    assert t.status_code == 200
    ident = onetime.app.state.oauth.verify(t.json()["access_token"])
    assert ident is not None
    assert ident.label == f"oauth:{cid[:8]}"
    assert NAME not in ident.label


async def _idp_identity(ic, idp, claims):
    cid, verifier, q, cookie = await start(ic, idp)
    page = await callback(ic, idp, q, cookie, claims=claims)
    r = await ic.post(
        "/oauth/idp/consent", content=_consent_body(ticket_of(page)),
        headers={**FORM, "Cookie": f"{cookie.name}={cookie}"},
    )
    assert r.status_code == 303
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]
    t = await _token(ic, cid, verifier, code)
    assert t.status_code == 200
    return cid, ic.app.state.oauth.verify(t.json()["access_token"]), t.json()


async def test_idp_without_username_claims_gets_oauth_tag(ic, idp):
    cid, ident, _ = await _idp_identity(
        ic, idp, {"preferred_username": None, "email": None}
    )
    assert ident is not None
    assert ident.label == f"oauth:{cid[:8]}"
    assert ident.user == f"{TENANT}:{OID}"


async def test_idp_username_claim_keeps_sanitized_label(ic, idp):
    _, ident, _ = await _idp_identity(ic, idp, {"preferred_username": "bob@example.com"})
    assert ident is not None
    assert ident.label == "bob@example.com"


def _store(app):
    return app.state.oauth


async def _refresh(c, cid: str, refresh_token: str) -> httpx.Response:
    return await c.post(
        "/oauth/token",
        content=urlencode(
            {"grant_type": "refresh_token", "client_id": cid, "refresh_token": refresh_token}
        ),
        headers=FORM,
    )


async def test_refresh_route_clears_label_equal_to_client_name_keeps_others(plain, caplog):
    store = _store(plain.app)
    cid = await _register_named(plain)
    old = store.mint_token_pair(
        client_id=cid, scope="mcp", audience=store.canonical_resource, label=NAME
    )
    keep = store.mint_token_pair(
        client_id=cid, scope="mcp", audience=store.canonical_resource, label="idp-label@x.com"
    )
    caplog.set_level(logging.DEBUG)
    r_old = await _refresh(plain, cid, old["refresh_token"])
    assert r_old.status_code == 200
    new = r_old.json()
    ident = store.verify(new["access_token"])
    assert ident is not None and ident.label == f"oauth:{cid[:8]}"
    r_keep = await _refresh(plain, cid, keep["refresh_token"])
    assert r_keep.status_code == 200
    ident2 = store.verify(r_keep.json()["access_token"])
    assert ident2 is not None and ident2.label == "idp-label@x.com"
    r_newer = await _refresh(plain, cid, new["refresh_token"])
    assert r_newer.status_code == 200
    ident3 = store.verify(r_newer.json()["access_token"])
    assert ident3 is not None and ident3.label == f"oauth:{cid[:8]}"
    assert NAME not in r_old.text + r_keep.text + r_newer.text
    logged = "\n".join(r.getMessage() for r in caplog.records)
    assert "oauth token issued grant=refresh" in logged
    for secret in (NAME, old["refresh_token"], new["refresh_token"], keep["refresh_token"]):
        assert secret not in logged
    assert cid not in logged.replace(cid[:8], "")


class _FlakyClientReads(OAuthTokenStore):
    fail = False

    def get_client(self, client_id: str):
        if self.fail:
            raise RuntimeError("transient store error")
        return super().get_client(client_id)


async def test_client_lookup_failure_leaves_presented_refresh_token_usable(tmp_path):
    cred = EncryptedSqliteStore(tmp_path / "c.db", "k" * 32)
    store = _FlakyClientReads(
        cred, issuer="https://a.example", canonical_resource="https://a.example/mcp"
    )
    cid = store.register_client([CB], client_name=NAME)["client_id"]
    pair = store.mint_token_pair(
        client_id=cid, scope="mcp", audience=store.canonical_resource, label=NAME
    )
    store.fail = True
    with pytest.raises(RuntimeError):
        store.rotate_refresh(pair["refresh_token"], client_id=cid)
    store.fail = False
    retry = store.rotate_refresh(pair["refresh_token"], client_id=cid)
    assert retry is not None
    ident = store.verify(retry["access_token"])
    assert ident is not None and ident.label == f"oauth:{cid[:8]}"


LABEL_SOURCE = re.compile(
    r"""\blabel\s*=(?!=)[^\n]*client_name"""
    r"""|or\s+client\.get\(["']client_name["']\)"""
    r"""|\blabel\b[^\n]*==[^\n]*client_name"""
)


def label_source_hits(files: dict[str, str]) -> list[tuple[str, int, str]]:
    hits = []
    for path, text in files.items():
        for n, line in enumerate(text.splitlines(), 1):
            if LABEL_SOURCE.search(line):
                hits.append((path, n, line.strip()))
    return hits


def _sdk_sources() -> dict[str, str]:
    root = Path(agent_sdk.__file__).parent
    return {str(p.relative_to(root)): p.read_text() for p in root.rglob("*.py")}


def test_client_name_is_only_label_related_in_rotate_refresh():
    hits = label_source_hits(_sdk_sources())
    assert len(hits) == 1, hits
    path, _, line = hits[0]
    assert path.endswith("auth/oauth_tokens.py")
    assert "==" in line


def test_label_scan_catches_fallback_put_back():
    files = _sdk_sources()
    key = next(k for k in files if k.endswith("routes/oauth.py"))
    assert 'label = meta.get("label")\n' in files[key]
    files[key] = files[key].replace(
        'label = meta.get("label")\n',
        'label = meta.get("label") or client.get("client_name")\n',
        1,
    )
    assert len(label_source_hits(files)) == 2
