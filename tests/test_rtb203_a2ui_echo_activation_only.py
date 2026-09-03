"""RT-B-203: on the read-only routes (``tasks/list``, ``tasks/get``),
``X-A2A-Extensions`` must mean "activated for THIS response", never merely
"the caller's own request header asked for it".

Before this fix, ``_echo_extensions`` ran unconditionally on both routes —
neither of which runs any extension logic (no ``_capabilities()`` call,
nothing forwarded) — so a client opting into ``A2UI_EXTENSION_URI`` on a
``tasks/get``/``tasks/list`` call against a task that was NOT created with
A2UI active still got the header echoed back, alongside a Task whose
artifacts carry no A2UI parts: a false activation signal on the wire. The
credential-forwarding extension must never be echoed on either route at
all — nothing is forwarded on a read.
"""

from __future__ import annotations

import uuid

from agent_sdk.credentials.card import EXTENSION_URI as CREDENTIAL_FORWARDING_EXTENSION_URI
from agent_sdk.models.content_types import A2UI_EXTENSION_URI
from agent_sdk.testing import reply, tool_call

from .conftest import wait_for_state


def send_body(text: str) -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


async def _create_plain_task(client, fake_model) -> str:
    """Task with NO A2UI activation at creation — a plain text reply."""
    fake_model.script(reply("plain reply, no tools"))
    r = await client.post("/v1/message:send", json=send_body("hello"))
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    done = await wait_for_state(client, task_id)
    assert done["status"]["state"] == "completed"
    return task_id


async def _create_a2ui_task(client, fake_model) -> str:
    """Task created WITH A2UI active — its artifact carries a real A2UI part."""
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    r = await client.post(
        "/v1/message:send",
        json=send_body("kpis"),
        headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
    )
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    done = await wait_for_state(client, task_id)
    assert done["status"]["state"] == "completed"
    mime_types = [
        p.get("metadata", {}).get("mimeType")
        for art in done["artifacts"]
        for p in art["parts"]
        if p.get("kind") == "data"
    ]
    assert "application/a2ui+json" in mime_types, (
        f"fixture task does not actually carry an A2UI part: {mime_types}"
    )
    return task_id


# ── tasks/get ────────────────────────────────────────────────────────────


async def test_tasks_get_no_echo_when_task_carries_no_a2ui_part(client, fake_model):
    task_id = await _create_plain_task(client, fake_model)
    r = await client.get(
        f"/v1/tasks/{task_id}", headers={"X-A2A-Extensions": A2UI_EXTENSION_URI}
    )
    assert r.status_code == 200, r.text
    assert "x-a2a-extensions" not in {k.lower() for k in r.headers}, dict(r.headers)


async def test_tasks_get_echoes_when_task_actually_carries_a2ui_part(client, fake_model):
    task_id = await _create_a2ui_task(client, fake_model)
    r = await client.get(
        f"/v1/tasks/{task_id}", headers={"X-A2A-Extensions": A2UI_EXTENSION_URI}
    )
    assert r.status_code == 200, r.text
    assert r.headers.get("x-a2a-extensions") == A2UI_EXTENSION_URI, dict(r.headers)


async def test_tasks_get_never_echoes_credential_forwarding(client, fake_model):
    task_id = await _create_a2ui_task(client, fake_model)
    r = await client.get(
        f"/v1/tasks/{task_id}",
        headers={
            "X-A2A-Extensions": f"{A2UI_EXTENSION_URI}, {CREDENTIAL_FORWARDING_EXTENSION_URI}"
        },
    )
    assert r.status_code == 200, r.text
    echoed = r.headers.get("x-a2a-extensions", "")
    assert CREDENTIAL_FORWARDING_EXTENSION_URI not in echoed, echoed


async def test_tasks_get_no_echo_without_request_header(client, fake_model):
    task_id = await _create_a2ui_task(client, fake_model)
    r = await client.get(f"/v1/tasks/{task_id}")
    assert r.status_code == 200, r.text
    assert "x-a2a-extensions" not in {k.lower() for k in r.headers}, dict(r.headers)


# ── tasks/list ───────────────────────────────────────────────────────────


async def test_tasks_list_no_echo_when_no_returned_task_carries_a2ui(client, fake_model):
    await _create_plain_task(client, fake_model)
    r = await client.get("/v1/tasks", headers={"X-A2A-Extensions": A2UI_EXTENSION_URI})
    assert r.status_code == 200, r.text
    assert "x-a2a-extensions" not in {k.lower() for k in r.headers}, dict(r.headers)


async def test_tasks_list_echoes_when_a_returned_task_carries_a2ui(client, fake_model):
    await _create_plain_task(client, fake_model)
    await _create_a2ui_task(client, fake_model)
    r = await client.get("/v1/tasks", headers={"X-A2A-Extensions": A2UI_EXTENSION_URI})
    assert r.status_code == 200, r.text
    assert r.headers.get("x-a2a-extensions") == A2UI_EXTENSION_URI, dict(r.headers)


async def test_tasks_list_never_echoes_credential_forwarding(client, fake_model):
    await _create_a2ui_task(client, fake_model)
    r = await client.get(
        "/v1/tasks",
        headers={
            "X-A2A-Extensions": f"{A2UI_EXTENSION_URI}, {CREDENTIAL_FORWARDING_EXTENSION_URI}"
        },
    )
    assert r.status_code == 200, r.text
    echoed = r.headers.get("x-a2a-extensions", "")
    assert CREDENTIAL_FORWARDING_EXTENSION_URI not in echoed, echoed
