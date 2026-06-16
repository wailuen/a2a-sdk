"""ChatDriver — agui_turn() RUN_FINISHED / interrupt handling + Group E SC items.

Regression tests for the HIGH conformance bug where agui_turn() had no
RUN_FINISHED branch, so interrupt outcomes were silently swallowed.

Group E tests (SC-E1 through SC-E5) cover:
  SC-E1 Auth header injection
  SC-E2 agent.json fallback card discovery
  SC-E3 additionalInterfaces transport fallback
  SC-E4 resume() method
  SC-E5 A2AError error code constants
"""

from __future__ import annotations

import json
import uuid

import pytest
import httpx

from agent_sdk.testing import FakeModelClient, tool_call, reply
from agent_sdk.testing.chat import A2AError, ChatDriver


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


# ===========================================================================
# Group E — SC-E1 through SC-E5 unit tests
# ===========================================================================


# ---------------------------------------------------------------------------
# Shared A2A mock transport helpers
# ---------------------------------------------------------------------------


class _RoutedTransport:
    """Minimal httpx async transport routing requests to per-path handlers."""

    def __init__(self, routes: dict) -> None:
        # routes: {path: callable(request) -> httpx.Response}
        self._routes = routes
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        handler = self._routes.get(path)
        if handler is None:
            return httpx.Response(404, json={"error": "not found"})
        return handler(request)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


def _a2a_card(preferred_transport: str = "HTTP+JSON", additional: list | None = None) -> dict:
    card: dict = {"preferredTransport": preferred_transport}
    if additional:
        card["additionalInterfaces"] = additional
    return card


def _task_response(state: str = "completed", task_id: str = "task-1") -> dict:
    return {"id": task_id, "status": {"state": state}, "history": [], "artifacts": []}


# ---------------------------------------------------------------------------
# SC-E1: Auth header injection
# ---------------------------------------------------------------------------


async def test_sc_e1_credentials_sent_on_message_send():
    """ChatDriver with credentials sends Authorization header on /v1/message:send."""
    captured: list[dict] = []

    def handle_card(req):
        return httpx.Response(200, json=_a2a_card())

    def handle_send(req):
        captured.append({"path": req.url.path, "headers": dict(req.headers)})
        return httpx.Response(200, json=_task_response(task_id="task-1"))

    def handle_task(req):
        return httpx.Response(200, json=_task_response(state="completed", task_id="task-1"))

    transport = _RoutedTransport({
        "/.well-known/agent-card.json": handle_card,
        "/v1/message:send": handle_send,
        "/v1/tasks/task-1": handle_task,
    })
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        driver = ChatDriver(
            client,
            credentials={"Authorization": "Bearer test"},
            poll_interval=0.01,
        )
        # Pre-set card so _discover_card doesn't go through routing
        driver._card = _a2a_card()
        await driver.a2a_turn("hello")

    assert captured, "no /v1/message:send request captured"
    auth = captured[0]["headers"].get("authorization", "")
    assert auth == "Bearer test", f"expected 'Bearer test', got {auth!r}"


async def test_sc_e1_credentials_sent_on_tasks_get():
    """ChatDriver with credentials sends Authorization header on /v1/tasks/{id} poll."""
    poll_captured: list[dict] = []
    call_count = 0

    def handle_send(req):
        # Return an in-progress task to trigger a poll
        return httpx.Response(200, json=_task_response(state="working", task_id="task-99"))

    def handle_task(req):
        nonlocal call_count
        call_count += 1
        poll_captured.append({"path": req.url.path, "headers": dict(req.headers)})
        return httpx.Response(200, json=_task_response(state="completed", task_id="task-99"))

    transport = _RoutedTransport({
        "/v1/message:send": handle_send,
        "/v1/tasks/task-99": handle_task,
    })
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        driver = ChatDriver(
            client,
            credentials={"Authorization": "Bearer test"},
            poll_interval=0.01,
        )
        driver._card = _a2a_card()
        await driver.a2a_turn("hello")

    assert poll_captured, "no /v1/tasks/{id} request captured"
    auth = poll_captured[0]["headers"].get("authorization", "")
    assert auth == "Bearer test", f"expected 'Bearer test' on poll, got {auth!r}"


