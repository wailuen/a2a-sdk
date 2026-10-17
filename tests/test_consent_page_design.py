"""Consent page redesign: TPC mark, agent name, shared layout, CSP-safe.

Both consent pages (admin-key ``GET /oauth/authorize`` and the IdP sign-in
consent) render through ``routes/_consent_ui.render_consent_page``. The page
must stay self-contained under the consent CSP (``default-src 'none'``): no
script, no image fetch, no external stylesheet or font.
"""

from __future__ import annotations

import json
import re

import httpx

from agent_sdk.routes._consent_ui import render_consent_page
from agent_sdk.routes._tpc_logo import TPC_LOGO_SVG
from agent_sdk.routes.oauth import _idp_consent_page

_REDIRECT = "https://claude.ai/api/mcp/auth_callback"
_CODE_CHALLENGE = "E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM"


def _render(**overrides: str) -> str:
    kwargs: dict[str, str] = {
        "agent_name": "a2a-teamwork",
        "client_name": "Microsoft 365 Copilot",
        "return_host": "teams.microsoft.com",
        "audience": "https://agent.example.com/mcp",
        "form_action": "/oauth/idp/consent",
        "form_html": '<button type="submit" class="primary">Allow</button>',
    }
    kwargs.update(overrides)
    return render_consent_page(**kwargs)  # type: ignore[arg-type]


def _assert_self_contained(page: str) -> None:
    lowered = page.lower()
    assert "<script" not in lowered
    assert "<img" not in lowered
    assert "<link" not in lowered
    assert "@import" not in lowered
    assert "url(" not in lowered
    # The only absolute URL allowed is the SVG namespace on the inline mark.
    urls = set(re.findall(r'(?:src|href)\s*=\s*["\']?(https?://[^"\'\s>]+)', page))
    assert urls == set(), urls


def test_logo_is_inline_svg_without_style_or_script() -> None:
    assert TPC_LOGO_SVG.startswith('<svg class="logo" role="img" aria-label="TPC"')
    assert TPC_LOGO_SVG.endswith("</svg>")
    for banned in ("<style", "<script", "<image", "href=", "class=\"st"):
        assert banned not in TPC_LOGO_SVG


def test_page_shows_mark_agent_and_client() -> None:
    page = _render(signed_in_as="alice@example.com")
    assert TPC_LOGO_SVG in page
    assert "Built by TPC" in page
    assert "Microsoft 365 Copilot wants to access a2a-teamwork" in page
    assert "Signed in as <strong>alice@example.com</strong>" in page
    assert "teams.microsoft.com" in page
    assert '<form method="post" action="/oauth/idp/consent">' in page
    _assert_self_contained(page)


def test_page_supports_dark_mode_and_phone_width() -> None:
    page = _render()
    assert "@media (prefers-color-scheme: dark)" in page
    assert "@media (max-width: 480px)" in page
    assert '<meta name="viewport"' in page


def test_every_raw_value_is_escaped() -> None:
    evil = '<script>alert(1)</script>"'
    page = _render(
        agent_name=evil,
        client_name=evil,
        return_host=evil,
        audience=evil,
        signed_in_as=evil,
        error=evil,
        allow_label=evil,
    )
    assert "<script>alert(1)" not in page
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in page


def test_idp_page_keeps_ticket_and_decisions() -> None:
    cleaned = {
        "client_name": "Claude",
        "redirect_uri": _REDIRECT,
        "audience": "https://agent.example.com/mcp",
    }
    r = _idp_consent_page(cleaned, None, "flow.ticket", agent_name="alphageo")
    page = r.body.decode()
    assert 'name="ticket" value="flow.ticket"' in page
    assert 'name="decision" value="allow"' in page
    assert 'name="decision" value="deny"' in page
    assert "Signed in as <strong>your account</strong>" in page
    assert "Claude wants to access alphageo" in page
    _assert_self_contained(page)


async def test_admin_consent_page_renders_new_layout(client: httpx.AsyncClient) -> None:
    r = await client.post(
        "/oauth/register",
        content=json.dumps({"redirect_uris": [_REDIRECT]}),
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 201, r.text
    client_id = r.json()["client_id"]
    r = await client.get(
        "/oauth/authorize",
        params={
            "client_id": client_id,
            "redirect_uri": _REDIRECT,
            "response_type": "code",
            "code_challenge": _CODE_CHALLENGE,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert r.status_code == 200, r.text
    page = r.text
    assert TPC_LOGO_SVG in page
    agent = client.app.state.settings.display_name  # type: ignore[attr-defined]
    assert f"wants to access {agent}" in page
    assert 'name="api_key"' in page and ">Approve</button>" in page
    assert '<form method="post" action="/oauth/authorize">' in page
    assert "default-src 'none'" in r.headers["content-security-policy"]
    _assert_self_contained(page)
