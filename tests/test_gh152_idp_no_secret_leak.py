"""GH-152-D SI-2/SI-4: no IdP secret, code, token, verifier, nonce or cookie leaks."""

from __future__ import annotations

import logging
from urllib.parse import parse_qs, urlparse

import httpx

from agent_sdk.credentials.store import NS_OAUTH_IDP
from tests.test_gh152_idp_authorize_flow import (  # noqa: F401  (fixtures)
    FORM,
    callback,
    ic,
    idp,
    idp_app,
    start,
    ticket_of,
    urlencode,
)

SECRET = "SENTINEL-CLIENT-SECRET-93f1"
IDP_CODE = "SENTINEL-IDP-CODE-77ab"
IDP_AT = "SENTINEL-IDP-ACCESS-TOKEN-5c2d"
IDP_RT = "SENTINEL-IDP-REFRESH-TOKEN-e804"


class Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.lines: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.lines.append(record.getMessage() + " " + str(record.exc_text) + " " + str(record.args))


def _blob(responses: list[httpx.Response]) -> str:
    parts = []
    for r in responses:
        parts.append(r.text)
        parts.extend(f"{k}: {v}" for k, v in r.headers.items() if k.lower() != "set-cookie")
    return "\n".join(parts)


async def test_no_idp_secrets_in_logs_or_responses(ic, idp):
    ic.app.state.credential_store.set(NS_OAUTH_IDP, "client_secret", SECRET)
    idp.access_token = IDP_AT
    idp.refresh_token = IDP_RT
    handler = Collector()
    root = logging.getLogger("agent_sdk")
    root.addHandler(handler)
    old = root.level
    root.setLevel(logging.DEBUG)
    responses: list[httpx.Response] = []
    redirects: list[str] = []
    secrets_seen: list[str] = [SECRET, IDP_CODE, IDP_AT, IDP_RT]
    cookies: list[str] = []
    id_tokens: list[str] = []

    async def cb(q, cookie, **kw):
        r = await callback(ic, idp, q, cookie, **kw)
        id_tokens.append(idp.claims["id_token"])
        responses.append(r)
        return r

    def note(verifier, q, cookie):
        secrets_seen.extend([verifier, q["nonce"], q["state"], q["code_challenge"]])
        cookies.append(cookie)

    try:
        # success path
        cid, verifier, q, cookie = await start(ic, idp)
        note(verifier, q, cookie)
        page = await cb(q, cookie, code=IDP_CODE)
        assert page.status_code == 200
        assert idp.token_calls == 1
        ok = await ic.post("/oauth/idp/consent", content=urlencode({"ticket": ticket_of(page), "decision": "allow"}),
                           headers={**FORM, "Cookie": f"{cookie.name}={cookie}"})
        responses.append(ok)
        redirects.append(ok.headers["location"])
        # bad nonce
        _, v2, q2, c2 = await start(ic, idp)
        note(v2, q2, c2)
        r = await cb(q2, c2, claims={"nonce": "bad"})
        redirects.append(r.headers["location"])
        # IdP-side error param
        _, v3, q3, c3 = await start(ic, idp)
        note(v3, q3, c3)
        r = await ic.get("/oauth/idp/callback", params={"error": "access_denied", "error_description": IDP_CODE, "state": q3["state"]},
                         headers={"Cookie": f"{c3.name}={c3}"})
        responses.append(r)
        redirects.append(r.headers["location"])
        # token endpoint 4xx (IdpDenied), IdP echoes sentinel in its error body
        _, v4, q4, c4 = await start(ic, idp)
        note(v4, q4, c4)
        calls = idp.token_calls
        idp.token_status = 400
        r = await cb(q4, c4, code=IDP_CODE + "x")
        idp.token_status = 200
        assert idp.token_calls == calls + 1
        redirects.append(r.headers["location"])
        # replay of a burned state
        responses.append(await callback(ic, idp, q4, c4, code=IDP_CODE))
        # missing client secret at authorize
        ic.app.state.credential_store.delete(NS_OAUTH_IDP, "client_secret")
        cidm = (await ic.post("/oauth/register", json={"redirect_uris": ["https://client.example.com/cb"]})).json()["client_id"]
        r = await ic.get("/oauth/authorize", params={
            "client_id": cidm, "redirect_uri": "https://client.example.com/cb", "response_type": "code",
            "code_challenge": "A" * 43, "code_challenge_method": "S256"})
        assert "temporarily_unavailable" in r.headers["location"]
        responses.append(r)
        redirects.append(r.headers["location"])
        ic.app.state.credential_store.set(NS_OAUTH_IDP, "client_secret", SECRET)
        # IdP down
        idp.down = True
        r = await ic.get("/oauth/authorize", params={
            "client_id": cidm, "redirect_uri": "https://client.example.com/cb", "response_type": "code",
            "code_challenge": "A" * 43, "code_challenge_method": "S256"})
        responses.append(r)
        redirects.append(r.headers["location"])
    finally:
        root.removeHandler(handler)
        root.setLevel(old)

    assert len(id_tokens) == 3 and len(set(id_tokens)) == 3
    forbidden = secrets_seen + cookies + id_tokens
    blob = _blob(responses)
    logs = "\n".join(handler.lines)
    for s in forbidden:
        for loc in redirects:
            assert s not in loc, "leaked into client redirect"
        assert s not in logs, "leaked into logs"
    for s in forbidden:
        assert s not in blob, "leaked into response"
    assert cid and parse_qs(urlparse(ok.headers["location"]).query)["code"]


async def test_idp_secret_rotation_needs_no_restart(ic, idp):
    store = ic.app.state.credential_store
    for secret in ("first-secret", "rotated-secret"):
        store.set(NS_OAUTH_IDP, "client_secret", secret)
        _, _, q, cookie = await start(ic, idp)
        r = await callback(ic, idp, q, cookie)
        assert r.status_code == 200
        assert idp.last_token_form["client_secret"] == [secret]


def _access_record(path: str) -> logging.LogRecord:
    return logging.LogRecord(
        "uvicorn.access",
        logging.INFO,
        __file__,
        1,
        '%s - "%s %s HTTP/%s" %d',
        ("127.0.0.1:1234", "GET", path, "1.1", 302),
        None,
    )


def _render_access(path: str) -> str:
    record = _access_record(path)
    access = logging.getLogger("uvicorn.access")
    assert all(f.filter(record) for f in access.filters)
    return record.getMessage()


def test_uvicorn_access_log_strips_oauth_query(idp_app):
    line = _render_access("/oauth/idp/callback?code=XSECRETCODE&state=YSECRETSTATE")
    assert "XSECRETCODE" not in line and "YSECRETSTATE" not in line
    assert "/oauth/idp/callback" in line
    other = _render_access("/v1/tasks?limit=5")
    assert "/v1/tasks?limit=5" in other


def test_uvicorn_access_filter_installed_once(idp_app):
    from agent_sdk.observability.logging import configure_access_log_filter

    configure_access_log_filter()
    configure_access_log_filter()
    access = logging.getLogger("uvicorn.access")
    assert sum(1 for f in access.filters if getattr(f, "_agent_sdk", False)) == 1
