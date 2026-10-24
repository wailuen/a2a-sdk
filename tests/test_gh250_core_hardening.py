"""GH-250: depth-cap message, Graph webhook parser, boot store leak, shared
format-char drop, SafeValueError definition guard.

Ruling: https://github.com/wailuen/a2a-sdk/issues/250#issuecomment-6381441157
"""

from __future__ import annotations

import gc
import json
import logging
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from pydantic import BaseModel

from agent_sdk import BaseAgentSettings
from agent_sdk.app import Agent
from agent_sdk.common import json_strict
from agent_sdk.common.json_strict import loads_strict
from agent_sdk.common.redact import (
    drop_format_chars,
    safe_cell_text,
    safe_id_text,
    safe_line_text,
)
from agent_sdk.contrib.webhooks import WebhookDispatcher, build_graph_webhook_router
from agent_sdk.models.errors import SafeValueError
from agent_sdk.routes.mcp import _sse_queues
from agent_sdk.testing import FakeModelClient

from .test_ag_ui import run, run_body

DEEP = b"[" * 65 + b"]" * 65
VERY_DEEP = b"[" * 5000 + b"]" * 5000
TOO_DEEP = "nesting too deep"
SECRET = "ZZ-CLIENT-STATE-SECRET-ZZ"


# ── item 1: distinct fixed message ──


def test_loads_strict_deep_message_is_distinct_from_malformed() -> None:
    with pytest.raises(json.JSONDecodeError) as deep:
        loads_strict(DEEP)
    with pytest.raises(json.JSONDecodeError) as bad:
        loads_strict(b"{")
    assert deep.value.msg == TOO_DEEP
    assert bad.value.msg != TOO_DEEP
    assert isinstance(deep.value, json_strict.NestingTooDeep)
    assert not isinstance(bad.value, json_strict.NestingTooDeep)


def test_loads_strict_64_levels_still_parse() -> None:
    assert loads_strict(b"[" * 64 + b"]" * 64) is not None


def test_recursion_backstop_is_nesting_too_deep(monkeypatch) -> None:
    def boom(*a, **k):
        raise RecursionError("HOSTILE-MARKER")

    monkeypatch.setattr(json_strict.json, "loads", boom)
    with pytest.raises(json_strict.NestingTooDeep) as info:
        loads_strict(b"[]")
    assert "HOSTILE-MARKER" not in str(info.value)


@pytest.mark.parametrize("body", [DEEP, VERY_DEEP])
async def test_mcp_post_deep_body_message(client, body) -> None:
    r = await client.post("/mcp", content=body, headers={"content-type": "application/json"})
    err = r.json()["error"]
    assert err["code"] == -32700
    assert err["message"] == TOO_DEEP


async def test_mcp_post_malformed_keeps_parse_error(client) -> None:
    r = await client.post("/mcp", content=b"{", headers={"content-type": "application/json"})
    assert r.json()["error"] == {"code": -32700, "message": "parse error"}


async def test_mcp_messages_deep_body_message(client, app) -> None:
    import asyncio
    import uuid

    token = client.headers["authorization"].removeprefix("Bearer ")
    identity = app.state.auth.api_keys.verify(token)
    session_id = uuid.uuid4().hex
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=8)
    _sse_queues(app)[session_id] = (queue, f"{identity.kind}:{identity.subject}")
    try:
        r = await client.post(
            "/mcp/messages",
            params={"session_id": session_id},
            content=DEEP,
            headers={"content-type": "application/json"},
        )
        assert r.status_code == 202
        err = json.loads(queue.get_nowait())["error"]
        assert err == {"code": -32700, "message": TOO_DEEP}
    finally:
        _sse_queues(app).pop(session_id, None)


@pytest.mark.parametrize("body", [DEEP, VERY_DEEP])
async def test_a2a_deep_body_message(client, body) -> None:
    r = await client.post(
        "/v1/message:send", content=body, headers={"content-type": "application/json"}
    )
    assert r.status_code == 400
    err = r.json()["error"]
    assert err["code"] == -32700
    assert err["message"] == TOO_DEEP


async def test_a2a_malformed_keeps_text(client) -> None:
    r = await client.post(
        "/v1/message:send", content=b"{", headers={"content-type": "application/json"}
    )
    assert r.json()["error"]["message"] == "request body is not valid JSON"


@pytest.mark.parametrize("body", [DEEP, VERY_DEEP])
async def test_ag_ui_deep_body_message(client, body) -> None:
    r = await client.post(
        "/ag-ui/run", content=body, headers={"content-type": "application/json"}
    )
    assert r.status_code == 200
    assert "RUN_ERROR" in r.text
    assert TOO_DEEP in r.text
    assert "malformed RunAgentInput body" not in r.text


async def test_ag_ui_malformed_keeps_text(client) -> None:
    r = await client.post(
        "/ag-ui/run", content=b"{", headers={"content-type": "application/json"}
    )
    assert "malformed RunAgentInput body" in r.text
    assert TOO_DEEP not in r.text


