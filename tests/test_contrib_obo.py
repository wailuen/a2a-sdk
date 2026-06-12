"""contrib.obo — MSAL on-behalf-of exchange + assertion threading + GraphSource.

Layers:
  1. scopes      — fully-qualify / dedup / OIDC pass-through.
  2. exchange    — OboExchanger over a FAKE MSAL app (no network, no real msal):
                   happy path, not-configured, bad tenant, expiry buffer, retry,
                   silent re-mint, and SECRETS HYGIENE (assertion/token never leak).
  3. context     — JWT-shape gate, bind/current, and the pure-ASGI middleware's
                   contextvar propagation into a detached worker snapshot.
  4. source      — GraphSource: no-assertion fails closed, host pinning, auth
                   header injection, JSON decode.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time

import httpx
import pytest

from agent_sdk.models.errors import AgentError, ErrorCategory
from agent_sdk.contrib.obo import (
    GRAPH_CREDENTIAL_FIELDS,
    GraphSource,
    OboAssertionMiddleware,
    OboCredentials,
    OboExchanger,
    OboToken,
    TokenExpiredError,
    bind_assertion,
    current_assertion,
    graph_scope,
    graph_scopes,
    looks_like_assertion,
    unbind_assertion,
)


# ── helpers ──
def _jwt(payload: dict) -> str:
    """Build an unsigned JWT-shaped string with the given payload claims."""
    def seg(obj: dict) -> str:
        raw = json.dumps(obj).encode()
        return base64.urlsafe_b64encode(raw).decode().rstrip("=")
    return f"{seg({'alg': 'none'})}.{seg(payload)}.{seg({'sig': 'x'})}"


def _access_token(*, oid="oid-1", tid="tid-1", scp="User.Read Mail.Read") -> str:
    claims: dict = {"scp": scp}
    if oid:
        claims["oid"] = oid
    if tid:
        claims["tid"] = tid
    return _jwt(claims)


def _inbound(aud="cid", **claims) -> str:
    """A JWT-shaped inbound user assertion. Default ``aud`` matches
    ``_CREDS.client_id`` so it passes the exchanger's default audience pre-check
    and reaches the (fake) MSAL app. Pass ``aud=None`` to omit the claim, or a
    different value to exercise a refusal."""
    payload: dict = {"sub": "u"}
    if aud is not None:
        payload["aud"] = aud
    payload.update(claims)
    return _jwt(payload)


class FakeMsalApp:
    """Records the assertion it was handed (to PROVE we never log it) and returns
    a scripted result. Stands in for msal.ConfidentialClientApplication."""

    def __init__(self, *, obo_result=None, accounts=None, silent_result=None):
        self.obo_result = obo_result
        self.accounts = accounts or []
        self.silent_result = silent_result
        self.seen_assertions: list[str] = []

    def acquire_token_on_behalf_of(self, user_assertion, scopes):
        self.seen_assertions.append(user_assertion)
        return self.obo_result

    def get_accounts(self):
        return self.accounts

    def acquire_token_silent(self, scopes, account):
        return self.silent_result


_CREDS = OboCredentials(tenant_id="contoso.onmicrosoft.com", client_id="cid", client_secret="sec")


def _exchanger(app: FakeMsalApp, *, creds=_CREDS, buffer=300, scopes=None):
    return OboExchanger(
        credentials_provider=lambda: creds,
        scopes=scopes or ["https://graph.microsoft.com/User.Read"],
        expiry_buffer_seconds=buffer,
        app_factory=lambda c: app,
    )


# ── 1. scopes ──
def test_graph_scope_qualifies_and_is_idempotent():
    assert graph_scope("Mail.Read") == "https://graph.microsoft.com/Mail.Read"
    # already-qualified is unchanged
    assert graph_scope("https://graph.microsoft.com/Mail.Read") == (
        "https://graph.microsoft.com/Mail.Read"
    )
    # OIDC scopes are resource-less — never prefixed
    assert graph_scope("offline_access") == "offline_access"
    # a different resource URI passes through untouched
    assert graph_scope("api://other/.default") == "api://other/.default"


def test_graph_scopes_dedups_preserving_order():
    out = graph_scopes("User.Read", "Mail.Read", "User.Read")
    assert out == [
        "https://graph.microsoft.com/User.Read",
        "https://graph.microsoft.com/Mail.Read",
    ]


# ── 2. exchange ──
async def test_exchange_happy_path_returns_token_and_account():
    app = FakeMsalApp(obo_result={"access_token": _access_token()})
    ex = _exchanger(app)
    tok = await ex.exchange(_inbound())
    assert isinstance(tok, OboToken)
    assert tok.access_token == app.obo_result["access_token"]
    assert tok.home_account_id == "oid-1.tid-1"
    assert tok.scopes == ("https://graph.microsoft.com/User.Read",)
    # granted_scopes reflects the access token's scp (Entra may downscope)
    assert tok.granted_scopes == ("User.Read", "Mail.Read")


async def test_exchange_not_configured_raises_auth():
    ex = OboExchanger(
        credentials_provider=lambda: None,
        scopes=["https://graph.microsoft.com/User.Read"],
        app_factory=lambda c: FakeMsalApp(),
    )
    with pytest.raises(AgentError) as ei:
        await ex.exchange(_jwt({"sub": "u"}))
    assert ei.value.category is ErrorCategory.AUTH
    assert "not configured" in ei.value.message


async def test_exchange_bad_tenant_id_is_rejected_without_echo():
    bad = OboCredentials(tenant_id="bad/../inject", client_id="c", client_secret="s")
    ex = _exchanger(FakeMsalApp(obo_result={"access_token": _access_token()}), creds=bad)
    with pytest.raises(AgentError) as ei:
        await ex.exchange(_jwt({"sub": "u"}))
    assert ei.value.category is ErrorCategory.AUTH
    # generic message — the offending value is never echoed
    assert "bad/../inject" not in str(ei.value) and "bad/../inject" not in str(ei.value.detail)


async def test_assertion_within_buffer_raises_expired_and_is_not_retried():
    app = FakeMsalApp(obo_result={"access_token": _access_token()})
    ex = _exchanger(app, buffer=300)
    near = _jwt({"exp": time.time() + 60})  # expires in 60s, buffer is 300s
    with pytest.raises(TokenExpiredError):
        await ex.exchange_with_retry(near)
    assert app.seen_assertions == []  # never handed to MSAL


async def test_exchange_failure_sanitizes_jwt_in_error_description():
    leaked = _jwt({"sub": "leak"})
    app = FakeMsalApp(
        obo_result={
            "error": "invalid_grant",
            "error_description": f"AADSTS500133: bad assertion: {leaked}",
        }
    )
    ex = _exchanger(app)
    with pytest.raises(AgentError) as ei:
        await ex.exchange(_inbound())
    err = ei.value
    assert err.category is ErrorCategory.AUTH
    # the JWT fragment must be scrubbed everywhere it could surface
    assert leaked not in str(err)
    assert leaked not in str(err.detail)
    assert "<redacted-jwt>" in err.detail["error_description"]
    # public() never carries detail at all (defense in depth)
    assert "error_description" not in err.public()


async def test_exchange_with_retry_retries_transient_then_succeeds():
    # first call transient, second call ok — emulate via a swappable result
    app = FakeMsalApp(obo_result={"error": "temporarily_unavailable", "error_description": "x"})
    ex = _exchanger(app)

    real = app.acquire_token_on_behalf_of
    state = {"n": 0}

    def flaky(user_assertion, scopes):
        state["n"] += 1
        if state["n"] == 1:
            return {"error": "temporarily_unavailable", "error_description": "retry me"}
        return {"access_token": _access_token()}

    app.acquire_token_on_behalf_of = flaky  # type: ignore[assignment]
    tok = await ex.exchange_with_retry(_inbound())
    assert tok.access_token  # succeeded on the retry
    assert state["n"] == 2


async def test_exchange_with_retry_does_not_retry_permanent_error():
    state = {"n": 0}
    app = FakeMsalApp()

    def perm(user_assertion, scopes):
        state["n"] += 1
        return {"error": "invalid_client", "error_description": "bad secret"}

    app.acquire_token_on_behalf_of = perm  # type: ignore[assignment]
    ex = _exchanger(app)
    with pytest.raises(AgentError):
        await ex.exchange_with_retry(_inbound())
    assert state["n"] == 1  # no retry on a non-transient error


async def test_token_for_account_silent_remint():
    app = FakeMsalApp(
        accounts=[{"home_account_id": "oid-1.tid-1"}],
        silent_result={"access_token": "reminted"},
    )
    ex = _exchanger(app)
    assert await ex.token_for_account("oid-1.tid-1") == "reminted"


async def test_token_for_account_no_cached_account_raises():
    ex = _exchanger(FakeMsalApp(accounts=[]))
    with pytest.raises(AgentError) as ei:
        await ex.token_for_account("missing")
    assert ei.value.category is ErrorCategory.AUTH


def test_empty_scopes_rejected():
    with pytest.raises(ValueError):
        OboExchanger(credentials_provider=lambda: _CREDS, scopes=[])


async def test_wrong_audience_refused_before_reaching_msal():
    # Confused-deputy guard: an assertion minted for a DIFFERENT resource is
    # refused locally and never relayed to Entra.
    app = FakeMsalApp(obo_result={"access_token": _access_token()})
    ex = _exchanger(app)
    with pytest.raises(AgentError) as ei:
        await ex.exchange(_inbound(aud="some-other-resource"))
    assert ei.value.category is ErrorCategory.AUTH
    assert app.seen_assertions == []  # never handed to MSAL


async def test_audience_default_accepts_api_uri_form():
    # The default allow-list includes both "cid" and "api://cid".
    app = FakeMsalApp(obo_result={"access_token": _access_token()})
    ex = _exchanger(app)
    await ex.exchange(_inbound(aud="api://cid"))
    assert len(app.seen_assertions) == 1


async def test_audience_override_accepts_custom_app_id_uri():
    app = FakeMsalApp(obo_result={"access_token": _access_token()})
    ex = OboExchanger(
        credentials_provider=lambda: _CREDS,
        scopes=["https://graph.microsoft.com/User.Read"],
        app_factory=lambda c: app,
        expected_audiences=["api://custom-app-id-uri"],
    )
    await ex.exchange(_inbound(aud="api://custom-app-id-uri"))
    assert len(app.seen_assertions) == 1
    # and the default forms are now NOT accepted
    app.seen_assertions.clear()
    with pytest.raises(AgentError):
        await ex.exchange(_inbound(aud="cid"))
    assert app.seen_assertions == []


async def test_missing_audience_is_left_for_msal():
    # No aud claim → we do not invent one; MSAL remains the gate (so it reaches it).
    app = FakeMsalApp(obo_result={"access_token": _access_token()})
    ex = _exchanger(app)
    await ex.exchange(_inbound(aud=None))
    assert len(app.seen_assertions) == 1


async def test_audience_claim_as_list_matches_on_intersection():
    app = FakeMsalApp(obo_result={"access_token": _access_token()})
    ex = _exchanger(app)
    await ex.exchange(_inbound(aud=["unrelated", "cid"]))
    assert len(app.seen_assertions) == 1


async def test_non_finite_exp_is_treated_as_expired():
    # A NaN/inf exp must not slip past the buffer via NaN comparison semantics.
    app = FakeMsalApp(obo_result={"access_token": _access_token()})
    ex = _exchanger(app)
    for bad in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(TokenExpiredError):
            await ex.exchange(_inbound(exp=bad))
    assert app.seen_assertions == []


async def test_msal_exception_becomes_generic_auth_error_without_leak():
    # If the MSAL call RAISES (not returns an error dict), the exception — which
    # could carry the assertion or secret — must not propagate.
    secret_marker = "SECRET-IN-STACKTRACE"
    app = FakeMsalApp()

    def boom(user_assertion, scopes):
        raise RuntimeError(f"msal internal error {secret_marker} {user_assertion}")

    app.acquire_token_on_behalf_of = boom  # type: ignore[assignment]
    ex = _exchanger(app)
    with pytest.raises(AgentError) as ei:
        await ex.exchange(_inbound())
    err = ei.value
    assert err.category is ErrorCategory.AUTH
    assert secret_marker not in str(err)
    assert secret_marker not in str(err.detail)
    assert err.__cause__ is None  # original suppressed (raise ... from None)
    assert err.__context__ is None  # nulled — no leak via a __context__-walking serializer


def test_credentials_repr_masks_secret():
    r = repr(OboCredentials(tenant_id="t", client_id="c", client_secret="super-secret"))
    assert "super-secret" not in r
    assert "[redacted]" in r


def test_token_repr_masks_access_token():
    r = repr(OboToken("the-access-token", "oid.tid", ("User.Read",)))
    assert "the-access-token" not in r
    assert "[redacted]" in r


# ── 3. context / threading ──
def test_looks_like_assertion():
    assert looks_like_assertion(_jwt({"a": 1})) is True
    assert looks_like_assertion("opaque-api-key-no-dots") is False
    assert looks_like_assertion("a.b") is False  # only two segments
    assert looks_like_assertion("a..c") is False  # empty middle segment
    assert looks_like_assertion("a.b!.c") is False  # non-base64url char


def test_bind_non_jwt_binds_none():
    tok = bind_assertion("opaque-key")
    try:
        assert current_assertion() is None  # opaque never treated as an assertion
    finally:
        unbind_assertion(tok)


async def test_middleware_binds_jwt_bearer_for_handler():
    jwt = _jwt({"sub": "u"})
    seen = {}

    async def app(scope, receive, send):
        seen["v"] = current_assertion()

    mw = OboAssertionMiddleware(app)
    scope = {"type": "http", "headers": [(b"authorization", b"Bearer " + jwt.encode())]}
    await mw(scope, None, None)
    assert seen["v"] == jwt
    assert current_assertion() is None  # reset after the request


async def test_middleware_ignores_opaque_and_missing_bearer():
    async def app(scope, receive, send):
        app.seen = current_assertion()

    mw = OboAssertionMiddleware(app)
    await mw({"type": "http", "headers": [(b"authorization", b"Bearer opaquekey")]}, None, None)
    assert app.seen is None
    await mw({"type": "http", "headers": []}, None, None)
    assert app.seen is None


async def test_middleware_finds_bearer_among_multiple_auth_headers():
    # A non-Bearer auth scheme on one header must not short-circuit a later Bearer.
    jwt = _jwt({"sub": "u"})
    seen = {}

    async def app(scope, receive, send):
        seen["v"] = current_assertion()

    mw = OboAssertionMiddleware(app)
    scope = {
        "type": "http",
        "headers": [
            (b"authorization", b"Negotiate abc"),
            (b"authorization", b"Bearer " + jwt.encode()),
        ],
    }
    await mw(scope, None, None)
    assert seen["v"] == jwt


async def test_worker_snapshot_survives_request_reset():
    # THE core design claim: a detached worker (create_task) keeps the assertion
    # even after the middleware resets the request context in its finally block.
    jwt = _jwt({"sub": "u"})
    gate = asyncio.Event()
    seen = {}
    holder = {}

    async def worker():
        await gate.wait()  # runs AFTER the middleware's finally-reset
        seen["v"] = current_assertion()

    async def app(scope, receive, send):
        holder["t"] = asyncio.create_task(worker())  # snapshots context here

    mw = OboAssertionMiddleware(app)
    scope = {"type": "http", "headers": [(b"authorization", b"Bearer " + jwt.encode())]}
    await mw(scope, None, None)
    assert current_assertion() is None  # request context reset
    gate.set()
    await holder["t"]
    assert seen["v"] == jwt  # worker snapshot survived


async def test_middleware_passes_through_non_http_scopes():
    called = {}

    async def app(scope, receive, send):
        called["type"] = scope["type"]

    mw = OboAssertionMiddleware(app)
    await mw({"type": "lifespan"}, None, None)
    assert called["type"] == "lifespan"


# ── 4. GraphSource ──
def _resolver(creds: dict):
    def resolve(_source_name: str, field: str):
        return creds.get(field)
    return resolve


class StubExchanger:
    def __init__(self, token="gtok"):
        self.token = token
        self.calls: list[str] = []

    async def exchange_with_retry(self, assertion):
        self.calls.append(assertion)
        return OboToken(self.token, "oid.tid", ("User.Read",))


async def test_graphsource_bearer_requires_assertion():
    src = GraphSource(object(), _resolver({}), exchanger=StubExchanger())
    # no assertion bound → fail closed with AUTH
    with pytest.raises(AgentError) as ei:
        await src.bearer()
    assert ei.value.category is ErrorCategory.AUTH


async def test_graphsource_bearer_exchanges_current_assertion():
    ex = StubExchanger("tok-123")
    src = GraphSource(object(), _resolver({}), exchanger=ex)
    jwt = _jwt({"sub": "u"})
    tok = bind_assertion(jwt)
    try:
        assert await src.bearer() == "tok-123"
        assert ex.calls == [jwt]
    finally:
        unbind_assertion(tok)


async def test_graphsource_pins_host_before_minting():
    ex = StubExchanger()
    src = GraphSource(object(), _resolver({}), exchanger=ex)
    with pytest.raises(AgentError) as ei:
        await src.graph_request("GET", "https://evil.example.com/steal")
    assert ei.value.category is ErrorCategory.VALIDATION
    assert ex.calls == []  # never minted a token for a rejected host


@pytest.mark.parametrize(
    "url",
    [
        "https://graph.microsoft.com.evil.com/me",   # suffix-extension lookalike
        "https://graph.microsoft.com@evil.com/me",   # userinfo confusion
        "https://evilgraph.microsoft.com/me",         # prefix-extension lookalike
        "https://graph.microsoft.com.evil.com",       # no path
    ],
)
async def test_graphsource_rejects_host_lookalikes_before_minting(url):
    ex = StubExchanger()
    src = GraphSource(object(), _resolver({}), exchanger=ex)
    with pytest.raises(AgentError) as ei:
        await src.graph_request("GET", url)
    assert ei.value.category is ErrorCategory.VALIDATION
    assert ex.calls == []  # host rejected before any token mint


async def test_graphsource_injects_auth_and_decodes_json():
    ex = StubExchanger("tok-xyz")
    src = GraphSource(object(), _resolver({}), exchanger=ex)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["auth"] = request.headers.get("authorization")
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"id": "42"})

    src._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    jwt = _jwt({"sub": "u"})
    tok = bind_assertion(jwt)
    try:
        body = await src.graph_json("GET", "/me")
    finally:
        unbind_assertion(tok)
        await src.aclose()
    assert body == {"id": "42"}
    assert captured["auth"] == "Bearer tok-xyz"
    assert captured["url"] == "https://graph.microsoft.com/v1.0/me"


def test_graph_credential_fields_are_lowercase_and_secret_flagged():
    by_name = {f.name: f for f in GRAPH_CREDENTIAL_FIELDS}
    assert set(by_name) == {"azure_tenant_id", "azure_client_id", "azure_client_secret"}
    assert by_name["azure_client_secret"].secret is True
    assert by_name["azure_tenant_id"].secret is False  # IDs are not secrets