# ---------------------------------------------------------------------------
# SC-E2: agent.json fallback
# ---------------------------------------------------------------------------


async def test_sc_e2_agent_json_fallback():
    """ChatDriver falls back to /.well-known/agent.json when agent-card.json is 404."""

    def handle_card_json(req):
        return httpx.Response(404)

    def handle_agent_json(req):
        return httpx.Response(200, json=_a2a_card())

    transport = _RoutedTransport({
        "/.well-known/agent-card.json": handle_card_json,
        "/.well-known/agent.json": handle_agent_json,
    })
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        driver = ChatDriver(client)
        card = await driver._discover_card()

    assert card.get("preferredTransport") == "HTTP+JSON"


async def test_sc_e2_both_404_raises():
    """When both agent-card.json and agent.json return 404, _discover_card raises."""

    def handle_404(req):
        return httpx.Response(404)

    transport = _RoutedTransport({
        "/.well-known/agent-card.json": handle_404,
        "/.well-known/agent.json": handle_404,
    })
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        driver = ChatDriver(client)
        with pytest.raises(httpx.HTTPStatusError):
            await driver._discover_card()


# ---------------------------------------------------------------------------
# SC-E3: additionalInterfaces transport fallback
# ---------------------------------------------------------------------------


async def test_sc_e3_additional_interfaces_fallback():
    """When preferredTransport=GRPC (unsupported), fall back via additionalInterfaces."""
    captured: list[str] = []

    def handle_send(req):
        captured.append(req.url.path)
        return httpx.Response(200, json=_task_response(task_id="task-fb"))

    def handle_task(req):
        return httpx.Response(200, json=_task_response(state="completed", task_id="task-fb"))

    card = _a2a_card(
        preferred_transport="GRPC",
        additional=[{"transport": "HTTP+JSON", "url": "http://test/v1"}],
    )
    transport = _RoutedTransport({
        "/v1/message:send": handle_send,
        "/v1/tasks/task-fb": handle_task,
    })
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        driver = ChatDriver(client, poll_interval=0.01)
        driver._card = card
        await driver.a2a_turn("hello")

    assert "/v1/message:send" in captured, "expected fallback to HTTP+JSON transport"


async def test_sc_e3_no_fallback_raises():
    """When preferredTransport is unsupported and no additionalInterfaces, raises ValueError."""
    card = _a2a_card(preferred_transport="GRPC")
    transport = _RoutedTransport({})
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        driver = ChatDriver(client)
        driver._card = card
        with pytest.raises(ValueError, match="unsupported A2A transport"):
            await driver.a2a_turn("hello")


# ---------------------------------------------------------------------------
# SC-E4: resume() method
# ---------------------------------------------------------------------------


async def test_sc_e4_resume_sends_task_and_context_ids():
    """resume() POSTs to /v1/message:send with taskId and contextId."""
    captured_body: list[dict] = []

    def handle_send(req):
        body = json.loads(req.content)
        captured_body.append(body)
        # Return a task; resume() will poll it
        return httpx.Response(200, json=_task_response(task_id="t1"))

    def handle_task(req):
        return httpx.Response(200, json=_task_response(state="completed", task_id="t1"))

    transport = _RoutedTransport({
        "/v1/message:send": handle_send,
        "/v1/tasks/t1": handle_task,
    })
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        driver = ChatDriver(client, poll_interval=0.01)
        driver._card = _a2a_card()
        await driver.resume("t1", "ctx1", "answer")

    assert captured_body, "no POST to /v1/message:send"
    msg = captured_body[0]["message"]
    assert msg["taskId"] == "t1", f"expected taskId='t1', got {msg.get('taskId')!r}"
    assert msg["contextId"] == "ctx1", f"expected contextId='ctx1', got {msg.get('contextId')!r}"
    assert any(
        p.get("text") == "answer"
        for p in msg.get("parts", [])
    ), "reply text 'answer' not found in parts"