# ── item 2: Graph webhook parser ──


def _webhook_app(got: list) -> tuple[FastAPI, WebhookDispatcher]:
    d = WebhookDispatcher(expected_client_state=SECRET)

    async def handler(n) -> None:
        got.append(n)

    d.on("default", handler)
    app = FastAPI()
    app.include_router(build_graph_webhook_router(d, path="/webhooks/graph"))
    return app, d


@pytest.mark.parametrize(
    "body",
    [VERY_DEEP, DEEP, b'{"value": NaN}', b'{"value": 1e999}', b"\xff\xfe"],
)
async def test_webhook_hostile_body_dropped_202(body) -> None:
    got: list = []
    app, d = _webhook_app(got)
    scheduled: list = []
    d.schedule = lambda payload: scheduled.append(payload)  # type: ignore[method-assign]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=True),
        base_url="http://test",
    ) as c:
        r = await c.post("/webhooks/graph", content=body)
    assert r.status_code == 202
    assert scheduled == []
    await d.aclose()


async def test_webhook_valid_body_still_scheduled() -> None:
    got: list = []
    app, d = _webhook_app(got)
    scheduled: list = []
    d.schedule = lambda payload: scheduled.append(payload)  # type: ignore[method-assign]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        r = await c.post("/webhooks/graph", json={"value": []})
    assert r.status_code == 202
    assert scheduled == [{"value": []}]
    await d.aclose()


def test_graph_router_reads_body_through_shared_helper() -> None:
    import inspect

    from agent_sdk.contrib.webhooks import graph

    src = inspect.getsource(graph)
    assert "read_capped_body" in src
    assert "request.stream()" not in src
    assert "json.loads(" not in src


# ── item 3: boot order and close-on-exception ──


def _agent(tmp_path: Path, **kw) -> Agent:
    kw.setdefault("persona", "p")
    return Agent(
        settings=BaseAgentSettings(
            DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="test-agent"
        ),
        model_client=FakeModelClient(),
        **kw,
    )


def _spy_store(monkeypatch) -> list:
    stores: list = []
    original = Agent._build_credential_store

    def spy(self):
        store = original(self)
        real_close = store.close
        state = {"closed": 0}

        def close() -> None:
            state["closed"] += 1
            real_close()

        store.close = close  # type: ignore[method-assign]
        stores.append(state)
        return store

    monkeypatch.setattr(Agent, "_build_credential_store", spy)
    return stores


def test_post_open_boot_error_closes_store(tmp_path, monkeypatch, caplog) -> None:
    stores = _spy_store(monkeypatch)
    agent = _agent(tmp_path, mcp_instructions="x" * 100_000)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(ValueError) as info:
            agent.build_app()
    assert len(stores) == 1 and stores[0]["closed"] == 1
    assert str(tmp_path) not in str(info.value)
    assert str(tmp_path) not in caplog.text
    gc.collect()


def test_boot_without_error_leaves_store_open(tmp_path, monkeypatch) -> None:
    stores = _spy_store(monkeypatch)
    app = _agent(tmp_path).build_app()
    assert len(stores) == 1 and stores[0]["closed"] == 0
    app.state.credential_store.close()
    gc.collect()


# ── items 4 and 5: shared format-char drop, definition guard ──

BIDI = "a‮b⁦c⁩d​e"


def test_drop_format_chars_removes_cf_only() -> None:
    assert drop_format_chars(BIDI) == "abcde"
    assert drop_format_chars("AAPL (1688214-U) = 1, 2:3") == "AAPL (1688214-U) = 1, 2:3"


@pytest.mark.parametrize("helper", [safe_line_text, safe_cell_text, safe_id_text])
def test_safe_helpers_drop_bidi(helper) -> None:
    assert helper(BIDI) == "abcde"


def test_safe_id_text_alphabet_stays_byte_exact() -> None:
    value = "urn:x-1_2.3~4!5@6=7+8/9,0 (ab)"
    assert safe_id_text(value) == value


def test_safe_value_error_hint_drops_bidi() -> None:
    from agent_sdk.agent.loop import safe_validation_message

    class Hint(SafeValueError):
        message = "Use‮ AAPL"

    from pydantic import field_validator

    class M(BaseModel):
        t: str

        @field_validator("t")
        @classmethod
        def _c(cls, v: str) -> str:
            raise Hint()

    with pytest.raises(Exception) as info:
        M.model_validate({"t": "x"})
    assert "Use AAPL" in safe_validation_message("t", info.value, M)  # type: ignore[arg-type]


@pytest.mark.parametrize("bad", ["\x07 ", "‮", "‮⁦ \x00", ""])
def test_unrenderable_message_fails_at_definition(bad) -> None:
    with pytest.raises(TypeError):

        class Bad(SafeValueError):
            message = bad


def test_inherited_message_is_accepted() -> None:
    class Base(SafeValueError):
        message = "Use AAPL"

    class Child(Base):
        pass

    assert Child.message == "Use AAPL"
