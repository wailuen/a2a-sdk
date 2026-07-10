"""Shared fixtures: isolated example agent + FakeModelClient + live ASGI client.

Test-isolation note (RT-CONTENT-TYPES-REGISTRY-GLOBAL-STATE)
-------------------------------------------------------------
``agent_sdk.models.content_types`` uses two module-level globals:

* ``_REGISTRY`` — maps data_type str → ContentModel subclass.
* ``_PROFILE_SEALED`` — set to ``True`` once the Standard Profile types are
  registered at import time; never reset.

Tests in ``test_content_types.py`` that register temporary domain cards clean
up via ``try/finally: _REGISTRY.pop(...)`` blocks, which is safe under the
current *sequential* CI execution model (pytest-xdist disabled).

If parallel test execution (``-n auto``) is ever introduced:

1. Refactor ``_REGISTRY`` and ``_PROFILE_SEALED`` into pytest fixtures with
   ``function`` scope, or monkeypatch ``_REGISTRY`` at the start of each
   test that registers a temporary type.
2. Ensure no test relies on import-time side-effects of ``content_types`` to
   be idempotent with a clean registry; instead restore state explicitly in
   teardown.

Until parallel execution is enabled, the sequential guarantee makes the
existing try/finally pattern sufficient.
"""

from __future__ import annotations

import asyncio
import gc
import logging
from contextlib import contextmanager
from typing import AsyncIterator, Iterator

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
    built = make_agent(settings, model_client=fake_model).build_app()
    yield built
    built.state.credential_store.close()
    gc.collect()


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


@pytest.fixture
def sdk_caplog():
    """Factory fixture: capture log records directly from a named ``agent_sdk.*``
    logger, independent of caplog's root-logger propagation.

    ``agent_sdk.observability.logging.configure_logging()`` sets
    ``propagate = False`` on the ``agent_sdk`` root logger the first time any
    test in the session builds an app. From that point on, records emitted by
    loggers under ``agent_sdk`` may never reach the stdlib root logger that
    plain ``caplog`` attaches to — whether they do depends on pytest-version
    behaviour and exact test order, so a bare ``caplog.at_level(...)`` /
    ``caplog.records`` assertion against an ``agent_sdk.*`` logger can pass in
    isolation yet read empty at full-suite scope. Attaching a handler directly
    to the target logger sidesteps propagation and the root logger entirely,
    so capture is deterministic regardless of test order or pytest version.

    Usage::

        with sdk_caplog("agent_sdk.agent.loop", logging.WARNING) as records:
            ...
        assert any("foo" in r.getMessage() for r in records)
    """

    @contextmanager
    def _capture(logger_name: str, level: int = logging.WARNING) -> Iterator[list[logging.LogRecord]]:
        records: list[logging.LogRecord] = []

        class _Collector(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        target = logging.getLogger(logger_name)
        handler = _Collector()
        handler.setLevel(level)
        orig_level = target.level
        target.setLevel(level)
        target.addHandler(handler)
        try:
            yield records
        finally:
            target.removeHandler(handler)
            target.setLevel(orig_level)

    return _capture


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
