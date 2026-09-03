"""RT-003 (GH-147 AC3): repair_dangling_tool_use must bridge the trailing
'user' message on EVERY exit path, not only the dangling-toolUse append path.

Root cause: repair_dangling_tool_use returned early — before ever reaching
its own ``bridge_trailing_user(messages)`` call — whenever the last message
wasn't an assistant toolUse turn. ``routes/a2a.py``'s ``tasks_cancel`` relies
entirely on this helper to bridge the trailing 'user' message (the worker's
own ``except asyncio.CancelledError: raise`` deliberately leaves
record.messages untouched — "the canceller owns status + final frame").

Two shapes reach that early return with a trailing 'user' message already in
place, cancelling before ANY dangling toolUse exists:

* cancelling while the model is still "thinking" (blocked awaiting
  ``model.converse()`` on turn 1) — record.messages is just the initial
  ``['user']`` turn, so ``last.get("role") != "assistant"`` fires.
* cancelling between turns (blocked awaiting ``model.converse()`` on turn 2,
  after turn 1's tool round already folded assistant toolUse + user
  toolResult) — record.messages is ``['user', 'assistant', 'user']``, same
  early return.

Both left record.messages ending on 'user'; CANCELED is a terminal state, so
context_messages() replays it and _create_task_record appends another 'user'
turn — two consecutive 'user' messages, the exact shape GH-147 AC3 says must
never occur.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import Any

import httpx
import pytest

from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient, reply, tool_call

from .conftest import wait_for_state

pytestmark = pytest.mark.asyncio


class _BlockingModelClient:
    """Wraps a FakeModelClient; blocks forever on the ``block_on_call``'th
    ``converse()`` invocation (1-indexed) after signalling ``started``."""

    def __init__(self, inner: FakeModelClient, *, block_on_call: int) -> None:
        self._inner = inner
        self._block_on_call = block_on_call
        self._n = 0
        self.started = asyncio.Event()

    async def converse(self, **kwargs: Any) -> Any:
        self._n += 1
        if self._n == self._block_on_call:
            self.started.set()
            await asyncio.Event().wait()  # never released — cancel() interrupts this
        return await self._inner.converse(**kwargs)


@pytest.fixture
def fake_model() -> FakeModelClient:
    return FakeModelClient()


@pytest.fixture
def blocking_client(fake_model, request) -> _BlockingModelClient:
    block_on_call = getattr(request, "param", 1)
    return _BlockingModelClient(fake_model, block_on_call=block_on_call)


def _app(settings, blocking_client):
    built = make_agent(settings, model_client=blocking_client).build_app()
    return built


@pytest.fixture
def rt003_app(settings, blocking_client):
    built = _app(settings, blocking_client)
    yield built
    built.state.credential_store.close()


@pytest.fixture
async def rt003_client(rt003_app):
    async with rt003_app.router.lifespan_context(rt003_app):
        _, token = rt003_app.state.auth.api_keys.mint("test-admin", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=rt003_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10.0,
        ) as c:
            yield c


def send_body(
    text: str, *, task_id: str | None = None, context_id: str | None = None
) -> dict[str, Any]:
    msg: dict[str, Any] = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": uuid.uuid4().hex,
    }
    if task_id:
        msg["taskId"] = task_id
    if context_id:
        msg["contextId"] = context_id
    return {"message": msg}


def roles_have_no_adjacent_duplicate(roles: list[str]) -> bool:
    return all(a != b for a, b in zip(roles, roles[1:]))


# ── AC: cancel while the model is thinking (turn 1) bridges trailing user ──


@pytest.mark.parametrize("blocking_client", [1], indirect=True)
async def test_cancel_while_model_thinking_bridges_trailing_user(
    rt003_client, blocking_client, rt003_app
):
    r = await rt003_client.post("/v1/message:send", json=send_body("think slowly"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    context_id = r.json()["contextId"]

    await asyncio.wait_for(blocking_client.started.wait(), timeout=2.0)

    r = await rt003_client.post(f"/v1/tasks/{task_id}:cancel")
    assert r.status_code == 200, r.text
    assert r.json()["status"]["state"] == "canceled"

    record = rt003_app.state.task_store.get(task_id)
    assert record is not None
    roles = [m["role"] for m in record.messages]
    assert roles, "expected the initial user turn to still be present"
    assert roles[-1] != "user", (
        f"record.messages left ending on 'user' after cancel-while-thinking: {roles!r}"
    )
    assert roles_have_no_adjacent_duplicate(roles), f"adjacent same-role messages: {roles}"

    # contextId continuation must never replay two consecutive 'user' turns.
    blocking_client._inner.calls.clear()
    blocking_client._inner.script(reply("turn two after cancel"))
    r2 = await rt003_client.post(
        "/v1/message:send", json=send_body("turn two", context_id=context_id)
    )
    assert r2.status_code == 200, r2.text
    task2_id = r2.json()["id"]
    await wait_for_state(rt003_client, task2_id)

    assert blocking_client._inner.calls, "converse must have been called for turn 2"
    replayed_roles = [m["role"] for m in blocking_client._inner.calls[0]["messages"]]
    assert roles_have_no_adjacent_duplicate(
        replayed_roles
    ), f"adjacent same-role messages sent upstream: {replayed_roles}"


# ── AC: cancel between turns (after a completed tool round) also bridges ──


@pytest.mark.parametrize("blocking_client", [2], indirect=True)
async def test_cancel_between_turns_bridges_trailing_user(
    rt003_client, blocking_client, rt003_app
):
    blocking_client._inner.script(tool_call("echo", {"text": "hi"}))

    r = await rt003_client.post("/v1/message:send", json=send_body("use a tool then stall"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    context_id = r.json()["contextId"]

    await asyncio.wait_for(blocking_client.started.wait(), timeout=2.0)

    record_before = rt003_app.state.task_store.get(task_id)
    assert record_before is not None
    roles_before = [m["role"] for m in record_before.messages]
    assert roles_before[-1] == "user", (
        f"expected the tool-round toolResult fold to leave messages ending "
        f"on 'user' before cancel: {roles_before!r}"
    )

    r = await rt003_client.post(f"/v1/tasks/{task_id}:cancel")
    assert r.status_code == 200, r.text
    assert r.json()["status"]["state"] == "canceled"

    record = rt003_app.state.task_store.get(task_id)
    assert record is not None
    roles = [m["role"] for m in record.messages]
    assert roles[-1] != "user", (
        f"record.messages left ending on 'user' after cancel-between-turns: {roles!r}"
    )
    assert roles_have_no_adjacent_duplicate(roles), f"adjacent same-role messages: {roles}"

    blocking_client._inner.calls.clear()
    blocking_client._inner.script(reply("turn two after cancel"))
    r2 = await rt003_client.post(
        "/v1/message:send", json=send_body("turn two", context_id=context_id)
    )
    assert r2.status_code == 200, r2.text
    task2_id = r2.json()["id"]
    await wait_for_state(rt003_client, task2_id)

    assert blocking_client._inner.calls, "converse must have been called for turn 2"
    replayed_roles = [m["role"] for m in blocking_client._inner.calls[0]["messages"]]
    assert roles_have_no_adjacent_duplicate(
        replayed_roles
    ), f"adjacent same-role messages sent upstream: {replayed_roles}"
