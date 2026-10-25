"""RT-002: docs/protocols.md and DESIGN.md must document terminal-task
RESUME (message/send, message/stream with taskId) as 400 -32004
(UnsupportedOperation) — never -32002 (TaskNotCancelable), which A2A v0.3.0
reserves exclusively for tasks/cancel (harness/reference/a2a-protocol-0_3_0.md
"-32002 on tasks/cancel").

_resume_or_error (agent_sdk/routes/a2a.py) has returned -32004 for
message/send since it landed, and message/stream's terminal-task branch
returns -32004 too. The docs previously taught -32002 for "resume or
cancel", conflating the two. This module pins the corrected doc language
statically AND proves it live on both message/send and message/stream, so
doc and code can never drift apart silently again (LRN-118).
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path

import agent_sdk.app as _app_module

from .conftest import wait_for_state


def _repo_root() -> Path:
    return Path(_app_module.__file__).parent.parent


def _protocols_md_text() -> str:
    return (_repo_root() / "docs" / "protocols.md").read_text()


def _design_md_text() -> str:
    return (_repo_root() / "DESIGN.md").read_text()


def _send_body(text: str, task_id: str | None = None) -> dict:
    message: dict = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": uuid.uuid4().hex,
    }
    if task_id:
        message["taskId"] = task_id
    return {"message": message}


# ===========================================================================
# Static — doc text no longer claims -32002 for terminal-task resume
# ===========================================================================


def _normalize_ws(text: str) -> str:
    """Collapse markdown hand-wrapping so a clause split across lines still
    matches a single-line regex."""
    return re.sub(r"\s+", " ", text)


def test_protocols_md_scopes_32002_to_cancel_only() -> None:
    text = _normalize_ws(_protocols_md_text())
    assert "terminal-task resume or cancel" not in text, (
        "docs/protocols.md must not lump resume and cancel under one code — "
        "A2A v0.3.0 reserves -32002 for tasks/cancel only"
    )
    assert re.search(r"terminal-task cancel.*?-32002", text), (
        "docs/protocols.md must state terminal-task cancel -> -32002"
    )


def test_protocols_md_documents_terminal_resume_as_32004() -> None:
    text = _normalize_ws(_protocols_md_text())
    assert re.search(
        r"terminal-task resume.*?message:(send|stream).*?400.*?-32004", text
    ), (
        "docs/protocols.md must document terminal-task resume "
        "(message:send / message:stream with taskId) as 400 -32004"
    )


def test_design_md_32004_row_covers_terminal_resume() -> None:
    text = _design_md_text()
    match = re.search(r"\|\s*-32004\s*\|[^\n]*\|", text)
    assert match, "DESIGN.md must have a -32004 error table row"
    row = match.group(0)
    assert "message/send" in row and "message/stream" in row, (
        f"DESIGN.md's -32004 trigger column must name terminal-task "
        f"re-message on message/send and message/stream; got: {row!r}"
    )


# ===========================================================================
# Live — both surfaces the doc now describes actually emit 400 -32004
# ===========================================================================


async def test_terminal_task_resume_via_message_send_is_32004(client, fake_model):
    from agent_sdk.testing import reply

    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=_send_body("hello"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, {"completed", "failed", "canceled"})

    r2 = await client.post("/v1/message:send", json=_send_body("resume attempt", task_id))
    assert r2.status_code == 400, r2.text
    assert r2.json()["error"]["code"] == -32004


async def test_terminal_task_resume_via_message_stream_is_32004(client, fake_model):
    from agent_sdk.testing import reply

    fake_model.script(reply("done"))
    r = await client.post("/v1/message:send", json=_send_body("hello"))
    task_id = r.json()["id"]
    await wait_for_state(client, task_id, {"completed", "failed", "canceled"})

    r2 = await client.post("/v1/message:stream", json=_send_body("resume attempt", task_id))
    assert r2.status_code == 400, r2.text
    assert r2.json()["error"]["code"] == -32004
