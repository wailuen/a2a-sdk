"""One-time org consent — opt-in bypass of the per-authorization admin gate.

Covers (GH-136):
  OTC-1  Flag OFF (default): a consented client still gets the consent page
         — existing behaviour is byte-for-byte preserved.
  OTC-2  Flag ON, never-consented client: consent page + admin gate intact.
         A fresh DCR registration can NEVER self-authorize.
  OTC-3  Flag ON, consented client: GET /oauth/authorize 303s straight to the
         registered redirect_uri with code (+state) — no page, no admin key.
  OTC-4  Flag ON: the auto-issued code is a REAL code — it exchanges at
         /oauth/token for an access token (end-to-end, PKCE S256 verified).
  OTC-5  Flag ON: an unregistered redirect_uri is still refused for a
         consented client — validation is short-circuited, never skipped.
  OTC-6  Flag ON: a malformed PKCE challenge is still refused for a consented
         client.
  OTC-7  Flag ON: POST /oauth/authorize (the explicit-approval path) still
         requires an admin key even when the client is already consented —
         the bypass is GET-only and never weakens the POST gate.

The bypass keys off the ``consented`` flag that ``mark_consented()`` already
persists in the ``__oauth_clients__`` namespace; before this feature that flag
was read only by the LRU eviction guard.

All tests use a dedicated app/client pair with the flag forced on, so the
default-off fixtures in conftest stay untouched.
"""

from __future__ import annotations

import base64
import gc
import hashlib
import json
import secrets
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient


_FORM_HEADERS = {"Content-Type": "application/x-www-form-urlencoded"}
_REDIRECT_URI = "https://claude.ai/api/mcp/auth_callback"


def _pkce() -> tuple[str, str]:
    """Return (verifier, S256 challenge) — 43 unpadded base64url chars."""
    verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return verifier, challenge


# ---------------------------------------------------------------------------
# Fixtures — flag ON (the default-OFF path is covered by the conftest client)
# ---------------------------------------------------------------------------


