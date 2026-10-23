"""GH-218 — /mcp/ (trailing slash) serves the same handlers as /mcp, no 307."""

from __future__ import annotations

import httpx

from agent_sdk.routes import mcp as mcp_module

_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-06-18", "capabilities": {}},
}


def _unauth(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def test_post_slash_initialize_no_redirect(client: httpx.AsyncClient) -> None:
    r = await client.post("/mcp/", json=_INIT)
    assert r.status_code == 200, r.text
    assert r.headers["mcp-session-id"]


async def test_unauthenticated_slash_routes_401_with_mcp_prm(app) -> None:
    prm = app.state.auth.prm_url
    bare = app.state.auth.bare_prm_url
    assert prm != bare
    async with app.router.lifespan_context(app):
        async with _unauth(app) as c:
            for method in ("POST", "GET", "DELETE"):
                kwargs = {"json": _INIT} if method == "POST" else {}
                r = await c.request(method, "/mcp/", **kwargs)
                assert r.status_code == 401, (method, r.status_code)
                assert f'resource_metadata="{prm}"' in r.headers["www-authenticate"]


async def test_delete_slash_matches_delete(client: httpx.AsyncClient) -> None:
    sid = (await client.post("/mcp", json=_INIT)).headers["mcp-session-id"]
    a = await client.delete("/mcp/", headers={"Mcp-Session-Id": sid})
    b = await client.delete("/mcp", headers={"Mcp-Session-Id": sid})
    assert a.status_code != 307
    assert a.status_code == 204
    assert b.status_code == a.status_code


async def test_get_slash_reaches_mcp_get(client: httpx.AsyncClient) -> None:
    headers = {"MCP-Protocol-Version": "1999-01-01"}
    a = await client.get("/mcp/", headers=headers)
    b = await client.get("/mcp", headers=headers)
    assert a.status_code == b.status_code == 400
    assert a.json() == b.json()


def test_slash_routes_use_same_endpoint_functions() -> None:
    endpoints = {
        (path, m): r.endpoint
        for r in mcp_module.router.routes
        for path in [getattr(r, "path", "")]
        if path in ("/mcp", "/mcp/")
        for m in getattr(r, "methods", ())
    }
    for method, fn in (
        ("POST", mcp_module.mcp_post),
        ("GET", mcp_module.mcp_get),
        ("DELETE", mcp_module.mcp_delete),
    ):
        assert endpoints[("/mcp", method)] is fn
        assert endpoints[("/mcp/", method)] is fn
