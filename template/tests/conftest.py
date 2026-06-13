"""Isolated agent fixtures — FakeModelClient, no Bedrock, no real upstreams."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import AsyncIterator

import httpx
import pytest

from agent_sdk import Agent, CredentialField
from agent_sdk.testing import FakeModelClient

from src.config import Settings
from src.sources.sample_api import SampleApiAdapter
from src.tools import widgets


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(DEV_MODE=True, DATA_DIR=str(tmp_path / "data"))


@pytest.fixture
def fake_model() -> FakeModelClient:
    return FakeModelClient()


@pytest.fixture
def app(settings, fake_model):
    agent = Agent(
        settings=settings,
        artifacts_dir=Path(__file__).parent.parent / "src" / "artifacts",
        skills_dir=Path(__file__).parent.parent / "src" / "skills",
        toolsets=[widgets.tools],
        model_client=fake_model,
    )
    agent.register_source(
        SampleApiAdapter,
        credentials=[
            CredentialField(name="api_token", label="Sample API token", secret=True),
        ],
    )
    return agent.build_app()


@pytest.fixture
async def client(app) -> AsyncIterator[httpx.AsyncClient]:
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
