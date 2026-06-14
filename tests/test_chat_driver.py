"""ChatDriver — agui_turn() RUN_FINISHED / interrupt handling.

Regression tests for the HIGH conformance bug where agui_turn() had no
RUN_FINISHED branch, so interrupt outcomes were silently swallowed.
"""

from __future__ import annotations

import json
import uuid

import pytest

from agent_sdk.testing import FakeModelClient, tool_call, reply
from agent_sdk.testing.chat import ChatDriver


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def sse_lines(frames: list[dict]) -> bytes:
    """Encode a list of frame dicts as SSE bytes (``data: ...\n\n`` per frame)."""
    lines = []
    for f in frames:
        lines.append(f"data: {json.dumps(f)}\n\n")
    return "".join(lines).encode()


# ---------------------------------------------------------------------------
# Unit-level test: simulate RUN_FINISHED with interrupt via a mock transport
# ---------------------------------------------------------------------------


class _MockTransport(object):
    """Minimal httpx async transport that returns a pre-built SSE response."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    async def handle_async_request(self, request):
        import httpx

        stream = httpx.ByteStream(self._body)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _make_client(frames: list[dict]):
    """Return an AsyncClient whose /ag-ui/run replies with *frames* as SSE."""
    import httpx

    body = sse_lines(frames)
    transport = _MockTransport(body)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


async def test_agui_turn_interrupt_fires_emit():
    """RUN_FINISHED with interrupt outcome must fire the 'interrupt' emit key."""
    interrupt_obj = {
        "id": "intr-1",
        "toolCallId": "tc-1",
        "responseSchema": {"type": "object"},
    }
    frames = [
        {"type": "RUN_STARTED", "runId": "r1", "threadId": "t1"},
        {"type": "STATE_SNAPSHOT", "snapshot": {}},
        {"type": "STEP_STARTED", "stepName": "turn-1"},
        {"type": "TEXT_MESSAGE_START", "messageId": "m1"},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "thinking..."},
        {"type": "TEXT_MESSAGE_END", "messageId": "m1"},
        {"type": "STEP_FINISHED", "stepName": "turn-1"},
        {
            "type": "RUN_FINISHED",
            "outcome": {
                "type": "interrupt",
                "interrupts": [interrupt_obj],
            },
        },
    ]

    async with _make_client(frames) as client:
        driver = ChatDriver(client)
        fired: list = []
        messages: list[dict] = []

        await driver.agui_turn(
            "publish something",
            "thread-1",
            messages,
            emit={"interrupt": lambda x: fired.append(x)},
        )

    assert len(fired) == 1, f"expected 1 interrupt emit, got {len(fired)}: {fired}"
    assert fired[0]["id"] == "intr-1"
    assert fired[0]["toolCallId"] == "tc-1"


async def test_agui_turn_interrupt_no_interrupt_list_passes_outcome():
    """When interrupts list is empty, emit receives the outcome dict itself."""
    outcome = {"type": "interrupt"}
    frames = [
        {"type": "RUN_STARTED", "runId": "r1", "threadId": "t1"},
        {"type": "STATE_SNAPSHOT", "snapshot": {}},
        {"type": "RUN_FINISHED", "outcome": outcome},
    ]

    async with _make_client(frames) as client:
        driver = ChatDriver(client)
        fired: list = []

        await driver.agui_turn(
            "x",
            "t1",
            [],
            emit={"interrupt": lambda x: fired.append(x)},
        )

    assert len(fired) == 1
    assert fired[0]["type"] == "interrupt"


async def test_agui_turn_non_interrupt_run_finished_does_not_fire():
    """RUN_FINISHED without an interrupt outcome must NOT fire 'interrupt'."""
    frames = [
        {"type": "RUN_STARTED", "runId": "r1", "threadId": "t1"},
        {"type": "STATE_SNAPSHOT", "snapshot": {}},
        {"type": "TEXT_MESSAGE_START", "messageId": "m1"},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "done"},
        {"type": "TEXT_MESSAGE_END", "messageId": "m1"},
        {"type": "RUN_FINISHED", "outcome": {"type": "success"}},
    ]

    async with _make_client(frames) as client:
        driver = ChatDriver(client)
        fired: list = []
        messages: list[dict] = []

        result = await driver.agui_turn(
            "hello",
            "t1",
            messages,
            emit={"interrupt": lambda x: fired.append(x)},
        )

    assert fired == [], f"interrupt should NOT fire for success outcome, got {fired}"
    assert result == "done"


async def test_agui_turn_run_finished_breaks_loop():
    """Frames after RUN_FINISHED must be ignored (loop breaks on RUN_FINISHED)."""
    frames = [
        {"type": "RUN_STARTED", "runId": "r1", "threadId": "t1"},
        {"type": "STATE_SNAPSHOT", "snapshot": {}},
        {"type": "TEXT_MESSAGE_START", "messageId": "m1"},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "hello"},
        {"type": "TEXT_MESSAGE_END", "messageId": "m1"},
        {"type": "RUN_FINISHED", "outcome": {"type": "success"}},
        # Frames below appear AFTER RUN_FINISHED and must be ignored
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m2", "delta": " world"},
    ]

    async with _make_client(frames) as client:
        driver = ChatDriver(client)
        messages: list[dict] = []

        result = await driver.agui_turn("hi", "t1", messages)

    # Only the text before RUN_FINISHED should be collected
    assert result == "hello", f"expected 'hello', got {result!r}"


# ---------------------------------------------------------------------------
# Integration test: ChatDriver over live ASGI example agent
# ---------------------------------------------------------------------------


async def test_agui_turn_interrupt_live(client, fake_model):
    """End-to-end: ChatDriver.agui_turn() fires 'interrupt' against live agent."""
    fake_model.script(tool_call("publish_note", {"note": "test"}), reply("after resume"))

    driver = ChatDriver(client)
    fired: list = []
    messages: list[dict] = []

    await driver.agui_turn(
        "publish something",
        uuid.uuid4().hex,
        messages,
        emit={"interrupt": lambda x: fired.append(x)},
    )

    assert len(fired) == 1, f"expected 1 interrupt from live agent, got {fired}"
    intr = fired[0]
    assert intr.get("id"), f"interrupt missing id: {intr}"
    assert intr.get("toolCallId"), f"interrupt missing toolCallId: {intr}"
