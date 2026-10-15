"""RT-001 (w050 round 4, fresh-lens): a string that cannot be encoded as
UTF-8 must never reach a writer's ``.encode()``.

Root cause: ``dumps_strict`` uses ``ensure_ascii=False``, so a lone surrogate
(``json.loads('"a\\ud800b"')``, common when an upstream API cuts an emoji in
half) was copied into its output as-is. Every writability check
(``_is_writable`` in routes/mcp.py) passed, and the legacy MCP SSE generator
then raised ``UnicodeEncodeError`` mid-stream, killing the session with no
reply. Streamable HTTP's ``JSONResponse`` had the same gap (HTTP 500).

Fix at the root: ``dumps_strict`` itself raises a fixed-text ``ValueError``
when its output is not UTF-8-encodable, so every caller's existing
``except ValueError`` branch handles it (isError / -32603 / -32006 /
RUN_ERROR), and the error text never echoes the character (SI-2).
"""

from __future__ import annotations

import json

import pytest

from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.common.json_strict import dumps_strict
from agent_sdk.common.sse import sse_data
from agent_sdk.models.content_types import BarChart, BarItem
from agent_sdk.routes import a2a as a2a_route
from agent_sdk.routes import mcp as mcp_route

from tests.test_gh173_mcp_non_finite_output import (
    _call,
    _legacy_post,
    _legacy_session_for,
    _mcp_init,
)

LONE = json.loads('"a\\ud800b"')  # str with an unpaired high surrogate

_tools = ToolSet()


@_tools.tool(tier=1, emits=BarChart, read_only=True)
async def cut_emoji_bars() -> BarChart:
    """Returns a bar chart whose label holds a lone surrogate."""
    return BarChart.model_construct(
        bars=[BarItem.model_construct(category=LONE, value=1.0)]
    )


def _use_tools(client) -> None:
    client.app.state.registry = ToolRegistry([_tools], {})


# ── the shared serializer ──


def test_dumps_strict_rejects_lone_surrogate_with_fixed_text():
    with pytest.raises(ValueError) as exc:
        dumps_strict({"x": LONE})
    assert not isinstance(exc.value, UnicodeEncodeError)  # fixed text, no echo
    assert str(exc.value) == "string not encodable as UTF-8"
    assert "\ud800" not in str(exc.value)


def test_dumps_strict_rejects_lone_surrogate_in_key():
    with pytest.raises(ValueError):
        dumps_strict({LONE: 1})


def test_dumps_strict_output_is_always_utf8_encodable():
    text = dumps_strict({"emoji": "\U0001f600", "cjk": "中", "n": 1.5})
    assert text.encode("utf-8")  # never raises
    assert json.loads(text) == {"emoji": "\U0001f600", "cjk": "中", "n": 1.5}


def test_is_writable_false_for_lone_surrogate():
    assert mcp_route._is_writable({"x": LONE}) is False
    assert mcp_route._is_writable({"x": "fine \U0001f600"}) is True


def test_sse_data_raises_value_error_not_unicode_crash_later():
    with pytest.raises(ValueError) as exc:
        sse_data({"type": "TEXT_MESSAGE_CONTENT", "delta": LONE})
    assert "\ud800" not in str(exc.value)


def test_a2a_strict_json_response_replaces_lone_surrogate():
    """w050 RT-001 (round 6): a non-stream A2A answer (e.g. tasks/get on a
    record stored before the status-commit scrub) replaces the character
    with U+FFFD instead of failing every read of the task."""
    resp = a2a_route._strict_json_response({"text": LONE})
    assert resp.status_code == 200
    resp.body.decode("utf-8")  # valid UTF-8
    assert json.loads(resp.body) == {"text": "a\ufffdb"}


def test_a2a_strict_json_response_non_finite_still_fixed_error():
    resp = a2a_route._strict_json_response({"text": LONE, "x": float("nan")})
    body = json.loads(resp.body)
    assert resp.status_code == 502
    assert body["error"]["code"] == -32006
    assert body["error"]["message"] == "invalid agent response"
    assert b"\\ud800" not in resp.body


# ── MCP legacy HTTP+SSE transport (the reported crash) ──


async def test_legacy_tools_call_lone_surrogate_replies_is_error(client):
    _use_tools(client)
    sid, queue = await _legacy_session_for(client)
    r = await _legacy_post(client, sid, _call("cut_emoji_bars", rid=21))
    assert r.status_code == 202, r.text
    assert queue.qsize() == 1
    raw = queue.get_nowait()
    # the SSE generator does f"...data: {payload}".encode(): must not raise
    raw.encode("utf-8")
    body = json.loads(raw)
    assert body["id"] == 21
    assert body["result"]["isError"] is True
    assert body["result"]["content"] == [
        {"type": "text", "text": "tool output not serializable"}
    ]


async def test_legacy_unwritable_response_with_lone_surrogate_is_internal_error(
    client, monkeypatch
):
    sid, queue = await _legacy_session_for(client)

    async def bad_dispatch(app, message):
        return {"jsonrpc": "2.0", "id": message.get("id"), "result": {"x": LONE}}

    monkeypatch.setattr(mcp_route, "_dispatch", bad_dispatch)
    r = await _legacy_post(client, sid, {"jsonrpc": "2.0", "id": 22, "method": "tools/list"})
    assert r.status_code == 202, r.text
    raw = queue.get_nowait()
    raw.encode("utf-8")
    assert json.loads(raw) == {
        "jsonrpc": "2.0", "id": 22, "error": {"code": -32603, "message": "internal error"}
    }


async def test_legacy_lone_surrogate_request_id_is_nulled(client, monkeypatch):
    sid, queue = await _legacy_session_for(client)

    async def bad_dispatch(app, message):
        return {"jsonrpc": "2.0", "id": LONE, "result": {}}

    monkeypatch.setattr(mcp_route, "_dispatch", bad_dispatch)
    r = await _legacy_post(client, sid, {"jsonrpc": "2.0", "id": 23, "method": "tools/list"})
    assert r.status_code == 202, r.text
    raw = queue.get_nowait()
    raw.encode("utf-8")
    assert json.loads(raw)["id"] is None


# ── MCP Streamable HTTP transport (same gap: was a bare HTTP 500) ──


async def test_streamable_tools_call_lone_surrogate_is_is_error_not_500(client):
    _use_tools(client)
    headers = await _mcp_init(client)
    r = await client.post("/mcp", json=_call("cut_emoji_bars", rid=24), headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == 24
    assert body["result"]["isError"] is True
    assert "structuredContent" not in body["result"]
