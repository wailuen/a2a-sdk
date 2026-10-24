"""GH-235: deeply nested JSON bodies are a parse error on every surface (not a
500), and an AG-UI resume with more than one entry is refused."""

from __future__ import annotations

import asyncio
import json
import uuid

import pytest

from agent_sdk.common import json_strict
from agent_sdk.common.json_strict import loads_strict
from agent_sdk.routes.mcp import _sse_queues

from .conftest import sse_frames

MARKER = "HOSTILE-MARKER-9f3a"


def nested(depth: int) -> bytes:
    return ("[" * depth + f'"{MARKER}"' + "]" * depth).encode()


@pytest.fixture(autouse=True)
def _interpreter_raises_recursion_error(monkeypatch):
    """Python 3.14's C scanner parses 50000-deep arrays without error; older
    interpreters raise RecursionError. Force that behaviour so the test is
    meaningful on every version."""
    real = json_strict.json

    class _Shim:
        JSONDecodeError = real.JSONDecodeError
        dumps = staticmethod(real.dumps)

        @staticmethod
        def loads(raw, **kw):
            text = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
            if text.startswith("[" * 1000):
                raise RecursionError(f"maximum recursion depth exceeded {text[-30:]}")
            return real.loads(raw, **kw)

    monkeypatch.setattr(json_strict, "json", _Shim)


JSON_HEADERS = {"content-type": "application/json"}


def test_loads_strict_maps_recursion_error():
    with pytest.raises(json.JSONDecodeError) as ei:
        loads_strict(nested(50000))
    assert MARKER not in str(ei.value)
    assert MARKER not in ei.value.msg


async def test_mcp_post_nested_is_parse_error(client):
    r = await client.post("/mcp", content=nested(50000), headers=JSON_HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["error"]["code"] == -32700
    assert MARKER not in r.text


async def test_mcp_messages_nested_is_parse_error(client, app):
    bearer = client.headers["authorization"].removeprefix("Bearer ")
    identity = app.state.auth.api_keys.verify(bearer)
    owner = f"{identity.kind}:{identity.subject}"
    session_id = uuid.uuid4().hex
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=8)
    _sse_queues(app)[session_id] = (queue, owner)
    try:
        r = await client.post(
            "/mcp/messages",
            params={"session_id": session_id},
            content=nested(50000),
            headers=JSON_HEADERS,
        )
        assert r.status_code == 202, r.text
        queued = queue.get_nowait()
        assert json.loads(queued)["error"]["code"] == -32700
        assert MARKER not in queued
    finally:
        _sse_queues(app).pop(session_id, None)


async def test_a2a_message_send_nested_is_parse_error(client):
    r = await client.post("/v1/message:send", content=nested(50000), headers=JSON_HEADERS)
    assert r.status_code != 500, r.text
    assert r.status_code == 400, r.text
    assert MARKER not in r.text


async def test_ag_ui_run_nested_is_parse_error(client):
    r = await client.post("/ag-ui/run", content=nested(50000), headers=JSON_HEADERS)
    assert r.status_code == 200, r.text
    errors = [f for f in sse_frames(r.text) if f["type"] == "RUN_ERROR"]
    assert len(errors) == 1
    assert errors[0]["message"] == "malformed RunAgentInput body"
    assert MARKER not in r.text


async def test_oauth_register_nested_is_invalid_client_metadata(client):
    body = nested(2000)
    assert len(body) < 16 * 1024
    r = await client.post("/oauth/register", content=body, headers=JSON_HEADERS)
    assert r.status_code == 400, r.text
    assert r.json() == {
        "error": "invalid_client_metadata",
        "error_description": "request body must be valid JSON",
    }
    assert MARKER not in r.text


def run_body(**extra) -> dict:
    return {
        "threadId": "t1",
        "runId": "r1",
        "messages": [{"id": "m1", "role": "user", "content": "hi"}],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
        **extra,
    }


async def test_ag_ui_resume_with_two_entries_is_refused(client):
    entry = {"interruptId": "i1", "status": "resolved", "payload": {}}
    extra = {"interruptId": "i2", "status": "resolved", "payload": {"x": MARKER}}
    r = await client.post("/ag-ui/run", json=run_body(resume=[entry, extra]))
    assert r.status_code == 200, r.text
    errors = [f for f in sse_frames(r.text) if f["type"] == "RUN_ERROR"]
    assert len(errors) == 1
    assert errors[0]["message"] == "invalid resume entry"
    assert errors[0].get("code") == "validation"
    assert MARKER not in r.text


def test_loads_strict_depth_cap_without_recursion_error():
    for depth in (65, 300, 999):
        with pytest.raises(json.JSONDecodeError) as ei:
            loads_strict(nested(depth))
        assert ei.value.msg == "nesting too deep"
    assert loads_strict(nested(64)) is not None
    with pytest.raises(json.JSONDecodeError):
        loads_strict(("{\"a\":" * 300 + "1" + "}" * 300).encode())


async def test_a2a_deep_metadata_never_breaks_task_list(client):
    body = ('{"message":{"metadata":' + "[" * 300 + "]" * 300 + "}}").encode()
    r = await client.post("/v1/message:send", content=body, headers=JSON_HEADERS)
    assert r.status_code == 400, r.text
    assert (await client.get("/v1/tasks")).status_code != 500
