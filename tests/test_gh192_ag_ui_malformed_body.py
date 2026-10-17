"""GH-192: a non-JSON or non-object body gets a precise RUN_ERROR (DESIGN.md §5.3)."""

from __future__ import annotations

import pytest

from .conftest import sse_frames

MALFORMED = "malformed RunAgentInput body"


@pytest.mark.parametrize(
    "raw",
    [b"{not json", b"[1, 2]", b'"text"', b"42", b"null", b"true"],
)
async def test_malformed_body_run_error(client, raw):
    r = await client.post(
        "/ag-ui/run", content=raw, headers={"content-type": "application/json"}
    )
    assert r.status_code == 200, r.text
    frames = sse_frames(r.text)
    assert frames[0]["type"] == "RUN_STARTED"
    assert frames[0]["threadId"] and frames[0]["runId"]
    errors = [f for f in frames if f["type"] == "RUN_ERROR"]
    assert len(errors) == 1
    assert errors[0]["message"] == MALFORMED
    assert "not json" not in r.text
