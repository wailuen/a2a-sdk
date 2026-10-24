"""GH-248: A2A route hardening (generic -32603, MIME matching, historyLength,
role check, -32004 status, pageToken shape, GET :subscribe, bare wire).

Ruling: https://github.com/wailuen/a2a-sdk/issues/248#issuecomment-6381440791
"""

from __future__ import annotations

import asyncio
import uuid

import httpx
import pytest

from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.models.a2a import TaskState, TaskStatus
from agent_sdk.testing import reply

from .conftest import sse_frames, wait_for_state

MARKER = "SECRETMARKER9f3a"


def _body(text: str = "hi", **extra) -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        },
        **extra,
    }


# ── item 1: generic handler ──


async def test_unhandled_exception_returns_fixed_32603(app, monkeypatch, caplog) -> None:
    def boom(*a, **k):
        raise RuntimeError(MARKER)

    monkeypatch.setattr(app.state.task_store, "list_tasks_for_identity", boom)
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("t", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            with caplog.at_level("DEBUG"):
                r = await c.get("/v1/tasks")
    assert r.status_code == 500
    assert r.headers["content-type"].startswith("application/json")
    assert r.json() == {"error": {"code": -32603, "message": "internal error"}}
    assert MARKER not in r.text
    for rec in caplog.records:
        assert MARKER not in rec.getMessage()
        assert not rec.exc_info
    assert any("RuntimeError" in rec.getMessage() for rec in caplog.records)


# ── items 2, 3: MIME matching ──


@pytest.mark.parametrize("mode", ["*/*", "text/*", "Text/Plain", "Application/JSON", "text/plain; charset=utf-8", "text"])
async def test_accepted_output_modes_match(client, fake_model, mode) -> None:
    fake_model.script(reply("ok"))
    r = await client.post(
        "/v1/message:send", json=_body(configuration={"acceptedOutputModes": [mode]})
    )
    assert r.status_code == 200, r.text


@pytest.mark.parametrize("mode", ["image/png", "image/*", "textual/plain"])
async def test_accepted_output_modes_reject(client, mode) -> None:
    r = await client.post(
        "/v1/message:send", json=_body(configuration={"acceptedOutputModes": [mode]})
    )
    assert r.status_code == 415
    assert r.json()["error"]["code"] == -32005


@pytest.mark.parametrize("ct", ["Application/JSON", "APPLICATION/json; charset=utf-8"])
async def test_content_type_case_insensitive(client, fake_model, ct) -> None:
    import json

    fake_model.script(reply("ok"))
    r = await client.post(
        "/v1/message:send", content=json.dumps(_body()), headers={"Content-Type": ct}
    )
    assert r.status_code == 200, r.text


async def test_content_type_other_still_415(client) -> None:
    r = await client.post("/v1/message:send", content="x", headers={"Content-Type": "text/plain"})
    assert r.status_code == 415


# ── item 4: historyLength on resume and stream snapshot ──


async def test_resume_honours_history_length_zero(client, app) -> None:
    store = app.state.task_store
    r = await client.post("/v1/message:send", json=_body("seed"))
    seed = await wait_for_state(client, r.json()["id"])
    record = store.get(seed["id"], _identity_of(app, client))
    assert record is not None
    record.task.status = TaskStatus(state=TaskState.INPUT_REQUIRED)
    record.interrupted = True
    record.resume_future = asyncio.get_running_loop().create_future()
    body = _body("answer")
    body["message"]["taskId"] = seed["id"]
    body["configuration"] = {"historyLength": 0}
    r = await client.post("/v1/message:send", json=body)
    assert r.status_code == 200, r.text
    assert not r.json().get("history")


def _identity_of(app, client) -> Identity:
    token = client.headers["Authorization"].split(" ", 1)[1]
    ident = app.state.auth.api_keys.verify(token)
    assert ident is not None
    return ident


async def test_stream_first_snapshot_honours_history_length_zero(client, fake_model) -> None:
    fake_model.script(reply("ok"))
    r = await client.post(
        "/v1/message:stream", json=_body(configuration={"historyLength": 0})
    )
    assert r.status_code == 200
    first = sse_frames(r.text)[0]
    assert not first.get("history")


async def test_stream_first_snapshot_default_has_history(client, fake_model) -> None:
    fake_model.script(reply("ok"))
    r = await client.post("/v1/message:stream", json=_body())
    assert sse_frames(r.text)[0].get("history")


# ── item 5: role ──


async def test_non_user_role_rejected(client) -> None:
    body = _body()
    body["message"]["role"] = "agent"
    for path in ("/v1/message:send", "/v1/message:stream"):
        r = await client.post(path, json=body)
        assert r.status_code == 400
        assert r.json() == {"error": {"code": -32602, "message": "message.role must be user"}}


# ── item 6: -32004 status ──


async def test_unsupported_operation_status_pinned(client) -> None:
    # Dispatch-level wrong verb is transport-level: 405 + -32004 (documented).
    r = await client.get("/v1/message:send")
    assert (r.status_code, r.json()["error"]["code"]) == (405, -32004)
    # Capability-level -32004 uses the models/errors.py status: 501.
    r = await client.get("/v1/tasks/abc:cancel")
    assert (r.status_code, r.json()["error"]["code"]) == (501, -32004)


# ── item 7: pageToken ──


@pytest.mark.parametrize("token", ["zzzz", "a" * 33, "A" * 32, MARKER, "../x"])
async def test_bad_page_token_400(client, token) -> None:
    r = await client.get("/v1/tasks", params={"pageToken": token})
    assert r.status_code == 400
    assert r.json() == {"error": {"code": -32602, "message": "invalid pageToken"}}
    assert token not in r.text


async def test_empty_page_token_first_page_and_paging(client, fake_model) -> None:
    for _ in range(3):
        fake_model.script(reply("ok"))
        r = await client.post("/v1/message:send", json=_body())
        await wait_for_state(client, r.json()["id"])
    r = await client.get("/v1/tasks", params={"pageToken": "", "pageSize": 2})
    assert r.status_code == 200
    p1 = r.json()
    assert len(p1["tasks"]) == 2 and p1["nextPageToken"]
    r = await client.get("/v1/tasks", params={"pageToken": p1["nextPageToken"], "pageSize": 2})
    assert r.status_code == 200
    p2 = r.json()
    assert len(p2["tasks"]) == 1 and p2["nextPageToken"] == ""


# ── item 8: GET :subscribe ──


async def test_subscribe_get_and_post(client, fake_model) -> None:
    fake_model.script(reply("ok"))
    r = await client.post("/v1/message:send", json=_body())
    tid = r.json()["id"]
    await wait_for_state(client, tid)
    for verb in ("GET", "POST"):
        r = await client.request(verb, f"/v1/tasks/{tid}:subscribe")
        assert r.status_code == 200, (verb, r.text)
        assert r.headers["content-type"].startswith("text/event-stream")
        frames = sse_frames(r.text)
        assert frames[0]["id"] == tid
        assert frames[-1]["final"] is True


async def test_subscribe_get_unknown_task_404(client) -> None:
    for verb in ("GET", "POST"):
        r = await client.request(verb, "/v1/tasks/nope:subscribe")
        assert r.status_code == 404
        assert r.json()["error"]["code"] == -32001


async def test_subscribe_without_credentials_401(client) -> None:
    for verb in ("GET", "POST"):
        r = await client.request(
            verb, "/v1/tasks/abc:subscribe", headers={"Authorization": ""}
        )
        assert r.status_code == 401
        assert "resource_metadata" in r.headers["www-authenticate"]


async def test_subscribe_get_bad_origin_403(client) -> None:
    r = await client.get("/v1/tasks/abc:subscribe", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


async def test_subscribe_get_shares_admission_cap(client, app, monkeypatch) -> None:
    from agent_sdk.routes import a2a as a2a_module

    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_IDENTITY", 1)
    ident = _identity_of(app, client)
    t1 = app.state.task_store.create(new_task(), ident).task.id
    t2 = app.state.task_store.create(new_task(), ident).task.id
    first = asyncio.create_task(client.get(f"/v1/tasks/{t1}:subscribe"))
    try:
        await asyncio.sleep(0.3)
        assert not first.done()
        r = await client.get(f"/v1/tasks/{t2}:subscribe")
        assert r.status_code == 429
    finally:
        first.cancel()
        try:
            await first
        except BaseException:
            pass


# ── item 9: bare wire documented ──


def test_bare_wire_documented() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    for rel in ("DESIGN.md", "docs/protocols.md"):
        text = (root / rel).read_text()
        assert "SendMessageResponse" in text and "StreamResponse" in text, rel
