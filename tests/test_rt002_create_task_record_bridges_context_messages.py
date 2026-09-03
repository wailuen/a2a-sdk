"""RT-002: ``_create_task_record`` must bridge the prior transcript returned
by ``TaskStore.context_messages()`` before appending the new ``user`` turn.

``context_messages()`` is a non-abstract, overridable ``TaskStore`` ABC
method (C-005, tasks/store.py) — its whole reason to exist is external
durable subclasses. Every ``run_loop`` WRITER (loop.py's five exits,
``repair_dangling_tool_use``) bridges its own exit so ``record.messages``
never ends on ``user``, but a store override — an AzureTableTaskStore-shaped
store, or any record persisted before GH-147's writer-side guards existed —
can return a transcript that already ends on ``user``. This is the one
consumption site of that data, and none of the SDK's guard set runs on the
continuation path, so it must re-assert the invariant on read rather than
trust the writers that produced ``prior``.
"""

from __future__ import annotations

import uuid
from typing import Any

from agent_sdk.testing import reply

from .conftest import wait_for_state


def user_msg(text: str, *, context_id: str | None = None) -> dict:
    msg: dict[str, Any] = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": uuid.uuid4().hex,
    }
    if context_id:
        msg["contextId"] = context_id
    return {"message": msg}


def roles_have_no_adjacent_duplicate(roles: list[str]) -> bool:
    return all(a != b for a, b in zip(roles, roles[1:]))


async def test_create_task_record_bridges_trailing_user_from_context_messages(
    client, fake_model
):
    """A TaskStore override whose ``context_messages()`` returns a
    transcript ending on ``user`` (the shape GH-147's guarded writers never
    produce, but which the public ABC contract does not forbid a subclass
    from returning) must not reproduce the two-consecutive-'user' defect on
    the continuation path."""
    ctx = uuid.uuid4().hex
    store = client.app.state.task_store
    stale_transcript = [{"role": "user", "content": [{"text": "orphaned prior turn"}]}]
    store.context_messages = lambda context_id, identity=None: stale_transcript

    fake_model.script(reply("second reply"))
    r = await client.post("/v1/message:send", json=user_msg("turn two", context_id=ctx))
    assert r.status_code == 200, r.text
    await wait_for_state(client, r.json()["id"])

    record = store.get(r.json()["id"])
    assert record is not None
    roles = [m["role"] for m in record.messages]
    assert roles_have_no_adjacent_duplicate(roles), f"adjacent same-role messages: {roles}"

    assert fake_model.calls, "converse must have been called"
    roles_sent = [m["role"] for m in fake_model.calls[0]["messages"]]
    assert roles_have_no_adjacent_duplicate(
        roles_sent
    ), f"adjacent same-role messages sent upstream: {roles_sent}"
