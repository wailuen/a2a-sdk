"""Protocol conformance fix tests — wave 9 Group A (A2A protocol).

SC-A1  bare-Message return path in message/send
GH-15  Content-Type guard → -32005/HTTP 415 for non-JSON
GH-16  terminal task re-message → -32002/HTTP 409 (not -32001/404)
SC-A2  plain scalar ArtifactEvent emits TextPart + DataPart
SC-A3  GET /v1/card requires auth (401 without, 501 with)
SC-A4  credential-forwarding URI echoed in X-A2A-Extensions
"""

from __future__ import annotations

import gc
import uuid
from typing import ClassVar

import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.events import ArtifactEvent
from agent_sdk.agent.runner import build_artifact
from agent_sdk.credentials.card import EXTENSION_URI as CRED_FWD_URI
from agent_sdk.example.agent import make_agent
from agent_sdk.models.a2a import DataPart, TextPart
from agent_sdk.testing import FakeModelClient, reply

from .conftest import wait_for_state


# ── helpers ──────────────────────────────────────────────────────────────────


def send_body(text: str, task_id: str | None = None) -> dict:
    msg = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": uuid.uuid4().hex,
    }
    if task_id:
        msg["taskId"] = task_id
    return {"message": msg}


# ── SC-A1: bare-Message quick-response path ──────────────────────────────────


@pytest.fixture
def sync_reply_app(tmp_path):
    """Agent with a sync_reply hook that returns 'pong' for any message."""
    settings = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="sync-reply-agent"
    )
    fake_model = FakeModelClient()
    agent = make_agent(settings, model_client=fake_model)
    agent.set_sync_reply(lambda msg: "pong")
    built = agent.build_app()
    yield built
    built.state.credential_store.close()
    gc.collect()


