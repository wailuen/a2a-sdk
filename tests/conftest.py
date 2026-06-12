"""Shared fixtures: isolated example agent + FakeModelClient + live ASGI client."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

import httpx
import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient


@pytest.fixture
def settings(tmp_path) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent"
    )


@pytest.fixture
def fake_model() -> FakeModelClient:
    return FakeModelClient()


@pytest.fixture
def app(settings, fake_model):
    return make_agent(settings, model_client=fake_model).build_app()


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
    """Lifespan-managed client; admin bearer pre-set on headers."""
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            c.app = app  # type: ignore[attr-defined]
            yield c


async def wait_for_state(client, task_id: str, states=("completed", "failed"), timeout=5.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while True:
        r = await client.get(f"/v1/tasks/{task_id}")
        assert r.status_code == 200, r.text
        task = r.json()
        if task["status"]["state"] in states:
            return task
        if asyncio.get_event_loop().time() > deadline:
            raise AssertionError(f"task stuck in {task['status']['state']}")
        await asyncio.sleep(0.02)


def sse_frames(text: str) -> list[dict]:
    import json

    return [
        json.loads(line[len("data: "):])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]
