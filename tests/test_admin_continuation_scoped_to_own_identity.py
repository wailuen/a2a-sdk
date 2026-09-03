"""Regression test for RT-004: an admin `api_key` identity starting a fresh
``message/send``/``:stream`` (no ``taskId``) on ANOTHER identity's
``contextId`` must NOT inherit that identity's prior transcript into the
new task's ``record.messages``.

A wave's own redteam previously ratified the opposite as "the SDK's
documented position" (DESIGN.md §5.1, ``TaskStore.context_messages()``'s
docstring) and pinned it with a test asserting the leak — self-signoff on
new cross-identity data-exposure policy, never shipped. This test replaces
that one: ``TaskStore.context_messages()`` (``agent_sdk/tasks/store.py``,
``agent_sdk/tasks/memory.py``) no longer special-cases an admin `api_key`
identity at all — it is scoped to the calling identity exactly like
``context_reusable_messages()`` already was. There is still no ownership
check on a bare ``contextId`` (only on an existing ``taskId``, DESIGN.md
§5.1's binding), but that no longer matters: a mismatched identity now
simply sees no prior transcript, admin or not. Genuine operator inspection
of another identity's task remains available, safely, as a read: ``GET
/v1/tasks/{id}`` (``InMemoryTaskStore.get()``'s admin override), which
never seeds a new task's model-facing context.
"""

from __future__ import annotations

import uuid
from typing import Any

from agent_sdk.testing import reply

from .conftest import wait_for_state

_SECRET = "SECRET-BALANCE-90210"


def _a2a_msg(text: str, *, context_id: str | None = None) -> dict:
    msg: dict[str, Any] = {
        "role": "user",
        "parts": [{"kind": "text", "text": text}],
        "messageId": uuid.uuid4().hex,
    }
    if context_id:
        msg["contextId"] = context_id
    return {"message": msg}


async def test_admin_continuation_does_not_inherit_cross_identity_transcript(client, fake_model):
    # ``client`` is pre-authenticated as an admin api_key identity
    # (conftest.py); mint a second, non-admin identity for the "victim".
    _, victim_token = client.app.state.auth.api_keys.mint("victim", admin=False)

    fake_model.script(reply(f"noted: {_SECRET}"))
    r1 = await client.post(
        "/v1/message:send",
        json=_a2a_msg(f"my account balance is {_SECRET}"),
        headers={"Authorization": f"Bearer {victim_token}"},
    )
    assert r1.status_code == 200, r1.text
    completed = await wait_for_state(client, r1.json()["id"])
    assert completed["status"]["state"] == "completed", completed
    victim_ctx = completed["contextId"]

    # Admin identity starts a NEW task (no taskId) on the victim's contextId
    # — never resuming the victim's own task, and never authenticated as
    # the victim.
    fake_model.calls.clear()
    fake_model.script(reply("admin's own turn"))
    r2 = await client.post(
        "/v1/message:send",
        json=_a2a_msg("continuing the thread", context_id=victim_ctx),
    )
    assert r2.status_code == 200, r2.text
    completed2 = await wait_for_state(client, r2.json()["id"])
    assert completed2["status"]["state"] == "completed", completed2

    assert fake_model.calls, "converse must have been called for the admin's continuation turn"
    sent_messages = fake_model.calls[0]["messages"]
    assert not any(_SECRET in str(m) for m in sent_messages), (
        "an admin api_key identity starting a NEW task on another identity's "
        "contextId must never inherit that identity's prior transcript into "
        "the new task or send it to the model — context_messages() is "
        "identity-scoped with no admin override; got messages sent "
        f"upstream: {sent_messages!r}"
    )
    # The admin's task still functions normally — it just starts with no
    # inherited history, exactly like a brand-new contextId would.
    assert any("continuing the thread" in str(m) for m in sent_messages)
