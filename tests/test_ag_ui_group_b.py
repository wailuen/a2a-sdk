"""Group B AG-UI conformance fixes: GH-14, GH-17, SC-B1."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from agent_sdk.agent.events import ToolResultEvent
from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.routes.ag_ui import _RunMapper, _fold_history


# ── GH-14: synthetic TOOL_CALL_ARGS on resume path ──


def _make_mapper() -> _RunMapper:
    return _RunMapper(
        thread_id="t1",
        run_id="r1",
        capabilities=A2uiCapabilities.from_metadata(None),
    )


def test_resume_emits_tool_call_args_between_start_and_end() -> None:
    """ToolResultEvent with unseen tool_call_id must emit
    [TOOL_CALL_START, TOOL_CALL_ARGS(delta='{}'), TOOL_CALL_END, TOOL_CALL_RESULT]."""
    mapper = _make_mapper()
    event = ToolResultEvent(
        tool_call_id="unseen-id-001",
        tool_name="some_tool",
        ok=True,
        result="done",
    )
    frames = mapper.map(event)
    types = [f["type"] for f in frames]

    # Must contain all four in order
    assert "TOOL_CALL_START" in types, types
    assert "TOOL_CALL_ARGS" in types, types
    assert "TOOL_CALL_END" in types, types
    assert "TOOL_CALL_RESULT" in types, types

    idx_start = types.index("TOOL_CALL_START")
    idx_args = types.index("TOOL_CALL_ARGS")
    idx_end = types.index("TOOL_CALL_END")
    idx_result = types.index("TOOL_CALL_RESULT")
    assert idx_start < idx_args < idx_end < idx_result, (
        f"Expected START < ARGS < END < RESULT, got {idx_start}, {idx_args}, {idx_end}, {idx_result}"
    )

    args_frame = frames[idx_args]
    assert args_frame["toolCallId"] == "unseen-id-001"
    assert args_frame["delta"] == "{}", f"Expected delta='{{}}', got {args_frame['delta']!r}"


def test_normal_path_tool_call_args_unaffected() -> None:
    """On the normal path (START was emitted in this stream), no synthetic
    TOOL_CALL_ARGS should be added — the ToolCallEvent already emits one."""
    from agent_sdk.agent.events import ToolCallEvent

    mapper = _make_mapper()
    # Emit a real ToolCallEvent first so tool_call_id is in _seen_starts
    call_event = ToolCallEvent(
        tool_call_id="seen-id-001",
        tool_name="some_tool",
        arguments={"x": 1},
    )
    mapper.map(call_event)

    # Now emit the result — should NOT inject a second TOOL_CALL_ARGS
    result_event = ToolResultEvent(
        tool_call_id="seen-id-001",
        tool_name="some_tool",
        ok=True,
        result="ok",
    )
    frames = mapper.map(result_event)
    types = [f["type"] for f in frames]
    # On the normal path _ensure_step() may open a step, but no synthetic START
    assert types.count("TOOL_CALL_START") == 0, types
    assert types.count("TOOL_CALL_ARGS") == 0, types
    assert "TOOL_CALL_RESULT" in types, types


# ── GH-17: _fold_history ContentPart array coercion ──


@pytest.mark.parametrize(
    "content, expected",
    [
        # (a) str passes through unchanged
        ("hello world", "hello world"),
        # (b) single text ContentPart → extracted text
        ([{"type": "text", "text": "hi"}], "hi"),
        # (c) mixed text + image → only text joined
        (
            [
                {"type": "text", "text": "caption"},
                {"type": "image_url", "image_url": {"url": "http://img"}},
                {"type": "text", "text": " end"},
            ],
            "caption end",
        ),
        # (d) no-text list → empty string
        ([{"type": "image_url", "image_url": {"url": "http://img"}}], ""),
    ],
)
def test_fold_history_content_coercion(content: Any, expected: str) -> None:
    """_fold_history must correctly extract text from ContentPart arrays."""
    messages = [{"role": "user", "content": content}]
    result = _fold_history(messages)
    assert result is not None
    # After folding, content is stored as [{"text": ...}] dicts
    assert result[0]["content"][0]["text"] == expected


def test_fold_history_str_passthrough() -> None:
    """Plain string content must survive unmodified."""
    messages = [{"role": "user", "content": "plain text"}]
    result = _fold_history(messages)
    assert result is not None
    assert result[0]["content"][0]["text"] == "plain text"


def test_fold_history_no_text_list_returns_empty_string() -> None:
    """A list with no text parts must yield empty string content.
    Because empty string is falsy and _fold_history skips blank assistant turns,
    but for user messages the empty string flows through. However _fold_history
    only skips assistant messages with no content. User turn with '' still folds
    (folded and None-check is at the end for no user content at all)."""
    messages = [
        {"role": "user", "content": [{"type": "image_url", "url": "http://img"}]},
    ]
    result = _fold_history(messages)
    # Folded result: the content["text"] should be "" (extracted from no-text list)
    # The message still has role="user" so it's included (empty strings are valid)
    # But wait: content = "" (falsy) → raw.get("content") or "" = "" — let's trace
    # Actually the list is truthy so `raw.get("content") or ""` returns the list.
    # Then isinstance(content, list) → join text parts → "" (falsy str)
    # The assistant check `if role == "assistant" and not content.strip()` skips only assistant
    # User messages with "" content still get appended.
    assert result is not None
    assert result[0]["content"][0]["text"] == ""


# ── SC-B1: SSE heartbeat ──
# Integration-style test: pause the subscription queue >15 s and assert a heartbeat
# is emitted. We patch asyncio.wait_for to raise TimeoutError on the first call to
# simulate an idle period without actually waiting 15 seconds.


def test_heartbeat_constant_is_ping_comment() -> None:
    """The HEARTBEAT constant exported from common/sse must be the SSE comment
    b': ping\\n\\n' so load balancers don't close idle connections."""
    from agent_sdk.common.sse import HEARTBEAT
    assert HEARTBEAT == b": ping\n\n"


async def test_heartbeat_fires_on_idle_stream(client, fake_model) -> None:
    """When the subscription queue is idle for >15 s the stream emits a heartbeat
    comment frame. We simulate this by temporarily patching asyncio.wait_for to
    raise TimeoutError exactly once, then let the stream complete normally.

    The heartbeat is a raw SSE comment (b': ping\\n\\n') and does NOT appear in
    sse_frames() (which only collects 'data:' lines). We therefore capture the raw
    response text and assert the comment is present."""
    from agent_sdk.testing import reply

    orig_wait_for = asyncio.wait_for
    call_count = 0

    async def patched_wait_for(coro, timeout):  # type: ignore[override]
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # Simulate the first sub.get() timing out
            coro.close()  # discard the unawaited coroutine
            raise asyncio.TimeoutError
        return await orig_wait_for(coro, timeout)

    fake_model.script(reply("hello"))

    import agent_sdk.routes.ag_ui as ag_ui_module

    ag_ui_module.asyncio.wait_for = patched_wait_for  # type: ignore[attr-defined]
    try:
        r = await client.post(
            "/ag-ui/run",
            json={
                "threadId": "t-hb",
                "runId": "r-hb",
                "messages": [{"id": "m1", "role": "user", "content": "ping"}],
                "state": {},
                "tools": [],
                "context": [],
                "forwardedProps": {},
            },
        )
    finally:
        ag_ui_module.asyncio.wait_for = orig_wait_for  # type: ignore[attr-defined]

    assert r.status_code == 200
    raw = r.text
    assert ": ping" in raw, f"Expected heartbeat comment in response, got: {raw[:500]}"
