"""GH-45: malformed JSON body returns -32700 (Parse Error), not -32602."""

from __future__ import annotations

import uuid


def send_body(text: str) -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


async def test_malformed_json_returns_parse_error_send(client):
    """-32700 for syntactically invalid JSON on /v1/message:send."""
    r = await client.post(
        "/v1/message:send",
        content=b"{not valid json",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == -32700, (
        f"expected -32700 Parse Error, got {body['error']['code']}"
    )


async def test_malformed_json_returns_parse_error_stream(client):
    """-32700 for syntactically invalid JSON on /v1/message:stream."""
    r = await client.post(
        "/v1/message:stream",
        content=b"[[[broken",
        headers={"Content-Type": "application/json"},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == -32700, (
        f"expected -32700 Parse Error, got {body['error']['code']}"
    )


async def test_valid_json_invalid_schema_returns_invalid_params(client):
    """Valid JSON with wrong schema → -32602 (not -32700)."""
    r = await client.post(
        "/v1/message:send",
        json={"unexpected": "shape"},
    )
    assert r.status_code == 400
    body = r.json()
    assert body["error"]["code"] == -32602, (
        f"expected -32602 Invalid Params, got {body['error']['code']}"
    )
