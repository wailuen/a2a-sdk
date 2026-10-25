"""GH-269: AG-UI text is scrubbed, a mid-batch emit failure leaves no dangling START,
and the console fallback caps line count."""

from __future__ import annotations

import pytest

from agent_sdk.agent.events import TextEvent
from agent_sdk.routes import ag_ui
from agent_sdk.routes.ag_ui import _RunMapper
from agent_sdk.testing import reply

from .test_ag_ui import run, run_body
from .test_gh239_console_caps import _run, needs_node
from .test_gh215_console_generic_renderer import _surface, _text, _walk


def _types(frames):
    return [f["type"] for f in frames if f["type"].startswith(("TEXT_", "RUN_"))]


async def test_lone_surrogate_text_is_scrubbed(client, fake_model):
    fake_model.script(reply("bad \ud800 text"))
    frames = await run(client, run_body())
    assert _types(frames) == [
        "RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_CONTENT", "TEXT_MESSAGE_END", "RUN_FINISHED",
    ]
    content = next(f for f in frames if f["type"] == "TEXT_MESSAGE_CONTENT")
    assert content["delta"] == "bad � text"


def test_mapper_scrubs_delta():
    from agent_sdk.a2ui.translator import A2uiCapabilities

    m = _RunMapper("t", "r", A2uiCapabilities())
    frames = m.map(TextEvent(text="\udc00x"))
    assert frames[1]["delta"] == "�x"


async def test_content_serialization_failure_closes_message(client, fake_model, monkeypatch):
    real = ag_ui.sse_data

    def flaky(obj):
        if isinstance(obj, dict) and obj.get("type") == "TEXT_MESSAGE_CONTENT":
            raise ValueError("forced")
        return real(obj)

    monkeypatch.setattr(ag_ui, "sse_data", flaky)
    fake_model.script(reply("hello"))
    frames = await run(client, run_body())
    assert _types(frames) == ["RUN_STARTED", "TEXT_MESSAGE_START", "TEXT_MESSAGE_END", "RUN_ERROR"]
    start = next(f for f in frames if f["type"] == "TEXT_MESSAGE_START")
    end = next(f for f in frames if f["type"] == "TEXT_MESSAGE_END")
    assert start["messageId"] == end["messageId"]


@needs_node
def test_fallback_caps_line_count(tmp_path):
    lines = "\n".join(f"L{i}" for i in range(150))
    [r] = _run(tmp_path, [{"messages": _surface("F", "Thing", 5), "fallback": lines}])
    cap = r["max"]
    node = r["nodes"][0]
    shown = [x for x in _walk(node) if "a2ui-fallback-line" in (x.get("cls") or "")]
    assert len(shown) == cap
    assert f"{150 - cap} more" in _text(node)


@needs_node
def test_fallback_clips_prose_before_splitting(tmp_path):
    big = "\n".join(["x" * 100] * 1000)
    [r] = _run(tmp_path, [{"messages": _surface("F", "Thing", 5), "fallback": big}])
    node = r["nodes"][0]
    shown = [x for x in _walk(node) if "a2ui-fallback-line" in (x.get("cls") or "")]
    assert len(shown) == r["max"]
    assert "more" in _text(node)
