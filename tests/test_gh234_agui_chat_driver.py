"""GH-234: ChatDriver AG-UI driver — headers, terminal event, text join, RUN_ERROR."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from agent_sdk.testing.chat import ChatDriver
from agent_sdk.testing.turns import run_turn

SECRET = "sentinel-SECRET-9f3a"
NO_TERMINAL = "stream closed without a terminal event"
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "agent_sdk" / "console" / "static"


def _sse(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


def _content(delta, mid="m1"):
    return {"type": "TEXT_MESSAGE_CONTENT", "messageId": mid, "delta": delta}


FINISHED = {"type": "RUN_FINISHED", "outcome": {"type": "success"}}
ERROR = {"type": "RUN_ERROR", "message": "boom"}


def _driver(body, seen=None, status=200, **kw):
    def handler(req):
        if seen is not None:
            seen.append(req)
        return httpx.Response(status, content=body)

    client = httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))
    return ChatDriver(client, **kw)


def _emits():
    log = {"error": [], "text": []}
    return log, {"error": log["error"].append, "text": log["text"].append}


@pytest.mark.asyncio
async def test_headers_sent_with_credentials_and_accept():
    seen = []
    d = _driver(_sse(_content("hi"), FINISHED), seen, credentials={"X-Agent-Credentials": SECRET})
    await d.agui_turn("q", "th", [])
    req = seen[0]
    assert req.headers["x-agent-credentials"] == SECRET
    assert req.headers["accept"] == "text/event-stream"
    assert SECRET.encode() not in req.content and SECRET not in str(req.url)


@pytest.mark.asyncio
async def test_unterminated_stream_fires_fixed_error():
    d = _driver(_sse(_content("part")))
    log, emit = _emits()
    out = await d.agui_turn("q", "th", [], emit=emit)
    assert log["error"] == [NO_TERMINAL]
    assert log["text"] == ["part"]
    assert out == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("frames", [[_content("part")], [_content("part"), ERROR]])
async def test_turn_does_not_append_partial_reply(frames):
    d = _driver(_sse(*frames))
    msgs: list = []
    out = await d.agui_turn("q", "th", msgs)
    assert out == ""
    assert [m for m in msgs if m["role"] == "assistant"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("frames", [[_content("part")], [_content("part"), ERROR]])
async def test_resume_does_not_append_partial_reply(frames):
    d = _driver(_sse(*frames))
    msgs = [{"role": "user", "content": "q"}]
    out = await d.agui_resume("i1", "th", msgs, payload={"decision": "yes"})
    assert out == ""
    assert [m for m in msgs if m["role"] == "assistant"] == []


@pytest.mark.asyncio
async def test_frames_after_run_error_ignored():
    d = _driver(_sse(_content("a"), ERROR, _content("late"), FINISHED))
    log, emit = _emits()
    out = await d.agui_turn("q", "th", [], emit=emit)
    assert log["text"] == ["a"]
    assert log["error"] == ["boom"]
    assert out == ""


@pytest.mark.asyncio
async def test_messages_joined_with_newline_deltas_concatenated():
    d = _driver(_sse(
        _content("Hel", "a"), _content("lo", "a"),
        _content("Wor", "b"), _content("ld", "b"),
        FINISHED,
    ))
    assert await d.agui_turn("q", "th", []) == "Hello\nWorld"


@pytest.mark.asyncio
async def test_text_message_chunk_handled():
    d = _driver(_sse(
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "a", "delta": "one"},
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "a", "delta": "!"},
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "b", "delta": "two"},
        FINISHED,
    ))
    assert await d.agui_turn("q", "th", []) == "one!\ntwo"


@pytest.mark.asyncio
async def test_credentials_never_leak_in_any_outcome():
    cases = {
        "finished": (200, _sse(_content("hi"), FINISHED)),
        "unterminated": (200, _sse(_content("hi"))),
        "run_error": (200, _sse(_content("hi"), ERROR)),
        "http_error": (500, b"upstream"),
    }
    for name, (status, body) in cases.items():
        seen = []
        d = _driver(body, seen, status=status, credentials={"X-Agent-Credentials": SECRET})
        log, emit = _emits()
        try:
            await d.agui_turn("q", "th", [], emit=emit)
        except httpx.HTTPStatusError as exc:
            assert SECRET not in str(exc) and SECRET not in repr(exc), name
        req = seen[0]
        assert req.headers["x-agent-credentials"] == SECRET
        assert SECRET.encode() not in req.content, name
        assert SECRET not in str(req.url), name
        assert all(SECRET not in s for s in log["error"] + log["text"]), name


async def _run(tmp_path, body):
    client = httpx.AsyncClient(
        base_url="http://t", transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    )
    kf = tmp_path / "key"
    kf.write_text("k\n")
    async with client as c:
        return await run_turn(
            transport="agui", base_url="http://t", key_file=kf, query="q",
            run_key="r1", state_dir=tmp_path / "state", client=c, budget_s=5,
        )


@pytest.mark.asyncio
async def test_run_turn_unterminated_stream_fails(tmp_path):
    out = await _run(tmp_path, _sse(_content("partial")))
    assert out["ok"] is False and out["reply"] == ""


@pytest.mark.asyncio
async def test_run_turn_partial_then_run_error_fails(tmp_path):
    out = await _run(tmp_path, _sse(_content("partial"), ERROR))
    assert out["ok"] is False and out["reply"] == ""


@pytest.mark.asyncio
async def test_run_turn_normal_stream_passes(tmp_path):
    out = await _run(tmp_path, _sse(_content("fine"), FINISHED))
    assert out["ok"] is True and out["reply"] == "fine"


def test_console_static_changes():
    a2ui = (STATIC / "a2ui.js").read_text()
    chat = (STATIC / "chat.js").read_text()
    assert "export function resetSurfaces()" in a2ui
    assert "surfaces.clear()" in a2ui
    assert "resetSurfaces" in chat
    assert "TEXT_MESSAGE_CHUNK" in chat


def test_failed_resume_post_restores_form_and_placeholder():
    chat = (STATIC / "chat.js").read_text()
    start = chat.index("if (!resp) {\n      if (resumed) {")
    block = chat[start:start + 400]
    assert "pendingInterrupt = resumed" in block
    assert "interruptForm(resumed)" in block
    assert "input.placeholder" in block


@pytest.mark.asyncio
async def test_chunk_without_message_id_inherits_open_chunk():
    """w063 RT-001: AG-UI carries messageId on the first chunk only."""
    d = _driver(_sse(
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "a", "delta": "Hel"},
        {"type": "TEXT_MESSAGE_CHUNK", "delta": "lo"},
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "b", "delta": "World"},
        {"type": "TEXT_MESSAGE_CHUNK", "delta": "!"},
        FINISHED,
    ))
    assert await d.agui_turn("q", "th", []) == "Hello\nWorld!"


def test_console_chunk_id_inherited_and_folded_only_after_run_finished():
    """w063 RT-002/RT-003: chat.js mirrors chat.py on chunk ids and partial replies."""
    chat = (STATIC / "chat.js").read_text()
    assert "else id = chunkId;" in chat
    assert "for (const id of finished ? chunkOpen : [])" in chat


@pytest.mark.asyncio
async def test_empty_message_adds_no_separator_and_chunk_id_resets():
    d = _driver(_sse(
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "m0"},
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "m1", "delta": "a"},
        {"type": "TEXT_MESSAGE_START", "messageId": "m2", "role": "assistant"},
        _content("b", "m2"),
        {"type": "TEXT_MESSAGE_END", "messageId": "m2"},
        {"type": "TEXT_MESSAGE_CHUNK", "delta": "c"},
        FINISHED,
    ))
    assert await d.agui_turn("q", "th", []) == "a\nb\nc"
