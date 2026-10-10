"""GH-152-A: IdP settings, boot validation, reserved secret namespace, admin card."""

from __future__ import annotations

import builtins
import gc
import logging
import sys

import httpx
import pytest
from pydantic import ValidationError

from agent_sdk import BaseAgentSettings
from agent_sdk.config import parse_idp_issuer
from agent_sdk.credentials.store import NS_OAUTH_IDP, RESERVED_NAMESPACES, resolver_for_source
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient

TENANT = "11111111-2222-3333-4444-555555555555"
GOOD_ISSUER = f"https://login.microsoftonline.com/{TENANT}/v2.0"


def _settings(tmp_path, **extra):
    return BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent", **extra
    )


def _idp(tmp_path, **extra):
    base = {
        "AGENT_SDK_OAUTH_IDP": "oidc",
        "AGENT_SDK_OAUTH_IDP_ISSUER": GOOD_ISSUER,
        "AGENT_SDK_OAUTH_IDP_CLIENT_ID": "client-id",
    }
    base.update(extra)
    return _settings(tmp_path, **base)


def _build(settings):
    app = make_agent(settings, model_client=FakeModelClient()).build_app()
    app.state.credential_store.close()
    gc.collect()
    return app


def test_defaults(tmp_path):
    s = _settings(tmp_path)
    assert s.oauth_idp == "none"
    assert s.oauth_idp_session_hours == 720
    assert s.oauth_idp_disable_api_keys is False
    assert s.oauth_idp_issuer is None


def test_unknown_idp_value_fails_validation(tmp_path):
    with pytest.raises(ValidationError):
        _settings(tmp_path, AGENT_SDK_OAUTH_IDP="saml")


@pytest.mark.parametrize("hours", [0, 2161])
def test_session_hours_bounds(tmp_path, hours):
    with pytest.raises(ValidationError):
        _settings(tmp_path, AGENT_SDK_OAUTH_IDP_SESSION_HOURS=hours)


def test_parse_issuer_returns_tenant_guid():
    assert parse_idp_issuer(GOOD_ISSUER) == TENANT


def test_parse_issuer_non_entra_returns_none():
    assert parse_idp_issuer("https://example.okta.com/oauth2/default") is None


@pytest.mark.parametrize(
    "issuer",
    [
        "http://example.okta.com/x",
        "https://example.okta.com/x?a=1",
        "https://example.okta.com/x#frag",
        f"https://login.microsoftonline.com/{TENANT}/v2.0?x=1",
        f"https://login.microsoftonline.com/{TENANT}",
        f"https://login.microsoftonline.com/{TENANT}/v1.0",
    ],
)
def test_parse_issuer_refuses_malformed(issuer):
    with pytest.raises(ValueError):
        parse_idp_issuer(issuer)


@pytest.mark.parametrize(
    "issuer",
    [
        "https://login.microsoftonline.com/common/v2.0",
        "https://login.microsoftonline.com/organizations/v2.0",
        "https://login.microsoftonline.com/consumers/v2.0",
        "https://login.microsoftonline.com/9188040d-6c67-4c5b-b112-36a304b66dad/v2.0",
        "https://login.microsoftonline.com/9188040D-6C67-4C5B-B112-36A304B66DAD/v2.0",
        "https://login.microsoftonline.com/contoso.onmicrosoft.com/v2.0",
        f"https://sts.windows.net/{TENANT}/",
    ],
)
def test_boot_refuses_multi_tenant_issuer_aliases(tmp_path, issuer):
    with pytest.raises(ValueError) as exc:
        _build(_idp(tmp_path, AGENT_SDK_OAUTH_IDP_ISSUER=issuer))
    assert "AGENT_SDK_OAUTH_IDP_ISSUER" in str(exc.value)


def test_boot_accepts_good_entra_issuer(tmp_path):
    _build(_idp(tmp_path))


def test_boot_refuses_one_time_consent_with_idp(tmp_path):
    with pytest.raises(ValueError, match="cannot be combined with AGENT_SDK_OAUTH_IDP=oidc"):
        _build(_idp(tmp_path, AGENT_SDK_OAUTH_ONE_TIME_CONSENT=True))


@pytest.mark.parametrize(
    "missing", ["AGENT_SDK_OAUTH_IDP_ISSUER", "AGENT_SDK_OAUTH_IDP_CLIENT_ID"]
)
def test_boot_refuses_missing_issuer_or_client_id(tmp_path, missing):
    s = _idp(tmp_path)
    setattr(s, {"AGENT_SDK_OAUTH_IDP_ISSUER": "oauth_idp_issuer",
                "AGENT_SDK_OAUTH_IDP_CLIENT_ID": "oauth_idp_client_id"}[missing], None)
    with pytest.raises(ValueError, match=missing):
        _build(s)


