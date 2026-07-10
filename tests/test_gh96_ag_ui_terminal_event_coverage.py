"""GH-96: any non-StreamTerminated exception inside stream()'s try block must
still yield exactly one RUN_ERROR terminal frame (DESIGN.md §5.3).

Before the fix, ``except StreamTerminated: pass`` was the only exception
handler around the event loop; any other exception (e.g. from mapper.map()
translating an event, or from a store call) propagated straight past the
``if not mapper.terminal_sent: yield mapper.run_error(...)`` safety-net —
which sits AFTER the try/except, not inside it — so the SSE connection died
with no terminal frame at all.
"""

from __future__ import annotations

from agent_sdk.routes import ag_ui as ag_ui_module
from agent_sdk.testing import reply

from .conftest import sse_frames


def run_body(text: str = "hello", **extra) -> dict:
    return {
        "threadId": "t1",
        "runId": "r1",
        "messages": [{"id": "m1", "role": "user", "content": text}],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
        **extra,
    }


async def test_map_exception_still_yields_single_run_error(client, fake_model, monkeypatch):
    def _boom(self, event):
        raise RuntimeError("boom from mapper.map")

    monkeypatch.setattr(ag_ui_module._RunMapper, "map", _boom)

    fake_model.script(reply("hi there"))
    r = await client.post("/ag-ui/run", json=run_body())
    assert r.status_code == 200, r.text
    assert r.headers["content-type"].startswith("text/event-stream")

    frames = sse_frames(r.text)
    types = [f["type"] for f in frames]

    assert types[:2] == ["RUN_STARTED", "STATE_SNAPSHOT"]
    terminal_types = [t for t in types if t in ("RUN_FINISHED", "RUN_ERROR")]
    assert terminal_types == ["RUN_ERROR"], types
    assert types[-1] == "RUN_ERROR"
