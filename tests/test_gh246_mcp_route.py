"""GH-246: MCP routes cap the body while reading, reject bad ids, share one pager.

Ruling: https://github.com/wailuen/a2a-sdk/issues/246#issuecomment-6381440418
"""

from __future__ import annotations

import asyncio
import gc
from typing import Any, AsyncIterator

import httpx
import pytest
from pydantic import BaseModel
from starlette.requests import Request

from agent_sdk import BaseAgentSettings
from agent_sdk.agent.registry import ToolSet
from agent_sdk.app import Agent
from agent_sdk.common.body import BodyTooLarge, read_capped_body
from agent_sdk.routes import mcp as mcp_route
from agent_sdk.testing import FakeModelClient

CALLS: list[str] = []
CHUNK = 1024 * 1024


class In(BaseModel):
    x: str = ""


@pytest.fixture
async def mcp_client(tmp_path) -> AsyncIterator[httpx.AsyncClient]:
    CALLS.clear()
    ts = ToolSet()

    @ts.tool(tier=1)
    async def ran(inp: In) -> str:
        """records that it ran"""
        CALLS.append("ran")
        return "ok"

    app = Agent(
        settings=BaseAgentSettings(
            DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent"
        ),
        model_client=FakeModelClient(),
        persona="p",
        toolsets=[ts],
    ).build_app()
    async with app.router.lifespan_context(app):
        _, token = app.state.auth.api_keys.mint("t", admin=True)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
            headers={"Authorization": f"Bearer {token}"},
        ) as c:
            c.app = app  # type: ignore[attr-defined]
            yield c
    app.state.credential_store.close()
    gc.collect()


def _scope_request(chunks: list[bytes], headers: list[tuple[bytes, bytes]]) -> tuple[Request, list[int]]:
    served = [0]
    queue = list(chunks)

    async def receive() -> dict[str, Any]:
        if queue:
            served[0] += 1
            return {"type": "http.request", "body": queue.pop(0), "more_body": bool(queue)}
        return {"type": "http.disconnect"}

    scope = {"type": "http", "method": "POST", "headers": headers, "path": "/"}
    return Request(scope, receive), served


async def test_helper_stops_once_cap_passed() -> None:
    req, served = _scope_request([b"x" * 10] * 50, [])
    with pytest.raises(BodyTooLarge):
        await read_capped_body(req, 25)
    assert served[0] <= 3


async def test_helper_refuses_declared_length_before_read() -> None:
    req, served = _scope_request([b"x"], [(b"content-length", b"999")])
    with pytest.raises(BodyTooLarge):
        await read_capped_body(req, 100)
    assert served[0] == 0


async def test_helper_returns_body_under_cap() -> None:
    req, _ = _scope_request([b"ab", b"cd"], [])
    assert await read_capped_body(req, 4) == b"abcd"


def _counting_stream(counter: list[int], n: int = 20):
    async def gen():
        for _ in range(n):
            counter[0] += 1
            yield b" " * CHUNK

    return gen()


@pytest.mark.parametrize("path", ["/mcp", "/mcp/messages?session_id=" + "a" * 32])
async def test_streamed_over_cap_body_not_fully_read(mcp_client, monkeypatch, path) -> None:
    monkeypatch.setattr(mcp_route, "_identity_key", lambda identity: "owner")
    mcp_route._sse_queues(mcp_client.app)["a" * 32] = (asyncio.Queue(maxsize=8), "owner")
    counter = [0]
    r = await mcp_client.post(
        path, content=_counting_stream(counter), headers={"content-type": "application/json"}
    )
    assert r.status_code == 413
    assert r.json() == {"error": "request body too large"}
    assert counter[0] < 20
    assert counter[0] <= 4


@pytest.mark.parametrize("path", ["/mcp", "/mcp/messages?session_id=" + "a" * 32])
async def test_declared_over_cap_length_refused_before_read(mcp_client, monkeypatch, path) -> None:
    monkeypatch.setattr(mcp_route, "_identity_key", lambda identity: "owner")
    mcp_route._sse_queues(mcp_client.app)["a" * 32] = (asyncio.Queue(maxsize=8), "owner")
    counter = [0]
    r = await mcp_client.post(
        path,
        content=_counting_stream(counter),
        headers={
            "content-type": "application/json",
            "content-length": str(mcp_route._MAX_BODY_BYTES + 1),
        },
    )
    assert r.status_code == 413
    assert counter[0] == 0


_BAD_IDS = [
    pytest.param({}, id="missing"),
    pytest.param({"id": None}, id="null"),
    pytest.param({"id": True}, id="bool"),
    pytest.param({"id": 1.5}, id="float"),
    pytest.param({"id": [1]}, id="list"),
    pytest.param({"id": {"a": 1}}, id="object"),
]


def _tool_call(extra: dict[str, Any]) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "tools/call",
        "params": {"name": "ran", "arguments": {}},
        **extra,
    }


@pytest.mark.parametrize("extra", _BAD_IDS)
async def test_post_bad_id_is_invalid_request_and_tool_not_run(mcp_client, extra) -> None:
    r = await mcp_client.post("/mcp", json=_tool_call(extra))
    assert r.status_code == 200
    body = r.json()
    assert body["id"] is None
    assert body["error"]["code"] == -32600
    assert CALLS == []