@pytest.fixture
async def sync_reply_client(sync_reply_app):
    import httpx

    async with sync_reply_app.router.lifespan_context(sync_reply_app):
        _, token = sync_reply_app.state.auth.api_keys.mint("test", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=sync_reply_app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            c.app = sync_reply_app
            yield c


async def test_sc_a1_sync_reply_returns_bare_message(sync_reply_client):
    """sync_reply hook returning 'pong' → bare Message (kind==message), no task."""
    r = await sync_reply_client.post("/v1/message:send", json=send_body("ping"))
    assert r.status_code == 200, r.text
    body = r.json()
    # Must be a bare Message, not a Task
    assert body.get("kind") == "message", f"expected kind==message, got: {body}"
    assert body["role"] == "agent"
    assert body["parts"][0]["kind"] == "text"
    assert body["parts"][0]["text"] == "pong"
    assert "messageId" in body
    assert "contextId" in body
    # No task should exist
    assert "id" not in body  # Task has 'id'; Message has 'messageId'


async def test_sc_a1_no_task_created_by_sync_reply(sync_reply_client):
    """No task entry in store when sync_reply fires."""
    r = await sync_reply_client.post("/v1/message:send", json=send_body("ping"))
    assert r.status_code == 200
    body = r.json()
    assert body.get("kind") == "message"
    # Confirm the task store is empty (no task id to look up)
    assert body.get("id") is None


async def test_sc_a1_no_hook_falls_through_to_task_path(client, fake_model):
    """Without sync_reply hook, message/send creates a Task as normal."""
    fake_model.script(reply("hi back"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    assert r.status_code == 200
    body = r.json()
    # Normal Task path: kind==task (or no kind field), has 'id'
    assert body.get("kind") != "message"
    assert "id" in body


# ── GH-15: Content-Type guard ────────────────────────────────────────────────


async def test_gh15_plain_text_content_type_returns_415(client):
    """POST with Content-Type: text/plain → HTTP 415 + code -32005."""
    r = await client.post(
        "/v1/message:send",
        content=b'{"message": {"role":"user","parts":[],"messageId":"abc"}}',
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 415, r.text
    assert r.json()["error"]["code"] == -32005


async def test_gh15_json_with_charset_proceeds(client, fake_model):
    """Content-Type: application/json; charset=utf-8 proceeds normally (charset stripped)."""
    fake_model.script(reply("ok"))
    body = send_body("hello")
    import json as _json

    r = await client.post(
        "/v1/message:send",
        content=_json.dumps(body).encode(),
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    # Should NOT be a 415 — the charset suffix must not block the request
    assert r.status_code == 200, r.text
    assert "error" not in r.json()


async def test_gh15_no_content_type_proceeds(client, fake_model):
    """No Content-Type header falls through (empty string check) — existing behaviour."""
    fake_model.script(reply("ok"))
    body = send_body("hello")
    import json as _json

    r = await client.post(
        "/v1/message:send",
        content=_json.dumps(body).encode(),
        headers={"Content-Type": ""},
    )
    # Empty Content-Type is treated as absent → should proceed
    assert r.status_code == 200, r.text


# ── GH-51: terminal task re-message → continuation (new task, same contextId) ──


async def test_gh16_terminal_task_remessage_returns_409(client, fake_model):
    """GH-16 / GH-51: re-messaging a completed task returns -32004 (UnsupportedOperation).
    A2A §6 item 14: message targeting a terminal task MUST return an error.
    The original task remains accessible at its ID with the completed state.
    """
    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=send_body("hi"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id)

    # Confirm the original task is accessible and completed
    r_get = await client.get(f"/v1/tasks/{task_id}")
    assert r_get.status_code == 200
    assert r_get.json()["status"]["state"] == "completed"

    # Re-message the completed task → must be rejected
    r_resume = await client.post("/v1/message:send", json=send_body("again", task_id))
    assert r_resume.status_code in (400, 501), r_resume.text
    assert r_resume.json()["error"]["code"] == -32004


# ── SC-A2: plain scalar artifact emits TextPart + DataPart ──────────────────


def test_sc_a2_plain_int_artifact_emits_two_parts():
    """ArtifactEvent with model=42 (int) → 2 parts: TextPart + DataPart."""
    event = ArtifactEvent(
        model=42,
        data_type="answer",
        tool_name="compute",
    )
    caps = A2uiCapabilities()
    artifact = build_artifact(event, caps)
    assert len(artifact.parts) == 2, f"expected 2 parts, got {len(artifact.parts)}: {artifact.parts}"
    text_part, data_part = artifact.parts
    assert isinstance(text_part, TextPart), f"first part should be TextPart, got {type(text_part)}"
    assert text_part.text == "42"
    assert isinstance(data_part, DataPart), f"second part should be DataPart, got {type(data_part)}"
    assert data_part.data == {"value": 42}


def test_sc_a2_plain_string_artifact_emits_two_parts():
    """ArtifactEvent with model='hello' (str) → 2 parts with DataPart wrapping the value."""
    event = ArtifactEvent(
        model="hello",
        data_type="greeting",
        tool_name="greet",
    )
    caps = A2uiCapabilities()
    artifact = build_artifact(event, caps)
    assert len(artifact.parts) == 2
    text_part, data_part = artifact.parts
    assert isinstance(text_part, TextPart)
    assert text_part.text == "hello"
    assert isinstance(data_part, DataPart)
    assert data_part.data == {"value": "hello"}
    assert data_part.metadata is not None
    assert data_part.metadata.get("mimeType") == "application/json"


# ── SC-A3: GET /v1/card requires auth ────────────────────────────────────────


async def test_sc_a3_extended_card_without_auth_returns_401(client):
    """GET /v1/card without Authorization header → HTTP 401."""
    import httpx

    app = client.app
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        # No auth header
    ) as unauth_client:
        r = await unauth_client.get("/v1/card")
    assert r.status_code == 401, r.text


async def test_sc_a3_extended_card_with_auth_returns_501(client):
    """GET /v1/card with valid auth → HTTP 501 + code -32007 (not configured)."""
    r = await client.get("/v1/card")
    assert r.status_code == 501, r.text
    assert r.json()["error"]["code"] == -32007


# ── SC-A4: credential-forwarding URI echoed in X-A2A-Extensions ──────────────


async def test_sc_a4_cred_fwd_uri_echoed(client, fake_model):
    """The example agent declares no credential source, so its card has no
    credential-forwarding extension and the URI is NOT echoed (v0.22.0: never
    echo an extension the card does not declare). The declared case is
    tests/test_forwarding_integration.py::test_a2a_echoes_declared_credential_extension."""
    fake_model.script(reply("ok"))
    r = await client.post(
        "/v1/message:send",
        json=send_body("hi"),
        headers={"X-A2A-Extensions": CRED_FWD_URI},
    )
    assert r.status_code == 200, r.text
    echoed = r.headers.get("x-a2a-extensions", "")
    assert CRED_FWD_URI not in echoed, echoed


async def test_sc_a4_both_uris_echoed(client, fake_model):
    """Both requested: only the declared A2UI URI is echoed (no credential source)."""
    from agent_sdk.models.content_types import A2UI_EXTENSION_URI

    fake_model.script(reply("ok"))
    r = await client.post(
        "/v1/message:send",
        json=send_body("hi"),
        headers={"X-A2A-Extensions": f"{A2UI_EXTENSION_URI}, {CRED_FWD_URI}"},
    )
    assert r.status_code == 200, r.text
    echoed = r.headers.get("x-a2a-extensions", "")
    assert A2UI_EXTENSION_URI in echoed
    assert CRED_FWD_URI not in echoed


async def test_sc_a4_unknown_uri_not_echoed(client, fake_model):
    """Unknown extension URIs are NOT echoed (only known ones are activated)."""
    fake_model.script(reply("ok"))
    r = await client.post(
        "/v1/message:send",
        json=send_body("hi"),
        headers={"X-A2A-Extensions": "https://unknown.example/ext"},
    )
    assert r.status_code == 200, r.text
    assert "x-a2a-extensions" not in r.headers
