"""RT-007 (loop.py review): ``bridge_context_messages``'s head-trim loop
(``while bridged and not _is_user_turn_boundary(bridged[0]): bridged.pop(0)``)
used to drop leading orphan messages with no operator signal at all — the
sibling cap path for the identical outcome,
``tasks/memory.py::_turn_boundary_slice``, logs a WARNING in both its
fallback case (some trimming, a boundary still found) and its drop-everything
case (no boundary anywhere), and this function's own docstring cites that
function as its model ("same contract as ``_turn_boundary_slice``'s 'no
genuine boundary in the window' case") — but only the tail-drop path
(``close_dangling_tool_use``'s ``DanglingToolUseUnreadable`` catch) logged.

DBG-5 (debug round 5, reverting round 4's RT-007 guard): round 4 wrapped the
pop loop in ``if any(_is_user_turn_boundary(m) for m in bridged):``, borrowing
``_turn_boundary_slice``'s "capping must never rewrite a transcript it didn't
need to shrink" rule. That rule is a CAP rule — its untouched case
(``len(messages) <= cap``) always already has a legal head, the task's own
seed user turn — and it does not transfer to a REPAIR rule whose
no-boundary-anywhere case is, by definition, the one where the head is
broken. The guard therefore disabled the head repair in exactly the two
situations it exists for: a leading ``user``/``toolResult`` orphan, and a
leading ``assistant`` message. Both reach Bedrock's Converse API verbatim via
``routes/a2a.py::_create_task_record`` and are rejected outright — a failed
request, not one lost prior turn.

The head trim is unconditional again, and may empty the list. That is the
same outcome ``_turn_boundary_slice`` itself picks (with its own WARNING)
when a transcript it DID have to rewrite has no boundary anywhere, and a
continuation with no prior context is valid: ``_create_task_record`` appends
the fresh user turn immediately after. Both outcomes are logged — a partial
trim and a full drop each get their own distinct WARNING.
"""

from __future__ import annotations

import logging

from agent_sdk.agent.loop import bridge_context_messages


def test_partial_head_trim_logs_a_warning(sdk_caplog) -> None:
    prior = [
        {"role": "assistant", "content": [{"text": "stray leading turn"}]},
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "hello"}]},
    ]
    with sdk_caplog("agent_sdk.agent.loop", logging.WARNING) as records:
        bridged = bridge_context_messages(prior)

    assert bridged and bridged[0]["role"] == "user"
    assert any("turn boundary" in r.getMessage() for r in records), (
        "a partial head trim must be logged, not silent"
    )
    assert not any("dropping the entire prior transcript" in r.getMessage() for r in records)


def test_no_legal_head_anywhere_is_dropped_with_its_own_warning(sdk_caplog) -> None:
    """DBG-5: no message that can legally head a conversation means every
    message is popped and the transcript comes back empty, with the distinct
    drop-everything WARNING. Leaving it in place (round 4's guard) handed
    ``_create_task_record`` a ``toolResult`` orphan at index 0, which Converse
    rejects — losing the whole request instead of the prior context."""
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
    with sdk_caplog("agent_sdk.agent.loop", logging.WARNING) as records:
        bridged = bridge_context_messages(all_orphaned)

    assert bridged == []
    assert any(
        "dropping the entire prior transcript" in r.getMessage() for r in records
    ), "an emptied transcript must be logged with the drop-everything warning"


def test_repair_only_transcript_with_no_organic_boundary_is_dropped(sdk_caplog) -> None:
    """The GH-150 "out-of-loop repair-only tail" shape — a complete
    ``[assistant(toolUse), user(toolResult)]`` round with no organic user
    turn. It cannot be carried forward: its head is an assistant message, and
    Converse requires a conversation to start on ``user``. Dropping it costs
    one turn of context; keeping it costs the request."""
    prior = [
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
    with sdk_caplog("agent_sdk.agent.loop", logging.WARNING) as records:
        bridged = bridge_context_messages(prior)

    assert bridged == []
    assert any("dropping the entire prior transcript" in r.getMessage() for r in records)


def test_no_head_trim_logs_nothing(sdk_caplog) -> None:
    prior = [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "hello"}]},
    ]
    with sdk_caplog("agent_sdk.agent.loop", logging.WARNING) as records:
        bridged = bridge_context_messages(prior)

    assert bridged == prior
    assert not any("turn boundary" in r.getMessage() for r in records)
