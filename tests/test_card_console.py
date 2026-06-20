"""Agent card (§4.5), console contract assertions (§5.3/§7)."""

from __future__ import annotations

from pathlib import Path

from agent_sdk.routes.agent_card import CUSTOM_EVENTS

CONSOLE_STATIC = Path(__file__).parent.parent / "agent_sdk" / "console" / "static"


async def test_card_shape(client):
    r = await client.get("/.well-known/agent-card.json")
    card = r.json()
    assert card["protocolVersion"] == "0.3.0"
    assert card["preferredTransport"] == "HTTP+JSON"
    # HTTP+JSON: clients append /v1/message:send etc. to url; url must be the server root, not the endpoint prefix
    assert not card["url"].endswith("/v1"), f"card url must be server root, not endpoint prefix: {card['url']}"
    assert card["url"].startswith("http"), f"card url must be absolute: {card['url']}"
    assert card["capabilities"]["streaming"] is True
    assert card["capabilities"]["pushNotifications"] is False
    assert card["supportsAuthenticatedExtendedCard"] is False
    exts = [e["uri"] for e in card["capabilities"]["extensions"]]
    assert "https://a2ui.org/a2a-extension/a2ui/v0.9.1" in exts
    assert "https://agent-sdk.dev/extensions/ag-ui-run/v1" in exts
    a2ui_ext = next(e for e in card["capabilities"]["extensions"] if e["uri"] == "https://a2ui.org/a2a-extension/a2ui/v0.9.1")
    params = a2ui_ext["params"]
    assert "urn:a2ui-profile:standard:v1" in params["supportedCatalogIds"]
    assert params["acceptsInlineCatalogs"] is False
    # skills carry only spec fields + x-sdk
    for skill in card["skills"]:
        bare = set(skill) - {
            "id", "name", "description", "tags", "examples",
            "inputModes", "outputModes", "security", "x-sdk",
        }
        assert not bare, bare
    assert card["x-agui"]["endpoint"].endswith("/ag-ui/run")
    # P6-01: customEvents are now objects with name + valueSchema (not flat strings)
    custom_event_names = {e["name"] for e in card["x-agui"]["customEvents"]}
    assert custom_event_names == set(CUSTOM_EVENTS)
    # never emit v1.0-only fields
    assert "supportedInterfaces" not in card


async def test_card_etag_and_alias(client):
    r = await client.get("/.well-known/agent-card.json")
    etag = r.headers["etag"]
    r304 = await client.get(
        "/.well-known/agent-card.json", headers={"If-None-Match": etag}
    )
    assert r304.status_code == 304
    alias = await client.get("/.well-known/agent.json")
    assert alias.content == r.content


def test_custom_events_match_console_routing_table():
    """§5.3: card customEvents and the console routing table are equal."""
    chat_js = (CONSOLE_STATIC / "chat.js").read_text()
    for name in CUSTOM_EVENTS:
        assert name in chat_js, f"console chat.js does not route {name}"
    # Tighter check: TOOL_CALL_ARGS and TOOL_CALL_END must appear as switch cases,
    # not just incidentally elsewhere in the file (e.g. comments).
    assert 'case "TOOL_CALL_ARGS"' in chat_js, \
        "chat.js switch is missing case \"TOOL_CALL_ARGS\""
    assert 'case "TOOL_CALL_END"' in chat_js, \
        "chat.js switch is missing case \"TOOL_CALL_END\""


async def test_console_page_and_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    r = await client.get("/admin")
    assert r.status_code == 200
    csp = r.headers.get("content-security-policy", "")
    assert "script-src 'self'" in csp and "'unsafe-inline'" not in csp
    r = await client.get("/admin/static/console.js")
    assert r.status_code == 200
    # traversal blocked
    r = await client.get("/admin/static/../../config.py")
    assert r.status_code in (400, 404)
