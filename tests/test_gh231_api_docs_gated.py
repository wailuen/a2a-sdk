import gc

import httpx
import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient

DOC_PATHS = ["/openapi.json", "/docs", "/redoc", "/docs/oauth2-redirect"]


def _build(tmp_path, dev_mode: bool):
    settings = BaseAgentSettings(
        DEV_MODE=dev_mode,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        **({} if dev_mode else {
            "PUBLIC_URL": "https://agent.example.com",
            "MASTER_KEY": "test-master-key-32-chars-minimum!!",
        }),
    )
    return make_agent(settings, model_client=FakeModelClient()).build_app()


async def _get(app, path: str) -> int:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        return (await c.get(path)).status_code


@pytest.mark.asyncio
@pytest.mark.parametrize("path", DOC_PATHS)
async def test_docs_routes_404_when_not_dev_mode(tmp_path, path) -> None:
    app = _build(tmp_path, dev_mode=False)
    try:
        assert await _get(app, path) == 404
    finally:
        app.state.credential_store.close()
        gc.collect()


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/openapi.json", "/docs", "/redoc"])
async def test_docs_routes_200_in_dev_mode(tmp_path, path) -> None:
    app = _build(tmp_path, dev_mode=True)
    try:
        assert await _get(app, path) == 200
    finally:
        app.state.credential_store.close()
        gc.collect()


def test_no_docs_routes_mounted_when_not_dev_mode(tmp_path) -> None:
    app = _build(tmp_path, dev_mode=False)
    try:
        paths = {getattr(r, "path", None) for r in app.routes}
        assert not paths & set(DOC_PATHS)
    finally:
        app.state.credential_store.close()
        gc.collect()