def test_boot_refuses_missing_oidc_extra(tmp_path, monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "jwt" or name.startswith("jwt."):
            raise ImportError("no jwt")
        return real_import(name, *a, **k)

    monkeypatch.delitem(sys.modules, "jwt", raising=False)
    monkeypatch.setattr(builtins, "__import__", fake_import)
    with pytest.raises(ValueError, match=r"agent-sdk\[oidc\]"):
        _build(_idp(tmp_path))


def test_boot_refuses_disable_api_keys_without_idp(tmp_path):
    with pytest.raises(ValueError, match="AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS"):
        _build(_settings(tmp_path, AGENT_SDK_OAUTH_IDP_DISABLE_API_KEYS=True))


def test_boot_warns_when_idp_secret_missing(tmp_path, sdk_caplog):
    with sdk_caplog("agent_sdk", logging.WARNING) as records:
        _build(_idp(tmp_path))
    msgs = [r.getMessage() for r in records if "client_secret" in r.getMessage()]
    assert len(msgs) == 1
    assert "Credentials" in msgs[0]


def test_boot_warns_on_unsupported_surfaces_setting(tmp_path, monkeypatch, sdk_caplog):
    monkeypatch.setenv("AGENT_SDK_OAUTH_IDP_SURFACES", "mcp")
    with sdk_caplog("agent_sdk", logging.WARNING) as records:
        _build(_idp(tmp_path))
    msgs = [r.getMessage() for r in records if "AGENT_SDK_OAUTH_IDP_SURFACES" in r.getMessage()]
    assert len(msgs) == 1
    assert "ignored" in msgs[0]


def test_idp_off_boot_is_silent_and_does_not_import_jwt(tmp_path, monkeypatch, sdk_caplog):
    monkeypatch.delitem(sys.modules, "jwt", raising=False)
    with sdk_caplog("agent_sdk", logging.DEBUG) as records:
        _build(_settings(tmp_path))
    assert "jwt" not in sys.modules
    assert not [r for r in records if "idp" in r.getMessage().lower()]


def test_oauth_idp_namespace_reserved(tmp_path):
    assert NS_OAUTH_IDP == "__oauth_idp__"
    assert NS_OAUTH_IDP in RESERVED_NAMESPACES
    app = _build(_settings(tmp_path))
    with pytest.raises(ValueError):
        resolver_for_source(app.state.credential_store, NS_OAUTH_IDP)


async def test_admin_can_set_idp_client_secret(client):
    r = await client.put(
        f"/admin/api/credentials/{NS_OAUTH_IDP}/client_secret", json={"value": "s3cret-sentinel"}
    )
    assert r.status_code == 200
    assert client.app.state.credential_store.get(NS_OAUTH_IDP, "client_secret") == "s3cret-sentinel"
    r = await client.delete(f"/admin/api/credentials/{NS_OAUTH_IDP}/client_secret")
    assert r.status_code == 200
    assert client.app.state.credential_store.get(NS_OAUTH_IDP, "client_secret") is None


async def test_idp_secret_card_never_returns_value(client):
    await client.put(
        f"/admin/api/credentials/{NS_OAUTH_IDP}/client_secret", json={"value": "s3cret-sentinel"}
    )
    r = await client.get("/admin/api/credentials")
    assert "s3cret-sentinel" not in r.text
    card = r.json()["oauth_idp"]
    assert card["source_name"] == NS_OAUTH_IDP
    assert [f["name"] for f in card["fields"]] == ["client_secret"]
    assert card["fields"][0]["set"] is True


async def test_idp_secret_requires_admin(client):
    app = client.app
    _, user_token = app.state.auth.api_keys.mint("plain-user", admin=False)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {user_token}"},
    ) as c:
        r = await c.put(
            f"/admin/api/credentials/{NS_OAUTH_IDP}/client_secret", json={"value": "x"}
        )
        assert r.status_code == 403
        assert (await c.get("/admin/api/credentials")).status_code == 403


OKTA_ISSUER = "https://example.okta.com/oauth2/default"
OPT_OUT = "AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS"


def test_allow_all_default_false(tmp_path):
    assert _settings(tmp_path).oauth_idp_allow_all_issuer_users is False


def test_boot_refuses_non_entra_issuer_without_gate(tmp_path):
    with pytest.raises(ValueError) as exc:
        _build(_idp(tmp_path, AGENT_SDK_OAUTH_IDP_ISSUER=OKTA_ISSUER))
    msg = str(exc.value)
    assert OPT_OUT in msg
    assert "AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE" in msg
    assert "AGENT_SDK_OAUTH_IDP_REQUIRED_GROUP" in msg
    assert "okta" not in msg


@pytest.mark.parametrize(
    "gate",
    [
        {"AGENT_SDK_OAUTH_IDP_REQUIRED_ROLE": "agent-users"},
        {"AGENT_SDK_OAUTH_IDP_REQUIRED_GROUP": "agent-group"},
    ],
)
def test_boot_accepts_non_entra_issuer_with_role_or_group(tmp_path, gate):
    _build(_idp(tmp_path, AGENT_SDK_OAUTH_IDP_ISSUER=OKTA_ISSUER, **gate))


def test_boot_accepts_opt_out_with_exactly_one_warning(tmp_path, sdk_caplog):
    with sdk_caplog("agent_sdk", logging.WARNING) as records:
        _build(_idp(tmp_path, AGENT_SDK_OAUTH_IDP_ISSUER=OKTA_ISSUER, **{OPT_OUT: True}))
    msgs = [r.getMessage() for r in records if OPT_OUT in r.getMessage()]
    assert len(msgs) == 1
    assert "every account" in msgs[0]


def test_boot_refuses_opt_out_without_oidc(tmp_path):
    with pytest.raises(ValueError, match=OPT_OUT):
        _build(_settings(tmp_path, **{OPT_OUT: True}))


def test_entra_guid_issuer_boots_without_gate_or_warning(tmp_path, sdk_caplog):
    with sdk_caplog("agent_sdk", logging.WARNING) as records:
        _build(_idp(tmp_path))
    assert not [r for r in records if OPT_OUT in r.getMessage()]
