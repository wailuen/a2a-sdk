"""GH-75: A2A §5.3 requires POST /v1/tasks/{id}:resubscribe, not :subscribe."""

from __future__ import annotations

import uuid

import pytest

from agent_sdk.testing import reply

from .conftest import wait_for_state


async def test_resubscribe_route_exists(client, fake_model):
    """GH-75 AC: POST /v1/tasks/{task_id}:resubscribe must return SSE, not 404."""
    fake_model.script(reply("done"))
    r = await client.post(
        "/v1/message:send",
        json={
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "hi"}],
                "messageId": uuid.uuid4().hex,
            }
        },
    )
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    r2 = await client.post(f"/v1/tasks/{task_id}:resubscribe")
    assert r2.status_code != 404, (
        "POST /v1/tasks/{id}:resubscribe returned 404 — route must be :resubscribe per A2A §5.3"
    )
    assert r2.status_code in (200, 400, 410), f"Unexpected status: {r2.status_code}"


async def test_subscribe_route_gone(client, fake_model):
    """GH-75 AC: :subscribe path must not succeed — clients must use :resubscribe."""
    fake_model.script(reply("done"))
    r = await client.post(
        "/v1/message:send",
        json={
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "hi"}],
                "messageId": uuid.uuid4().hex,
            }
        },
    )
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    r2 = await client.post(f"/v1/tasks/{task_id}:subscribe")
    assert r2.status_code in (404, 405), (
        f":subscribe should be 404 or 405 (route removed); got {r2.status_code}"
    )
