"""RT-008 (loop.py review): ``append_assistant_turn``'s docstring claims a
pre-existing assistant tail's content is MERGED into, "preserving whatever
real content that tail carried ... rather than discarding it" — but the
non-list branch (``isinstance(tail_content, list)`` false) used to do
``messages[-1]["content"] = content``, which REPLACES and silently discards
the tail's existing content. That branch is reachable on the caller-supplied
-history path the docstring is written for (an AG-UI resend whose assistant
tail's content is a bare string) — and it is the identical malformed shape
``close_dangling_tool_use`` treats as unreadable-and-raise rather than
silently rewriting.
"""

from __future__ import annotations

from agent_sdk.agent.loop import append_assistant_turn


def test_append_assistant_turn_preserves_a_string_tail() -> None:
    messages: list[dict] = [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": "the prior reply"},
    ]
    append_assistant_turn(messages, [{"text": "continued"}])

    assert len(messages) == 2, "must merge into the tail, never add a second assistant turn"
    tail = messages[-1]
    assert tail["role"] == "assistant"
    assert isinstance(tail["content"], list)
    assert {"text": "the prior reply"} in tail["content"]
    assert {"text": "continued"} in tail["content"]
    assert tail["content"].index({"text": "the prior reply"}) < tail["content"].index(
        {"text": "continued"}
    )


def test_append_assistant_turn_replaces_a_falsy_tail() -> None:
    messages: list[dict] = [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": None},
    ]
    append_assistant_turn(messages, [{"text": "continued"}])

    assert len(messages) == 2
    assert messages[-1]["content"] == [{"text": "continued"}]


def test_append_assistant_turn_still_merges_list_content() -> None:
    messages: list[dict] = [
        {"role": "user", "content": [{"text": "hi"}]},
        {"role": "assistant", "content": [{"text": "the prior reply"}]},
    ]
    append_assistant_turn(messages, [{"text": "continued"}])

    assert len(messages) == 2
    assert messages[-1]["content"] == [{"text": "the prior reply"}, {"text": "continued"}]


def test_append_assistant_turn_appends_fresh_when_tail_is_user() -> None:
    messages: list[dict] = [{"role": "user", "content": [{"text": "hi"}]}]
    append_assistant_turn(messages, [{"text": "hello"}])

    assert len(messages) == 2
    assert messages[-1] == {"role": "assistant", "content": [{"text": "hello"}]}