@pytest.mark.parametrize("ident", [7, "abc", 0])
async def test_post_good_id_still_runs(mcp_client, ident) -> None:
    r = await mcp_client.post("/mcp", json=_tool_call({"id": ident}))
    assert r.json()["id"] == ident
    assert CALLS == ["ran"]


async def test_post_notification_without_id_still_202(mcp_client) -> None:
    r = await mcp_client.post(
        "/mcp", json={"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert r.status_code == 202


async def _legacy(mcp_client, monkeypatch, message, headers=None):
    monkeypatch.setattr(mcp_route, "_identity_key", lambda identity: "owner")
    queue: asyncio.Queue = asyncio.Queue(maxsize=8)
    mcp_route._sse_queues(mcp_client.app)["b" * 32] = (queue, "owner")
    r = await mcp_client.post(
        "/mcp/messages?session_id=" + "b" * 32, json=message, headers=headers or {}
    )
    return r, queue


@pytest.mark.parametrize("extra", _BAD_IDS)
async def test_messages_bad_id_is_invalid_request_and_tool_not_run(
    mcp_client, monkeypatch, extra
) -> None:
    r, queue = await _legacy(mcp_client, monkeypatch, _tool_call(extra))
    assert r.status_code == 202
    sent = queue.get_nowait()
    assert '"id":null' in sent.replace(" ", "")
    assert "-32600" in sent
    assert CALLS == []


async def test_messages_rejects_wrong_content_type(mcp_client, monkeypatch) -> None:
    monkeypatch.setattr(mcp_route, "_identity_key", lambda identity: "owner")
    mcp_route._sse_queues(mcp_client.app)["b" * 32] = (asyncio.Queue(maxsize=8), "owner")
    r = await mcp_client.post(
        "/mcp/messages?session_id=" + "b" * 32,
        content=b"{}",
        headers={"content-type": "text/plain"},
    )
    assert r.status_code == 415


async def test_content_type_compare_is_case_insensitive(mcp_client, monkeypatch) -> None:
    r = await mcp_client.post(
        "/mcp",
        content=b'{"jsonrpc":"2.0","id":1,"method":"ping"}',
        headers={"content-type": "Application/JSON; charset=utf-8"},
    )
    assert r.status_code == 200
    r2, _ = await _legacy(
        mcp_client,
        monkeypatch,
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"content-type": "APPLICATION/JSON"},
    )
    assert r2.status_code == 202


async def test_messages_jsonrpc_response_is_acked_not_dispatched(
    mcp_client, monkeypatch
) -> None:
    seen: list[Any] = []

    async def spy(app, message):
        seen.append(message)
        return None

    monkeypatch.setattr(mcp_route, "_dispatch", spy)
    r, queue = await _legacy(mcp_client, monkeypatch, {"jsonrpc": "2.0", "id": 3, "result": {}})
    assert r.status_code == 202
    assert seen == []
    assert queue.empty()


async def test_messages_queue_full_is_json_503(mcp_client, monkeypatch) -> None:
    monkeypatch.setattr(mcp_route, "_identity_key", lambda identity: "owner")
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    queue.put_nowait("full")
    mcp_route._sse_queues(mcp_client.app)["b" * 32] = (queue, "owner")
    r = await mcp_client.post(
        "/mcp/messages?session_id=" + "b" * 32,
        json={"jsonrpc": "2.0", "id": 1, "method": "ping"},
    )
    assert r.status_code == 503
    assert r.json() == {"error": "session queue full"}


def test_one_shared_pager_for_tools_and_prompts() -> None:
    page, nxt = mcp_route._page(list(range(70)), None)
    assert page == list(range(64))
    assert nxt == mcp_route._encode_cursor(64)
    page, nxt = mcp_route._page(list(range(70)), nxt)
    assert page == list(range(64, 70))
    assert nxt is None
    with pytest.raises(mcp_route._InvalidCursor):
        mcp_route._page([1], "!!!")


_NULL_ID_ERRORS = [
    pytest.param(
        {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "x"}}, id="null-id"
    ),
    pytest.param({"jsonrpc": "2.0", "error": {"code": -32700, "message": "x"}}, id="no-id"),
]


@pytest.mark.parametrize("message", _NULL_ID_ERRORS)
async def test_post_error_response_without_id_is_202_empty(mcp_client, message) -> None:
    r = await mcp_client.post("/mcp", json=message)
    assert r.status_code == 202
    assert r.content == b""


@pytest.mark.parametrize("message", _NULL_ID_ERRORS)
async def test_messages_error_response_without_id_acked_not_queued(
    mcp_client, monkeypatch, message
) -> None:
    r, queue = await _legacy(mcp_client, monkeypatch, message)
    assert r.status_code == 202
    assert queue.empty()


@pytest.mark.parametrize("bad_id", [{"a": 1}, 1.5, True, [1]])
async def test_missing_method_does_not_echo_invalid_id(bad_id):
    from agent_sdk.routes.mcp import _dispatch

    resp = await _dispatch(None, {"jsonrpc": "2.0", "id": bad_id})
    assert resp is not None and resp["id"] is None
    assert resp["error"]["code"] == -32600
