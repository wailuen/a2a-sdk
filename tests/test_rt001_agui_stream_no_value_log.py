"""RT-001 (w047, LRN-214): the AG-UI stream catch-all never logs an
exception's message or formatted traceback.

``routes/ag_ui.py``'s event mapper calls ``payload.wire()`` and
``translate()`` inside the stream's ``try``. A content model (or custom
translator) that raises a pydantic ``ValidationError`` carries
``input_value='<tool output>'`` in its message; the catch-all must log only
the exception type and frame locations (SI-2), and still end the run with a
RUN_ERROR frame (§5.3).
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, ValidationError

from agent_sdk.routes import ag_ui
from agent_sdk.testing import reply, tool_call

from .conftest import sse_frames

MARKER = "MARKER-SECRET-7c1e"


class _Strict(BaseModel):
    n: int


def _boom(*args, **kwargs):
    try:
        _Strict(n=MARKER)  # type: ignore[arg-type]
    except ValidationError as exc:
        raise exc
    return {}


async def test_stream_catch_all_leaves_marker_out_of_logs(client, fake_model, monkeypatch, caplog):
    # The worker renders the artifact for its own bookkeeping first, so a
    # raising wire() fails there; patch the route's own translate() call so
    # the exception is raised inside the stream's try, as a custom domain
    # translator would.
    monkeypatch.setattr(ag_ui, "translate", _boom)
    caplog.set_level(logging.DEBUG)
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    r = await client.post(
        "/ag-ui/run",
        json={
            "threadId": "t-rt001",
            "runId": "r1",
            "messages": [{"id": "m1", "role": "user", "content": "kpis"}],
            "state": {},
            "tools": [],
            "context": [],
            "forwardedProps": {"a2uiClientCapabilities": {"tier": "core"}},
        },
    )
    assert r.status_code == 200, r.text
    frames = sse_frames(r.text)
    types = [f["type"] for f in frames]
    # The failure really happened inside the stream's try (not vacuous).
    assert types[-1] == "RUN_ERROR", types
    assert MARKER not in r.text

    failed = [rec for rec in caplog.records if "ag-ui stream failed" in rec.getMessage()]
    assert failed, "catch-all did not log — assertions below would be vacuous"
    rec = failed[0]
    assert rec.exc_info is None
    assert "ValidationError" in rec.getMessage()
    assert "ag_ui.py:" in rec.getMessage()  # frame locations kept for diagnosis

    assert MARKER not in caplog.text
    for record in caplog.records:
        assert MARKER not in record.getMessage()
        assert record.exc_info is None or MARKER not in str(record.exc_info[1])
