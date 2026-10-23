"""GH-219: agent card advertises the SDK's own OAuth authorization server."""

from __future__ import annotations

from agent_sdk.models.a2a import AgentCard


async def _card(client, **headers):
    r = await client.get("/.well-known/agent-card.json", headers=headers)
    assert r.status_code == 200
    return r.json()


async def test_card_advertises_oauth2_and_bearer(client):
    card = await _card(client)
    assert card["security"] == [{"bearer": []}, {"oauth2": []}]
    assert card["securitySchemes"]["bearer"] == {"type": "http", "scheme": "bearer"}
    assert "oauth2" in card["securitySchemes"]
    assert not any(s.get("type") == "openIdConnect" for s in card["securitySchemes"].values())


async def test_card_oauth2_urls_match_authorization_server_metadata(client):
    card = await _card(client)
    meta = (await client.get("/.well-known/oauth-authorization-server")).json()
    oauth2 = card["securitySchemes"]["oauth2"]
    assert oauth2["type"] == "oauth2"
    assert oauth2["oauth2MetadataUrl"] == f"{meta['issuer']}/.well-known/oauth-authorization-server"
    flow = oauth2["flows"]["authorizationCode"]
    assert flow["authorizationUrl"] == meta["authorization_endpoint"]
    assert flow["tokenUrl"] == meta["token_endpoint"]
    assert flow["scopes"] == {}


async def test_card_still_validates_against_a2a_model(client):
    AgentCard.model_validate(await _card(client))


async def test_oauth2_urls_ignore_spoofed_host_headers(client):
    plain = await _card(client)
    spoofed = await _card(
        client,
        Host="evil.example",
        **{"X-Forwarded-Host": "evil.example", "X-Forwarded-Proto": "http"},
    )
    assert spoofed["securitySchemes"] == plain["securitySchemes"]
    assert "evil.example" not in str(spoofed["securitySchemes"])


async def test_extended_card_security_matches_public_when_advertised(client, app):
    card = await _card(client)
    assert card["supportsAuthenticatedExtendedCard"] is False
    assert card["securitySchemes"] == app.state.agent_card["securitySchemes"]
    assert card["security"] == app.state.agent_card["security"]
