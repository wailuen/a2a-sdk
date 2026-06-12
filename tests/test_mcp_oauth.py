"""MCP + OAuth surface integration over the built app (thin layer —
the deep protocol behavior was smoke-tested during implementation)."""

from __future__ import annotations


async def test_oauth_discovery_chain(client):
    for path in (
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-protected-resource/mcp",
        "/.well-known/oauth-authorization-server",
    ):
        r = await client.get(path)
        assert r.status_code == 200, path
    meta = (await client.get("/.well-known/oauth-authorization-server")).json()
    assert "S256" in meta["code_challenge_methods_supported"]


async def test_mcp_requires_auth_with_prm_pointer(client):
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        headers={"Authorization": ""},
    )
    assert r.status_code == 401
    assert "resource_metadata=" in r.headers.get("www-authenticate", "")


async def test_mcp_tools_list_tier1_only(client):
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
        },
    )
    assert r.status_code == 200, r.text
    session = r.headers.get("mcp-session-id")
    headers = {"Mcp-Session-Id": session} if session else {}
    headers["MCP-Protocol-Version"] = "2025-06-18"
    r = await client.post(
        "/mcp",
        json={"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        headers=headers,
    )
    tools = {t["name"] for t in r.json()["result"]["tools"]}
    assert "echo" in tools and "demo_kpis" in tools
    assert "demo_trend" not in tools and "publish_note" not in tools  # tier 2
    kpis = next(t for t in r.json()["result"]["tools"] if t["name"] == "demo_kpis")
    assert "outputSchema" in kpis  # derived from emits
    echo = next(t for t in r.json()["result"]["tools"] if t["name"] == "echo")
    assert "outputSchema" not in echo


async def test_cors_preflight(client):
    r = await client.options(
        "/mcp",
        headers={
            "Origin": "https://claude.ai",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert r.status_code == 204
    assert r.headers["access-control-allow-origin"] == "https://claude.ai"
