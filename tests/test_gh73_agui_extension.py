"""GH#73 — build_agent_card() must include ag-ui-run extension in capabilities.extensions."""

from __future__ import annotations

_AGUI_RUN_URI = "https://agent-sdk.dev/extensions/ag-ui-run/v1"


async def test_agui_run_extension_in_build_agent_card(app):
    """build_agent_card() must include ag-ui-run extension in capabilities.extensions."""
    card = app.state.agent_card
    ext_uris = [e["uri"] for e in card["capabilities"]["extensions"]]
    assert _AGUI_RUN_URI in ext_uris, (
        f"{_AGUI_RUN_URI} must appear in capabilities.extensions; got {ext_uris}"
    )


async def test_agui_run_extension_params_endpoint(app):
    """The ag-ui-run extension must declare an endpoint param ending in /ag-ui/run."""
    card = app.state.agent_card
    extension = next(
        e for e in card["capabilities"]["extensions"] if e["uri"] == _AGUI_RUN_URI
    )
    assert extension["params"]["endpoint"].endswith("/ag-ui/run"), (
        f"ag-ui-run extension endpoint must end with /ag-ui/run; "
        f"got {extension['params']['endpoint']!r}"
    )


async def test_agui_run_extension_in_live_card(client):
    """The served card must include ag-ui-run extension in capabilities.extensions."""
    r = await client.get("/.well-known/agent-card.json")
    assert r.status_code == 200
    card = r.json()
    ext_uris = [e["uri"] for e in card["capabilities"]["extensions"]]
    assert _AGUI_RUN_URI in ext_uris, (
        f"{_AGUI_RUN_URI} must appear in capabilities.extensions; got {ext_uris}"
    )
