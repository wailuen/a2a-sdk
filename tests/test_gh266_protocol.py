"""GH-266: per-call-site HTTP status for -32004, client codes in wire_errors.

Ruling: https://github.com/wailuen/a2a-sdk/issues/266#issuecomment-6395232882
"""

from __future__ import annotations

import uuid

import pytest

from agent_sdk.agent.runner import new_task
from agent_sdk.common.wire_errors import a2a_error
from agent_sdk.testing import reply

from .conftest import wait_for_state
from .test_gh248_a2a_route import _identity_of


def _body(task_id: str | None = None) -> dict:
    msg: dict = {
        "role": "user",
        "parts": [{"kind": "text", "text": "again"}],
        "messageId": uuid.uuid4().hex,
    }
    if task_id:
        msg["taskId"] = task_id
    return {"message": msg}


async def _completed_task(client, fake_model) -> str:
    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=_body())
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, {"completed", "failed", "canceled"})
    return task_id


async def test_terminal_resume_send_is_400(client, fake_model) -> None:
    task_id = await _completed_task(client, fake_model)
    r = await client.post("/v1/message:send", json=_body(task_id))
    assert (r.status_code, r.json()["error"]["code"]) == (400, -32004)


async def test_terminal_resume_stream_is_400(client, fake_model) -> None:
    task_id = await _completed_task(client, fake_model)
    r = await client.post("/v1/message:stream", json=_body(task_id))
    assert (r.status_code, r.json()["error"]["code"]) == (400, -32004)


async def test_not_awaiting_input_send_is_400(client, app) -> None:
    ident = _identity_of(app, client)
    task_id = app.state.task_store.create(new_task(), ident).task.id
    r = await client.post("/v1/message:send", json=_body(task_id))
    assert (r.status_code, r.json()["error"]["code"]) == (400, -32004)
    assert r.json()["error"]["message"] == "task is not awaiting input"


async def test_colon_guard_stays_501(client) -> None:
    r = await client.get("/v1/tasks/abc:cancel")
    assert (r.status_code, r.json()["error"]["code"]) == (501, -32004)


def test_a2a_error_default_status_for_32004_stays_501() -> None:
    assert a2a_error(-32004, "x").status_code == 501


@pytest.mark.parametrize("code,status", [(-32600, 400), (-32601, 404), (-32700, 400), (-32602, 400)])
def test_client_codes_map_to_4xx(code: int, status: int) -> None:
    assert a2a_error(code, "x").status_code == status