@pytest.fixture
def otc_app(tmp_path):
    """App with one-time consent enabled."""
    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "otc-data"),
        AGENT_NAME="otc-agent",
        AGENT_SDK_OAUTH_ONE_TIME_CONSENT=True,
    )
    built = make_agent(settings, model_client=FakeModelClient()).build_app()
    yield built
    built.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def otc_client(otc_app):
    async with otc_app.router.lifespan_context(otc_app):
        _, token = otc_app.state.auth.api_keys.mint("otc-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=otc_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            c.app = otc_app  # type: ignore[attr-defined]
            c.admin_token = token  # type: ignore[attr-defined]
            yield c


async def _register(client, redirect_uri: str = _REDIRECT_URI) -> str:
    """DCR a client; returns its client_id."""
    r = await client.post(
        "/oauth/register",
        content=json.dumps(
            {"redirect_uris": [redirect_uri], "client_name": "Claude"}
        ),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 201, f"DCR failed: {r.status_code} {r.text}"
    return r.json()["client_id"]


def _authorize_params(client_id: str, challenge: str, **over) -> dict[str, str]:
    params = {
        "client_id": client_id,
        "redirect_uri": _REDIRECT_URI,
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "xyz-state",
    }
    params.update(over)
    return params


async def _consent(client, client_id: str, challenge: str) -> None:
    """Drive the real POST approval path with an admin key (sets consented)."""
    r = await client.post(
        "/oauth/authorize",
        content=urlencode(
            _authorize_params(client_id, challenge)
            | {"api_key": client.admin_token}
        ),
        headers=_FORM_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 303, f"approval failed: {r.status_code} {r.text}"


# ===========================================================================
# OTC-1 — flag OFF (default) preserves the admin gate
# ===========================================================================


async def test_flag_off_consented_client_still_sees_consent_page(client):
    """With the flag at its default (off), an already-consented client must
    STILL be shown the admin-gated consent page. Existing deployments must
    not silently change behaviour on upgrade."""
    _, challenge = _pkce()
    client_id = await _register(client)
    # Consent via the real POST path.
    r = await client.post(
        "/oauth/authorize",
        content=urlencode(
            _authorize_params(client_id, challenge)
            | {"api_key": client.headers["Authorization"].split()[1]}
        ),
        headers=_FORM_HEADERS,
        follow_redirects=False,
    )
    assert r.status_code == 303, f"approval failed: {r.status_code} {r.text}"

    verifier2, challenge2 = _pkce()
    r2 = await client.get(
        "/oauth/authorize",
        params=_authorize_params(client_id, challenge2),
        follow_redirects=False,
    )
    assert r2.status_code == 200, (
        f"flag OFF must still render the consent page; got {r2.status_code}"
    )
    assert "Admin API key" in r2.text, (
        "flag OFF must still demand an admin API key on the consent page"
    )


# ===========================================================================
# OTC-2 — flag ON, never-consented client keeps the admin gate
# ===========================================================================


async def test_flag_on_unconsented_client_still_gated(otc_client):
    """A freshly DCR'd client has consented=False, so it must still hit the
    consent page even with the flag on. This is the property that stops an
    attacker registering their own client and self-authorizing."""
    _, challenge = _pkce()
    client_id = await _register(otc_client)

    r = await otc_client.get(
        "/oauth/authorize",
        params=_authorize_params(client_id, challenge),
        follow_redirects=False,
    )
    assert r.status_code == 200, (
        f"never-consented client must get the consent page; got {r.status_code}"
    )
    assert "Admin API key" in r.text


# ===========================================================================
# OTC-3 — flag ON, consented client authorizes silently
# ===========================================================================


async def test_flag_on_consented_client_auto_redirects(otc_client):
    """After one admin approval, a later GET /oauth/authorize for the same
    client must 303 straight to the registered redirect_uri with code+state
    — no consent page, no admin key. This is the org one-time-consent goal."""
    _, challenge = _pkce()
    client_id = await _register(otc_client)
    await _consent(otc_client, client_id, challenge)

    _, challenge2 = _pkce()
    r = await otc_client.get(
        "/oauth/authorize",
        params=_authorize_params(client_id, challenge2, state="second-user"),
        follow_redirects=False,
    )
    assert r.status_code == 303, (
        f"consented client must auto-redirect; got {r.status_code}: {r.text[:300]}"
    )
    location = r.headers.get("location", "")
    assert location.startswith(_REDIRECT_URI), (
        f"must redirect to the REGISTERED redirect_uri; got {location!r}"
    )
    query = parse_qs(urlparse(location).query)
    assert query.get("code"), f"redirect must carry a code; got {location!r}"
    assert query.get("state") == ["second-user"], (
        f"state must round-trip; got {query.get('state')!r}"
    )


# ===========================================================================
# OTC-4 — the auto-issued code is real (end-to-end exchange)
# ===========================================================================


async def test_auto_issued_code_exchanges_for_token(otc_client):
    """The silently-issued code must exchange at /oauth/token under PKCE —
    proving the bypass mints a genuine code, not a decorative redirect."""
    _, challenge = _pkce()
    client_id = await _register(otc_client)
    await _consent(otc_client, client_id, challenge)

    verifier2, challenge2 = _pkce()
    r = await otc_client.get(
        "/oauth/authorize",
        params=_authorize_params(client_id, challenge2),
        follow_redirects=False,
    )
    assert r.status_code == 303
    code = parse_qs(urlparse(r.headers["location"]).query)["code"][0]

    tok = await otc_client.post(
        "/oauth/token",
        content=urlencode(
            {
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": _REDIRECT_URI,
                "client_id": client_id,
                "code_verifier": verifier2,
            }
        ),
        headers=_FORM_HEADERS,
    )
    assert tok.status_code == 200, (
        f"auto-issued code must exchange; got {tok.status_code}: {tok.text}"
    )
    assert tok.json().get("access_token"), f"no access_token in {tok.json()}"


# ===========================================================================
# OTC-5 — validation is short-circuited, never skipped
# ===========================================================================


async def test_consented_client_unregistered_redirect_uri_refused(otc_client):
    """Consent must not license an arbitrary redirect_uri — the code can only
    ever be delivered to a URI the client registered."""
    _, challenge = _pkce()
    client_id = await _register(otc_client)
    await _consent(otc_client, client_id, challenge)

    _, challenge2 = _pkce()
    r = await otc_client.get(
        "/oauth/authorize",
        params=_authorize_params(
            client_id, challenge2, redirect_uri="https://evil.example/cb"
        ),
        follow_redirects=False,
    )
    assert r.status_code == 400, (
        f"unregistered redirect_uri must be refused; got {r.status_code}"
    )
    assert "evil.example" not in r.headers.get("location", ""), (
        "must never redirect to an unregistered URI"
    )


async def test_consented_client_bad_pkce_refused(otc_client):
    """PKCE S256 shape is still enforced for a consented client."""
    _, challenge = _pkce()
    client_id = await _register(otc_client)
    await _consent(otc_client, client_id, challenge)

    r = await otc_client.get(
        "/oauth/authorize",
        params=_authorize_params(client_id, "too-short"),
        follow_redirects=False,
    )
    assert r.status_code in (302, 400), (
        f"malformed PKCE must be refused; got {r.status_code}"
    )
    assert "code=" not in r.headers.get("location", ""), (
        "must not issue a code under a malformed PKCE challenge"
    )


# ===========================================================================
# OTC-7 — the POST approval path keeps its admin gate
# ===========================================================================


async def test_post_authorize_still_requires_admin_when_consented(otc_client):
    """The bypass is GET-only. A POST with a non-admin key must still be
    rejected even for an already-consented client — otherwise the explicit
    approval endpoint would become an unauthenticated code minter."""
    _, challenge = _pkce()
    client_id = await _register(otc_client)
    await _consent(otc_client, client_id, challenge)

    _, non_admin = otc_client.app.state.auth.api_keys.mint("plain", admin=False)
    _, challenge2 = _pkce()
    r = await otc_client.post(
        "/oauth/authorize",
        content=urlencode(
            _authorize_params(client_id, challenge2) | {"api_key": non_admin}
        ),
        headers={**_FORM_HEADERS, "Authorization": f"Bearer {non_admin}"},
        follow_redirects=False,
    )
    assert r.status_code == 401, (
        f"POST must still reject a non-admin key; got {r.status_code}"
    )
