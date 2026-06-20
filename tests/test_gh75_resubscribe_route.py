"""GH-75 (corrected): A2A §2 transport table + §3.5.6 confirm REST path is
POST /v1/tasks/{id}:subscribe; JSON-RPC method name is tasks/resubscribe."""

from __future__ import annotations

import uuid

import pytest

from agent_sdk.testing import reply

from .conftest import wait_for_state


async def test_subscribe_route_exists(client, fake_model):
    """AC: POST /v1/tasks/{task_id}:subscribe must return SSE, not 404.

    The REST action suffix is :subscribe per A2A §2 transport table and §3.5.6.
    """
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
    assert r2.status_code != 404, (
        "POST /v1/tasks/{id}:subscribe returned 404 — route must be :subscribe per A2A §2/§3.5.6"
    )
    assert r2.status_code in (200, 400, 410), f"Unexpected status: {r2.status_code}"


async def test_resubscribe_route_gone(client, fake_model):
    """AC: :resubscribe path must 404 — it was a misread of the spec (GH-75)."""
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
    assert r2.status_code in (404, 405), (
        f":resubscribe should be 404 or 405 (route never existed); got {r2.status_code}"
    )
