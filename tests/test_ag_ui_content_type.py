"""LRN-093: AG-UI /ag-ui/run must reject non-JSON Content-Type with 415.

Pass-through when Content-Type header is absent (allows bare curl);
reject only when present and not application/json.
"""

from __future__ import annotations

import pytest


def _run_body() -> dict:
    return {
        "threadId": "t1",
        "runId": "r1",
        "messages": [{"id": "m1", "role": "user", "content": "hello"}],
        "state": {},
        "tools": [],
        "context": [],
    }


@pytest.mark.asyncio
async def test_415_on_wrong_content_type(client):
    """POST with Content-Type: text/plain must be rejected with 415 (pre-parse)."""
    r = await client.post(
        "/ag-ui/run",
        content=b'{"threadId":"t1","runId":"r1","messages":[]}',
        headers={"Content-Type": "text/plain"},
    )
    assert r.status_code == 415


@pytest.mark.asyncio
async def test_no_415_when_content_type_absent(client, fake_model):
    """POST with no Content-Type header must proceed (not 415)."""
    from agent_sdk.testing import reply

    fake_model.script(reply("ok"))
    import json

    body = json.dumps(_run_body()).encode()
    # Remove the default Content-Type by not using json= kwarg and setting headers
    r = await client.post(
        "/ag-ui/run",
        content=body,
        headers={"Content-Type": ""},
    )
    # Should not be 415; the stream may end in RUN_ERROR due to validation but
    # the route itself accepted the request.
    assert r.status_code != 415
