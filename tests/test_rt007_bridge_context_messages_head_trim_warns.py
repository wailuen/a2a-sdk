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


def test_full_head_trim_logs_a_distinct_warning(sdk_caplog) -> None:
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
    ), "emptying the list entirely must log its own distinct warning"


def test_no_head_trim_logs_nothing(sdk_caplog) -> None:
    prior = [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "hello"}]},
    ]
    with sdk_caplog("agent_sdk.agent.loop", logging.WARNING) as records:
        bridged = bridge_context_messages(prior)

    assert bridged == prior
    assert not any("turn boundary" in r.getMessage() for r in records)
