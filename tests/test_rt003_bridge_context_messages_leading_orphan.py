"""RT-003 (w040 follow-up): ``bridge_context_messages``'s docstring claims it
re-asserts "BOTH transcript invariants a store override can break" but only
ever re-asserted the TAIL invariants (dangling ``toolUse`` tail,
ends-on-``user``). A ``TaskStore.context_messages()`` override can also hand
back a broken HEAD — a leading ``user``/``toolResult`` orphan whose matching
``toolUse`` fell outside the store's own window, or a leading ``assistant``
message — and neither shape is repaired before ``routes/a2a.py``'s
``_create_task_record`` folds it straight into a new task's
``record.messages`` and on to Bedrock's Converse API, which rejects both.

``TaskStore.context_messages()``'s own docstring (RT-007, tasks/store.py)
already makes a concrete store responsible for landing any cap on a genuine
user-authored turn boundary — a ``role == 'user'`` message with no
``toolResult`` block in its content, the same predicate
``tasks/memory.py::_turn_boundary_slice`` uses and the same shape
``routes/ag_ui.py::_fold_history``'s ``while folded and folded[0]['role'] !=
'user'`` loop enforces for the AG-UI carrier — but nothing enforces it on
read for the A2A carrier. This is the read-side gap.
"""

from __future__ import annotations

import uuid
from typing import Any

from agent_sdk.agent.loop import bridge_context_messages
from agent_sdk.tasks.memory import InMemoryTaskStore

from .conftest import wait_for_state


def _leading_tool_result_orphan() -> list[dict[str, Any]]:
    """A store window truncated mid-tool-round: the head is a
    ``toolResult`` continuation whose matching ``toolUse`` fell outside the
    window, followed by the assistant turn that closed out that round, and
    then a genuine, later user-authored turn that must survive."""
    return [
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "call-1",
                        "content": [{"text": "orphaned result"}],
                        "status": "success",
                    }
                }
            ],
        },
        {"role": "assistant", "content": [{"text": "that round's answer"}]},
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "hello"}]},
    ]


def _leading_assistant() -> list[dict[str, Any]]:
    return [
        {"role": "assistant", "content": [{"text": "stray assistant turn"}]},
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "hello"}]},
    ]


def test_bridge_context_messages_drops_a_leading_tool_result_orphan() -> None:
    bridged = bridge_context_messages(_leading_tool_result_orphan())
    assert bridged, "a genuine user turn follows the orphan; it must survive"
    assert bridged[0]["role"] == "user"
    assert not any(
        isinstance(b, dict) and "toolResult" in b for b in bridged[0].get("content", [])
    ), "the leading toolResult-only orphan must not be the head any more"


def test_bridge_context_messages_drops_a_leading_assistant_message() -> None:
    bridged = bridge_context_messages(_leading_assistant())
    assert bridged[0]["role"] == "user"
    assert bridged[0]["content"] == [{"text": "hi"}]


def test_bridge_context_messages_head_all_orphaned_is_emptied() -> None:
    """DBG-5 (debug round 5): no message in the transcript can legally head a
    conversation, so every one is dropped. Round 4 left this shape untouched
    on ``_turn_boundary_slice``'s "never rewrite a transcript it didn't need
    to shrink" rule — but that is a CAP rule whose untouched case always
    already has a legal head, and borrowing it here disabled the head repair
    in precisely the case the head is broken. Converse rejects a leading
    ``toolResult`` orphan, so the request fails wholesale rather than losing
    one turn of prior context."""
    all_orphaned = [
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "call-1",
                        "content": [{"text": "x"}],
                        "status": "success",
                    }
                }
            ],
        },
        {"role": "assistant", "content": [{"text": "stray"}]},
    ]
    assert bridge_context_messages(all_orphaned) == []


def test_bridge_context_messages_leaves_a_correctly_shaped_head_untouched() -> None:
    """No regression on the already-passing shape (a genuine leading user
    turn with no toolResult block)."""
    prior = [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "hello"}]},
    ]
    assert bridge_context_messages(prior) == prior


