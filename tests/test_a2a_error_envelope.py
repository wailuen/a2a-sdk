"""A2A HTTP error envelope conformance tests (A1 + A2 + A4).

Covers:
  A1 — All /v1/ HTTP errors return {"error": {code, message}} (no "detail" key).
  A2 — task_id with ':' returns -32004 (not -32001 task-not-found).
  A4 — MCP Origin validation rejects foreign origins; absent Origin passes.
"""

from __future__ import annotations

import uuid

import httpx
import pytest

from .conftest import wait_for_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _send_body(text: str) -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


# ===========================================================================
# A1 — /v1/ error envelope
# ===========================================================================


async def test_wrong_method_405_a2a_envelope(client):
    """GET /v1/message:send (wrong method) must return 405 with A2A envelope
    and -32004 (UnsupportedOperation), never FastAPI's {"detail": ...}."""
    r = await client.get("/v1/message:send")
    assert r.status_code == 405
    body = r.json()
    assert "detail" not in body, f"'detail' key must not appear in A2A envelope; got {body}"
    assert body["error"]["code"] == -32004


async def test_no_auth_401_a2a_envelope(client):
    """POST /v1/message:send with no Authorization must return 401 with A2A
    envelope and code -32000, never FastAPI's {"detail": ...}."""
    r = await client.post(
        "/v1/message:send",
        json=_send_body("hello"),
        headers={"Authorization": ""},  # strip the pre-set admin bearer
    )
    assert r.status_code == 401
    body = r.json()
    assert "detail" not in body, f"'detail' key must not appear in A2A envelope; got {body}"
    assert body["error"]["code"] == -32000


async def test_unknown_v1_route_404_a2a_envelope(client):
    """GET /v1/bogus (unknown route) must return 404 with A2A envelope,
    never FastAPI's {"detail": "Not Found"}."""
    r = await client.get("/v1/bogus")
    assert r.status_code == 404
    body = r.json()
    assert "detail" not in body, f"'detail' key must not appear in A2A envelope; got {body}"
    assert "error" in body
    assert isinstance(body["error"]["code"], int)
    assert isinstance(body["error"]["message"], str)


async def test_invalid_query_param_400_no_value_echo(client):
    """GET /v1/tasks/x?historyLength=notanint must return 400 with code -32602
    and must NOT echo the submitted value 'notanint' in the response body
    (SI-2: secrets hygiene)."""
    r = await client.get("/v1/tasks/x?historyLength=notanint")
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == -32602
    # The submitted value must never appear in the response.
    raw = r.text
    assert "notanint" not in raw, (
        f"Submitted value 'notanint' echoed in response body (SI-2 violation): {raw!r}"
    )
    assert "detail" not in body, f"'detail' key must not appear in A2A envelope; got {body}"


# ===========================================================================
# A2 — task_id colon guard
# ===========================================================================


async def test_task_id_with_colon_returns_unsupported_operation(client):
    """GET /v1/tasks/abc:cancel must return -32004 (UnsupportedOperation),
    not -32001 (TaskNotFound) — the colon signals a sub-resource action on
    the wrong HTTP method, not a missing task."""
    r = await client.get("/v1/tasks/abc:cancel")
    # FastAPI may return 404 or 200 depending on route matching; what matters
    # is that the A2A error code is -32004, not -32001 (task not found).
    body = r.json()
    assert "error" in body, f"Expected A2A error envelope; got {body}"
    assert body["error"]["code"] == -32004, (
        f"Expected -32004 (UnsupportedOperation) for task_id with colon; "
        f"got {body['error']['code']}"
    )


# ===========================================================================
# A3 — terminal-task message/send error code (A2A-F1)
# ===========================================================================


async def test_terminal_task_send_returns_unsupported_operation(client):
    """message/send to a completed task must return -32004 (UnsupportedOperation),
    NOT -32002 (TaskNotCancelable). -32002 is reserved for tasks/cancel only
    (A2A v0.3.0 §2 error code table)."""
    # Create a new task and let it run to completion.
    r = await client.post("/v1/message:send", json=_send_body("hello"))
    assert r.status_code == 200
    task_id = r.json()["id"]

    # Wait for the task to reach a terminal state.
    await wait_for_state(client, task_id, {"completed", "failed", "canceled"})

    # Now attempt to send a new message to the completed task.
    resume_body = {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": "resume attempt"}],
            "messageId": uuid.uuid4().hex,
            "taskId": task_id,
        }
    }
    r2 = await client.post("/v1/message:send", json=resume_body)
    body = r2.json()
    assert "error" in body, f"Expected A2A error envelope; got {body}"
    assert body["error"]["code"] == -32004, (
        f"Expected -32004 (UnsupportedOperation) for message/send to terminal task; "
        f"got {body['error']['code']}"
    )


# ===========================================================================
# A4 — MCP Origin validation
# ===========================================================================


async def test_mcp_post_rejects_foreign_origin(client):
    """POST /mcp with a foreign Origin header must return 403.

    MCP spec §10/§12 requires servers to validate Origin to prevent
    DNS-rebinding attacks. Any origin not in cors_origins is foreign."""
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "evil", "version": "0"},
            },
        },
        headers={"Origin": "https://evil.example.com"},
    )
    assert r.status_code == 403


async def test_mcp_post_allows_no_origin(client):
    """POST /mcp without an Origin header must NOT be rejected (non-browser
    tools — curl, SDK clients — never send Origin)."""
    r = await client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "sdk-client", "version": "1"},
            },
        },
        # No Origin header — simulates a non-browser client.
    )
    assert r.status_code != 403, (
        f"A request without an Origin header must not be rejected; got {r.status_code}"
    )
