"""GH-260: bearer-less 401 never 429s; OAuth 429 uses an OAuth error body.

Ruling: https://github.com/wailuen/a2a-sdk/issues/260#issuecomment-6393088715
"""

from __future__ import annotations

import gc
from typing import AsyncIterator

import httpx
import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.app import Agent
from agent_sdk.testing import FakeModelClient


@pytest.fixture
async def app_client(tmp_path) -> AsyncIterator[httpx.AsyncClient]:
    app = Agent(
        settings=BaseAgentSettings(
            DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent"
        ),
        model_client=FakeModelClient(),
        persona="p",
        toolsets=[],
    ).build_app()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            yield c
    app.state.credential_store.close()
    gc.collect()


async def test_bearerless_mcp_never_429(app_client):
    for _ in range(31):
        r = await app_client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "ping"})
        assert r.status_code == 401
        assert "resource_metadata" in r.headers["www-authenticate"]


async def test_invalid_bearer_still_rate_limited(app_client):
    codes = []
    for _ in range(31):
        r = await app_client.post(
            "/mcp",
            json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
            headers={"Authorization": "Bearer nope"},
        )
        codes.append(r.status_code)
    assert codes[-1] == 429


async def test_oauth_429_body_and_header(app_client):
    last = None
    for _ in range(31):
        last = await app_client.post("/oauth/token", data={"grant_type": "x"})
    assert last is not None and last.status_code == 429
    assert last.json() == {
        "error": "temporarily_unavailable",
        "error_description": "rate limit exceeded",
    }
    assert last.headers["retry-after"] == "60"


async def test_non_oauth_429_unchanged(app_client):
    codes = []
    r = None
    for _ in range(31):
        r = await app_client.get("/admin/api/keys", headers={"Authorization": "Bearer nope"})
        codes.append(r.status_code)
    assert codes[-1] == 429
    assert r is not None and r.json() == {"detail": "rate limit exceeded"}