async def test_sc_e4_resume_returns_completed_task():
    """resume() returns the completed task dict."""

    def handle_send(req):
        # Return in-progress so resume() polls
        return httpx.Response(200, json=_task_response(state="working", task_id="t2"))

    def handle_task(req):
        return httpx.Response(200, json=_task_response(state="completed", task_id="t2"))

    transport = _RoutedTransport({
        "/v1/message:send": handle_send,
        "/v1/tasks/t2": handle_task,
    })
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        driver = ChatDriver(client, poll_interval=0.01)
        driver._card = _a2a_card()
        result = await driver.resume("t2", "ctx2", "done")

    assert result["id"] == "t2"
    assert result["status"]["state"] == "completed"


# ---------------------------------------------------------------------------
# SC-E5: A2AError error code constants
# ---------------------------------------------------------------------------


def test_sc_e5_error_code_constants_no_instance_needed():
    """A2AError class attributes must be accessible without instantiation."""
    assert A2AError.TASK_NOT_FOUND == -32001
    assert A2AError.TASK_NOT_CANCELABLE == -32002
    assert A2AError.PUSH_NOT_SUPPORTED == -32003
    assert A2AError.UNSUPPORTED_OP == -32004
    assert A2AError.CONTENT_TYPE_UNSUP == -32005
    assert A2AError.INVALID_AGENT_RESP == -32006
    assert A2AError.NOT_AUTHENTICATED == -32007


def test_sc_e5_error_code_instance_code_matches():
    """A2AError instance .code still works alongside class constants."""
    err = A2AError(A2AError.TASK_NOT_FOUND, "task not found")
    assert err.code == -32001
    assert err.code == A2AError.TASK_NOT_FOUND


def test_sc_e5_existing_raise_sites_unaffected():
    """A2AError can still be raised with None code (existing behavior)."""
    err = A2AError(None, "some error")
    assert err.code is None
    assert str(err) == "some error"


# ---------------------------------------------------------------------------
# L-9: agui_turn() body must include tools and context (RunAgentInput schema)
# ---------------------------------------------------------------------------


class _CapturingTransport:
    """httpx async transport that captures the first POST body then returns SSE."""

    def __init__(self, sse_body: bytes) -> None:
        self._sse_body = sse_body
        self.captured_body: dict | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            self.captured_body = json.loads(request.content)
        stream = httpx.ByteStream(self._sse_body)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=stream,
        )

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass


async def test_l9_agui_turn_body_includes_tools_and_context():
    """agui_turn() POST body must include 'tools' and 'context' (RunAgentInput schema)."""
    frames = [
        {"type": "RUN_STARTED", "runId": "r1", "threadId": "t1"},
        {"type": "TEXT_MESSAGE_START", "messageId": "m1"},
        {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "hi"},
        {"type": "TEXT_MESSAGE_END", "messageId": "m1"},
        {"type": "RUN_FINISHED", "outcome": {"type": "success"}},
    ]
    sse_body = sse_lines(frames)
    transport = _CapturingTransport(sse_body)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        driver = ChatDriver(client)
        await driver.agui_turn("hello", "thread-1", [])

    body = transport.captured_body
    assert body is not None, "no POST body was captured"
    assert "tools" in body, f"'tools' key missing from agui_turn() POST body: {list(body.keys())}"
    assert "context" in body, f"'context' key missing from agui_turn() POST body: {list(body.keys())}"
    assert body["tools"] == [], f"expected tools=[], got {body['tools']!r}"
    assert body["context"] == [], f"expected context=[], got {body['context']!r}"