async def test_create_task_record_drops_a_leading_tool_result_orphan_head(client, fake_model):
    """End-to-end at the seam the route actually uses: a durable-shaped store
    override hands back a transcript whose HEAD is a toolResult orphan, and
    what lands in the new task's ``record.messages`` — and what is sent to
    the model — never starts on one."""
    from agent_sdk.testing import reply

    ctx = uuid.uuid4().hex
    store = client.app.state.task_store
    store.context_messages = lambda context_id, identity=None: _leading_tool_result_orphan()

    fake_model.script(reply("second reply"))
    r = await client.post(
        "/v1/message:send",
        json={
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "turn two"}],
                "messageId": uuid.uuid4().hex,
                "contextId": ctx,
            }
        },
    )
    assert r.status_code == 200, r.text
    await wait_for_state(client, r.json()["id"])

    record = store.get(r.json()["id"])
    assert record is not None
    assert not any(
        isinstance(b, dict) and "toolResult" in b
        for b in record.messages[0].get("content", [])
    ), record.messages

    assert fake_model.calls, "converse must have been called"
    sent = fake_model.calls[0]["messages"]
    assert not any(
        isinstance(b, dict) and "toolResult" in b for b in sent[0].get("content", [])
    ), sent


async def test_create_task_record_drops_a_leading_assistant_head(client, fake_model):
    from agent_sdk.testing import reply

    ctx = uuid.uuid4().hex
    store = client.app.state.task_store
    store.context_messages = lambda context_id, identity=None: _leading_assistant()

    fake_model.script(reply("second reply"))
    r = await client.post(
        "/v1/message:send",
        json={
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "turn two"}],
                "messageId": uuid.uuid4().hex,
                "contextId": ctx,
            }
        },
    )
    assert r.status_code == 200, r.text
    await wait_for_state(client, r.json()["id"])

    record = store.get(r.json()["id"])
    assert record is not None
    assert record.messages[0]["role"] == "user"

    assert fake_model.calls
    sent = fake_model.calls[0]["messages"]
    assert sent[0]["role"] == "user"


async def test_create_task_record_head_is_converse_legal_with_no_boundary_anywhere(
    client, fake_model
):
    """DBG-5, the harm chain round 4's guard reopened: a store window holding
    only a complete ``[assistant(toolUse), user(toolResult)]`` round has no
    genuine user turn anywhere, so nothing was trimmed and an ASSISTANT
    message headed the conversation sent to Converse — which requires a
    conversation to start on ``user`` and rejects the request outright."""
    from agent_sdk.testing import reply

    ctx = uuid.uuid4().hex
    store = client.app.state.task_store
    store.context_messages = lambda context_id, identity=None: [
        {
            "role": "assistant",
            "content": [{"toolUse": {"toolUseId": "call-1", "name": "f", "input": {}}}],
        },
        {
            "role": "user",
            "content": [
                {
                    "toolResult": {
                        "toolUseId": "call-1",
                        "content": [{"text": "ok"}],
                        "status": "success",
                    }
                }
            ],
        },
    ]

    fake_model.script(reply("second reply"))
    r = await client.post(
        "/v1/message:send",
        json={
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "turn two"}],
                "messageId": uuid.uuid4().hex,
                "contextId": ctx,
            }
        },
    )
    assert r.status_code == 200, r.text
    await wait_for_state(client, r.json()["id"])

    record = store.get(r.json()["id"])
    assert record is not None
    assert record.messages[0]["role"] == "user", record.messages

    assert fake_model.calls, "converse must have been called"
    sent = fake_model.calls[0]["messages"]
    assert sent[0]["role"] == "user", sent
    assert not any(
        isinstance(b, dict) and "toolResult" in b for b in sent[0].get("content", [])
    ), sent


def test_store_override_head_orphan_via_reference_store() -> None:
    """Same shape, driven through a concrete ``InMemoryTaskStore`` subclass
    override — mirrors ``test_rt003_context_messages_dangling_tool_use.py``'s
    tail-side coverage of the same seam."""

    class _OrphanHeadStore(InMemoryTaskStore):
        def context_messages(self, context_id, identity=None):  # type: ignore[override]
            return _leading_tool_result_orphan()

    store = _OrphanHeadStore()
    prior = store.context_messages("c1")
    bridged = bridge_context_messages(prior)
    assert bridged[0]["role"] == "user"
    assert not any(
        isinstance(b, dict) and "toolResult" in b for b in bridged[0].get("content", [])
    )
