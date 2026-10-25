"""GH-271 item 5: TaskStore.get() keeps a live task's runtime-only fields.

Ruling: https://github.com/wailuen/a2a-sdk/issues/271#issuecomment-6398502964
"""

from __future__ import annotations

import gc
import uuid

import httpx
import pytest

import agent_sdk.tasks.memory  # noqa: F401  (registers the bundled store)
from agent_sdk.app import Agent
from agent_sdk.example.agent import make_agent
from agent_sdk.models.content_types import A2UI_EXTENSION_URI
from agent_sdk.tasks.store import TaskStore
from agent_sdk.testing import FakeModelClient, reply


def _bundled_stores() -> list[type[TaskStore]]:
    found: list[type[TaskStore]] = []
    stack = list(TaskStore.__subclasses__())
    while stack:
        cls = stack.pop()
        if cls.__module__.startswith("agent_sdk.tasks") and cls not in found:
            found.append(cls)
        stack.extend(cls.__subclasses__())
    return found


def test_at_least_one_bundled_store_is_covered() -> None:
    assert _bundled_stores()


@pytest.mark.parametrize("store_cls", _bundled_stores(), ids=lambda c: c.__name__)
async def test_get_keeps_runtime_fields_and_binds_identity(settings, store_cls) -> None:
    model = FakeModelClient().script(reply("ok"))
    base = make_agent(settings, model_client=model)
    agent = Agent(
        settings=settings,
        persona="test",
        toolsets=list(base.toolsets),
        model_client=model,
        task_store=store_cls(),
    )
    app = agent.build_app()
    try:
        async with app.router.lifespan_context(app):
            keys = app.state.auth.api_keys
            _, tok_a = keys.mint("owner")
            _, tok_b = keys.mint("other")
            ident_a = keys.verify(tok_a)
            ident_b = keys.verify(tok_b)
            assert ident_a is not None and ident_b is not None
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": f"Bearer {tok_a}"},
            ) as c:
                r = await c.post(
                    "/v1/message:send",
                    json={
                        "message": {
                            "role": "user",
                            "parts": [{"kind": "text", "text": "go"}],
                            "messageId": uuid.uuid4().hex,
                        },
                        "configuration": {"acceptedOutputModes": ["application/json"]},
                    },
                    headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
                )
                assert r.status_code == 200, r.text
                task_id = r.json()["id"]
            store = app.state.task_store
            record = store.get(task_id, ident_a)
            assert record is not None
            assert record.accepted_output_modes == ["application/json"]
            assert app.state.a2ui_enabled is True
            assert record.a2ui_opted_in is True
            assert store.get(task_id, ident_b) is None
    finally:
        app.state.credential_store.close()
        gc.collect()
