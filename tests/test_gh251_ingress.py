"""GH-251: one JSON media-type check, cap tests, strict tool JSON, credential header.

Ruling: https://github.com/wailuen/a2a-sdk/issues/251#issuecomment-6393088850
"""

from __future__ import annotations

import base64
import json
import logging
from typing import Any, AsyncIterator

import httpx
import pytest
from starlette.requests import Request

from agent_sdk import BaseAgentSettings
from agent_sdk.agent.registry import ToolSet
from agent_sdk.app import Agent
from agent_sdk.common.body import BodyTooLarge, is_json_content_type, read_capped_body
from agent_sdk.common.redact import safe_block_text
from agent_sdk.credentials import forwarding
import asyncio

from agent_sdk.routes import ag_ui as ag_ui_route
from agent_sdk.routes import mcp as mcp_route
from agent_sdk.testing import FakeModelClient


@pytest.fixture
async def client(tmp_path) -> AsyncIterator[httpx.AsyncClient]:
    app = Agent(
        settings=BaseAgentSettings(
            DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent"
        ),
        model_client=FakeModelClient(),
        persona="p",
        toolsets=[ToolSet()],
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


@pytest.mark.parametrize(
    "ct",
    ["application/json", "Application/JSON", "application/json; charset=utf-8",
     "application/problem+json", "APPLICATION/Problem+JSON; x=y"],
)
def test_json_content_types_accepted(ct: str) -> None:
    assert is_json_content_type(ct)


@pytest.mark.parametrize(
    "ct",
    ["application/json-seq", "*/*", "application/*", "text", "text/plain", "", "+json",
     "application/jsonx", "*/*+json"],
)
def test_other_content_types_refused(ct: str) -> None:
    assert not is_json_content_type(ct)


ROUTES = [
    ("/v1/message:send", {"message": {"role": "user", "parts": [{"text": "hi"}]}}),
    ("/ag-ui/run", {"messages": [{"role": "user", "content": "hi"}]}),
    ("/mcp", {"jsonrpc": "2.0", "id": 1, "method": "ping"}),
    ("/mcp/messages?session_id=" + "a" * 32, {"jsonrpc": "2.0", "id": 1, "method": "ping"}),
]


@pytest.mark.parametrize("path,body", ROUTES)
@pytest.mark.parametrize("ct", ["application/json-seq", "*/*", "application/*", "text"])
async def test_route_refuses_non_json(client, monkeypatch, path, body, ct) -> None:
    monkeypatch.setattr(mcp_route, "_identity_key", lambda identity: "owner")
    mcp_route._sse_queues(client.app)["a" * 32] = (asyncio.Queue(maxsize=8), "owner")
    r = await client.post(path, content=json.dumps(body), headers={"Content-Type": ct})
    assert r.status_code == 415


@pytest.mark.parametrize("path,body", ROUTES)
@pytest.mark.parametrize("ct", ["Application/JSON", "application/problem+json"])
async def test_route_accepts_json_variants(client, monkeypatch, path, body, ct) -> None:
    monkeypatch.setattr(mcp_route, "_identity_key", lambda identity: "owner")
    mcp_route._sse_queues(client.app)["a" * 32] = (asyncio.Queue(maxsize=8), "owner")
    r = await client.post(path, content=json.dumps(body), headers={"Content-Type": ct})
    assert r.status_code != 415


async def test_send_over_cap_body(client) -> None:
    big = b" " * (1024 * 1024 + 1)
    r = await client.post(
        "/v1/message:send", content=big, headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 400
    assert "too large" in r.text


async def test_ag_ui_over_cap_body(client) -> None:
    big = b" " * (1024 * 1024 + 1)
    r = await client.post(
        "/ag-ui/run", content=big, headers={"Content-Type": "application/json"}
    )
    assert r.status_code == 413


def _request(headers: list[tuple[bytes, bytes]], chunks: list[bytes]) -> Request:
    queue = [
        {"type": "http.request", "body": c, "more_body": i < len(chunks) - 1}
        for i, c in enumerate(chunks)
    ]

    async def receive() -> dict[str, Any]:
        return queue.pop(0)

    return Request(
        {"type": "http", "method": "POST", "headers": headers, "path": "/"}, receive
    )


async def test_read_capped_body_non_numeric_length() -> None:
    req = _request([(b"content-length", b"abc")], [b"x" * 10, b"y" * 10])
    assert await read_capped_body(req, 100) == b"x" * 10 + b"y" * 10
    req = _request([(b"content-length", b"abc")], [b"x" * 60, b"y" * 60])
    with pytest.raises(BodyTooLarge):
        await read_capped_body(req, 100)


async def test_read_capped_body_lying_length() -> None:
    req = _request([(b"content-length", b"5")], [b"x" * 60, b"y" * 60])
    with pytest.raises(BodyTooLarge):
        await read_capped_body(req, 100)


def test_tool_json_replaces_nan_per_value() -> None:
    out = ag_ui_route._tool_json({"a": float("nan"), "b": 1, "c": [float("inf"), 2]}, "{}")
    assert json.loads(out) == {"a": None, "b": 1, "c": [None, 2]}


def test_tool_json_catches_any_exception_and_logs_type_once(caplog) -> None:
    class Boom:
        def __str__(self) -> str:
            raise RuntimeError("secret-payload")

    with caplog.at_level(logging.WARNING, logger="agent_sdk.ag_ui"):
        out = ag_ui_route._tool_json(Boom(), "FALLBACK")
    assert out == "FALLBACK"
    records = [r for r in caplog.records if r.name == "agent_sdk.ag_ui"]
    assert len(records) == 1
    assert "RuntimeError" in records[0].getMessage()
    assert "secret-payload" not in caplog.text


def test_safe_block_text_drops_format_chars_keeps_newlines() -> None:
    assert safe_block_text("a‮b​c\nd\te") == "abc\nd\te"


def _header(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def test_header_valid_still_parses() -> None:
    h = _header(b'{"src": {"api_key": "v"}}')
    assert forwarding.parse_header(h) == {"src": {"api_key": "v"}}


@pytest.mark.parametrize(
    "raw",
    [
        b'{"src": {"api_key": NaN}}',
        b'{"src": {"api_key": "a", "api_key": "b"}}',
        b'{"src": {"api_key": "a"}, "src": {"api_key": "b"}}',
        b'{"src": {"n": 1e999}}',
    ],
)
def test_header_nan_or_duplicate_key_fails_closed(raw: bytes, caplog) -> None:
    with caplog.at_level(logging.DEBUG):
        assert forwarding.parse_header(_header(raw)) == {}
    assert "api_key" not in caplog.text
