"""GH-217: an AG-UI SSE stream that ends before its terminal frame cancels the run."""

from __future__ import annotations

import asyncio
import inspect
import json
import uuid
from typing import Any

import pytest

from agent_sdk.routes import a2a as a2a_routes
from agent_sdk.testing import FakeModelClient, reply, tool_call

from .conftest import sse_frames


class BlockingModel(FakeModelClient):
    """Records the call, then never answers until cancelled."""

    async def converse(self, **kwargs: Any):  # type: ignore[override]
        self.calls.append({})
        await asyncio.Event().wait()


def _records(app) -> list:
    return list(app.state.task_store._records.values())


async def _drive(app, token: str, path: str, body: dict, *, until: str):
    """Raw ASGI POST; returns (task, disconnect_event, chunks) once `until`
    appears in the received bytes."""
    disconnect = asyncio.Event()
    sent_body = False
    chunks: list[bytes] = []
    payload = json.dumps(body).encode()

    async def receive() -> dict:
        nonlocal sent_body
        if not sent_body:
            sent_body = True
            return {"type": "http.request", "body": payload, "more_body": False}
        await disconnect.wait()
        return {"type": "http.disconnect"}

    async def send(message: dict) -> None:
        if message["type"] == "http.response.body":
            chunks.append(message.get("body", b""))

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "headers": [
            (b"authorization", f"Bearer {token}".encode()),
            (b"content-type", b"application/json"),
        ],
        "server": ("test", 80),
        "client": ("test-client", 12345),
        "root_path": "",
    }
    task = asyncio.create_task(app(scope, receive, send))
    for _ in range(200):
        if until.encode() in b"".join(chunks):
            return task, disconnect, chunks
        await asyncio.sleep(0.02)
    task.cancel()
    pytest.fail(f"never saw {until!r}")


async def _settle(task, disconnect) -> None:
    disconnect.set()
    await asyncio.wait_for(task, timeout=5)
    await asyncio.sleep(0.05)


def _agui_body(text="hi", **extra) -> dict:
    return {
        "threadId": "t217",
        "runId": "r217",
        "messages": [{"id": "m1", "role": "user", "content": text}],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
        **extra,
    }


def _send_body() -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": "go"}],
            "messageId": uuid.uuid4().hex,
        }
    }


async def test_disconnect_after_run_started_cancels_run(client, app):
    model = BlockingModel()
    app.state.model_client = model
    _, token = app.state.auth.api_keys.mint("gh217-a")
    task, disc, _ = await _drive(app, token, "/ag-ui/run", _agui_body(), until="RUN_STARTED")
    for _ in range(100):
        if model.calls:
            break
        await asyncio.sleep(0.02)
    assert len(model.calls) == 1
    (record,) = _records(app)
    worker = record.worker
    assert worker is not None and not worker.done()

    await _settle(task, disc)

    assert worker.done()
    assert record.task.status.state.value == "canceled"
    assert len(model.calls) == 1


async def test_disconnect_after_interrupt_does_not_cancel_and_resume_works(
    client, app, fake_model
):
    fake_model.script(tool_call("publish_note", {"note": "n"}), reply("after resume"))
    _, token = app.state.auth.api_keys.mint("gh217-b")
    task, disc, chunks = await _drive(
        app, token, "/ag-ui/run", _agui_body("publish"), until="RUN_FINISHED"
    )
    await _settle(task, disc)
    frames = sse_frames(b"".join(chunks).decode())
    interrupt_id = frames[-1]["outcome"]["interrupts"][0]["id"]
    (record,) = _records(app)
    assert record.task.status.state.value != "canceled"
    assert record.interrupted

    r = await client.post(
        "/ag-ui/run",
        json=_agui_body(
            resume=[{"interrupt_id": interrupt_id, "status": "resolved", "payload": {"d": 1}}]
        ),
    )
    frames = sse_frames(r.text)
    assert frames[-1]["type"] == "RUN_FINISHED"
    assert record.task.status.state.value == "completed"


async def test_a2a_stream_disconnect_leaves_task_running(client, app):
    model = BlockingModel()
    app.state.model_client = model
    _, token = app.state.auth.api_keys.mint("gh217-c")
    task, disc, _ = await _drive(app, token, "/v1/message:stream", _send_body(), until="data:")
    for _ in range(100):
        if model.calls:
            break
        await asyncio.sleep(0.02)
    (record,) = _records(app)
    worker = record.worker
    await _settle(task, disc)
    assert worker is not None and not worker.done()
    assert record.task.status.state.value in ("submitted", "working")
    worker.cancel()


async def test_tasks_cancel_other_identity_is_not_found(client, app):
    model = BlockingModel()
    app.state.model_client = model
    _, tok_a = app.state.auth.api_keys.mint("gh217-owner")
    _, tok_b = app.state.auth.api_keys.mint("gh217-other")
    task, disc, _ = await _drive(app, tok_a, "/ag-ui/run", _agui_body(), until="RUN_STARTED")
    (record,) = _records(app)

    r = await client.post(
        f"/v1/tasks/{record.task.id}:cancel", headers={"Authorization": f"Bearer {tok_b}"}
    )
    assert (r.status_code, r.json()["error"]["code"]) == (404, -32001)
    assert record.worker is not None and not record.worker.done()
    assert record.task.status.state.value != "canceled"
    await _settle(task, disc)


async def test_tasks_cancel_owner_still_cancels(client, app):
    model = BlockingModel()
    app.state.model_client = model
    _, tok = app.state.auth.api_keys.mint("gh217-self")
    task, disc, _ = await _drive(app, tok, "/v1/message:stream", _send_body(), until="data:")
    (record,) = _records(app)
    r = await client.post(
        f"/v1/tasks/{record.task.id}:cancel", headers={"Authorization": f"Bearer {tok}"}
    )
    assert r.status_code == 200
    assert r.json()["status"]["state"] == "canceled"
    await _settle(task, disc)


def test_shared_helper_takes_a_record_not_an_id():
    params = inspect.signature(a2a_routes.cancel_task_record).parameters
    assert list(params) == ["record", "store"]
    assert "TaskRecord" in str(params["record"].annotation)


class BlockAfterFirstModel(FakeModelClient):
    """Serves the scripted first turn, then blocks until cancelled."""

    async def converse(self, **kwargs: Any):  # type: ignore[override]
        if not self.calls:
            return await super().converse(**kwargs)
        self.calls.append({})
        await asyncio.Event().wait()


async def test_disconnect_during_resumed_run_cancels_run(client, app):
    model = BlockAfterFirstModel()
    model.script(tool_call("publish_note", {"note": "n"}))
    app.state.model_client = model
    _, token = app.state.auth.api_keys.mint("gh217-resume")
    task, disc, chunks = await _drive(
        app, token, "/ag-ui/run", _agui_body("publish"), until="RUN_FINISHED"
    )
    await _settle(task, disc)
    interrupt_id = sse_frames(b"".join(chunks).decode())[-1]["outcome"]["interrupts"][0]["id"]
    (record,) = _records(app)
    assert record.interrupted

    resume = _agui_body(
        resume=[{"interrupt_id": interrupt_id, "status": "resolved", "payload": {"d": 1}}]
    )
    task2, disc2, _ = await _drive(app, token, "/ag-ui/run", resume, until="RUN_STARTED")
    for _ in range(100):
        if len(model.calls) >= 2:
            break
        await asyncio.sleep(0.02)
    worker = record.worker
    assert worker is not None and not worker.done()

    await _settle(task2, disc2)

    assert worker.done()
    assert record.task.status.state.value == "canceled"
