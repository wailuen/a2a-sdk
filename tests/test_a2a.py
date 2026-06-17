"""A2A v0.3.0 surface conformance (DESIGN.md §5.1)."""

from __future__ import annotations

import uuid

import pytest

from agent_sdk.testing import reply, tool_call

from .conftest import sse_frames, wait_for_state


def send_body(text: str, task_id: str | None = None) -> dict:
    msg = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": uuid.uuid4().hex,
    }
    if task_id:
        msg["taskId"] = task_id
    return {"message": msg}


async def test_send_completes_with_artifact(client, fake_model):
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    fake_model.script(
        tool_call("demo_kpis", {"title": "Q2"}), reply("KPIs attached.")
    )
    r = await client.post(
        "/v1/message:send",
        json=send_body("kpis please"),
        headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
    )
    assert r.status_code == 200
    task = r.json()
    assert task["status"]["state"] in ("submitted", "working")
    assert task["contextId"]

    done = await wait_for_state(client, task["id"])
    assert done["status"]["state"] == "completed"
    art = done["artifacts"][0]
    kinds = [p["kind"] for p in art["parts"]]
    assert kinds == ["text", "data"]
    assert art["metadata"]["data_type"] == "kpi_card"
    # A2UI DataPart.data is a bare message array (conformance: not wrapped)
    msgs = art["parts"][1]["data"]
    assert art["parts"][1]["metadata"]["mimeType"] == "application/a2ui+json"
    verbs = [next(k for k in m if k != "version") for m in msgs]
    assert verbs == ["createSurface", "updateComponents", "updateDataModel", "deleteSurface"]


async def test_missing_message_id_is_invalid_params(client):
    r = await client.post(
        "/v1/message:send",
        json={"message": {"role": "user", "parts": [{"kind": "text", "text": "x"}]}},
    )
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32602


async def test_configuration_rejections(client):
    base = send_body("x")
    r = await client.post(
        "/v1/message:send",
        json={**base, "configuration": {"pushNotificationConfig": {"url": "https://e.com"}}},
    )
    assert r.json()["error"]["code"] == -32003
    r = await client.post(
        "/v1/message:send", json={**base, "configuration": {"blocking": True}}
    )
    assert r.json()["error"]["code"] == -32004
    r = await client.post(
        "/v1/message:send",
        json={**base, "configuration": {"acceptedOutputModes": ["image/png"]}},
    )
    assert r.json()["error"]["code"] == -32005


async def test_error_table(client, fake_model):
    r = await client.get("/v1/tasks/unknown")
    assert (r.status_code, r.json()["error"]["code"]) == (404, -32001)
    r = await client.get("/v1/tasks")
    assert r.status_code == 200
    assert r.json()["tasks"] == []
    assert r.json()["totalSize"] == 0
    r = await client.get("/v1/card")
    # extended card not configured = capability absent → 501 (spec table §2)
    assert (r.status_code, r.json()["error"]["code"]) == (501, -32007)

    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    task = await wait_for_state(client, r.json()["id"])
    r = await client.post(f"/v1/tasks/{task['id']}:cancel")
    assert (r.status_code, r.json()["error"]["code"]) == (409, -32002)


async def test_identity_binding_404_not_leak(client, fake_model):
    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    _, other = client.app.state.auth.api_keys.mint("other", admin=False)
    r = await client.get(
        f"/v1/tasks/{task_id}", headers={"Authorization": f"Bearer {other}"}
    )
    assert (r.status_code, r.json()["error"]["code"]) == (404, -32001)


async def test_stream_first_frame_full_task_then_final(client, fake_model):
    fake_model.script(reply("streamed"))
    async with client.stream(
        "POST", "/v1/message:stream", json=send_body("hi")
    ) as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        body = (await r.aread()).decode()
    frames = sse_frames(body)
    assert frames[0]["status"]["state"] in ("submitted", "working")  # full Task
    assert "id" in frames[0] and "contextId" in frames[0]
    assert frames[-1]["final"] is True
    assert frames[-1]["status"]["state"] == "completed"


async def test_interrupt_resume_via_message_send(client, fake_model):
    fake_model.script(
        tool_call("publish_note", {"note": "hello"}),
        reply("published!"),
    )
    r = await client.post("/v1/message:send", json=send_body("publish hello"))
    task_id = r.json()["id"]
    task = await wait_for_state(client, task_id, states=("input-required",))
    meta = task["status"]["message"]["metadata"]
    assert meta["interruptId"] and meta["responseSchema"]

    r = await client.post("/v1/message:send", json=send_body("approved", task_id))
    assert r.status_code == 200, r.text
    done = await wait_for_state(client, task_id)
    assert done["status"]["state"] == "completed"

    # GH-16: resume of a terminal task → UnsupportedOperation (-32004, HTTP 501)
    # so clients can distinguish "task not found" from "task exists but non-resumable".
    # -32004 is the correct A2A §2 code for message/send on a terminal task;
    # -32002 (TaskNotCancelable) is reserved for tasks/cancel only.
    r = await client.post("/v1/message:send", json=send_body("again", task_id))
    assert (r.status_code, r.json()["error"]["code"]) == (501, -32004)


async def test_cancel_running_task(client, fake_model):
    fake_model.script(
        tool_call("publish_note", {"note": "x"})  # parks in input-required
    )
    r = await client.post("/v1/message:send", json=send_body("publish"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, states=("input-required",))
    r = await client.post(f"/v1/tasks/{task_id}:cancel")
    assert r.status_code == 200
    assert r.json()["status"]["state"] == "canceled"


async def test_history_length_truncation(client, fake_model):
    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)
    r = await client.get(f"/v1/tasks/{task_id}?historyLength=1")
    assert len(r.json()["history"]) == 1
    r = await client.get(f"/v1/tasks/{task_id}?historyLength=0")
    assert r.json()["history"] == []


async def test_extensions_header_echo(client, fake_model):
    fake_model.script(reply("done"))
    uri = "https://a2ui.org/a2a-extension/a2ui/v0.9.1"
    r = await client.post(
        "/v1/message:send",
        json=send_body("hi"),
        headers={"X-A2A-Extensions": f"{uri}, https://other.example/ext"},
    )
    assert r.headers.get("x-a2a-extensions") == uri


async def test_tasks_list(client, fake_model):
    r = await client.get("/v1/tasks")
    assert r.status_code == 200
    body0 = r.json()
    assert body0["tasks"] == []
    assert body0["totalSize"] == 0
    assert body0["pageSize"] == 50
    assert body0["nextPageToken"] == ""

    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    r = await client.get("/v1/tasks")
    assert r.status_code == 200
    body = r.json()
    assert body["totalSize"] == 1
    assert len(body["tasks"]) == 1
    assert body["tasks"][0]["id"] == task_id
    assert body["nextPageToken"] == ""


async def test_tasks_list_isolation(client, fake_model):
    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    _, other_token = client.app.state.auth.api_keys.mint("other-user", admin=False)
    other_headers = {"Authorization": f"Bearer {other_token}"}
    r = await client.get("/v1/tasks", headers=other_headers)
    assert r.status_code == 200
    assert r.json()["totalSize"] == 0
    assert r.json()["tasks"] == []
