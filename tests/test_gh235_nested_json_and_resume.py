"""GH-247 (follow-up to GH-235): AG-UI resume validation and strict tool JSON."""

from __future__ import annotations

import asyncio
import json
import uuid

import httpx
import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.events import ToolCallEvent, ToolResultEvent
from agent_sdk.agent.runner import new_task
from agent_sdk.auth.identity import Identity
from agent_sdk.common import json_strict
from agent_sdk.common.json_strict import loads_strict
from agent_sdk.routes import a2a as a2a_module
from agent_sdk.routes.mcp import _sse_queues
from agent_sdk.routes.ag_ui import _RESULT_FALLBACK, _RunMapper
from agent_sdk.testing import reply, tool_call

from .conftest import sse_frames
from .test_ag_ui import run, run_body
from .test_rt001_r6_ag_ui_slot_binding import _cancel, _hold

MARKER = "HOSTILE-MARKER-7f3a"


def _errors(frames: list[dict]) -> list[dict]:
    return [f for f in frames if f["type"] == "RUN_ERROR"]


def _mapper() -> _RunMapper:
    return _RunMapper("t1", "r1", A2uiCapabilities.from_metadata(None))


@pytest.mark.parametrize("resume", [{"interruptId": MARKER}, MARKER, 5, True])
async def test_non_list_resume_is_run_error(client, resume):
    frames = await run(client, run_body(resume=resume))
    errs = _errors(frames)
    assert len(errs) == 1
    assert errs[0]["message"] == "invalid resume entry"
    assert errs[0]["code"] == "validation"
    assert MARKER not in str(frames)


async def test_null_resume_is_a_fresh_run(client, fake_model):
    fake_model.script(reply("hi"))
    frames = await run(client, run_body(resume=None))
    assert not _errors(frames)


@pytest.mark.parametrize("status", ["banana", 5, {"x": MARKER}, []])
async def test_bad_status_is_run_error_before_lookup(client, app, status):
    store = app.state.task_store
    record = store.create(new_task(), Identity(kind="api_key", subject="o"))
    store.mark_interrupted(record.task.id, "gh235-int")
    frames = await run(
        client,
        run_body(resume=[{"interruptId": "gh235-int", "status": status, "payload": {}}]),
    )
    errs = _errors(frames)
    assert len(errs) == 1
    assert errs[0]["message"] == "invalid resume entry"
    assert errs[0]["code"] == "validation"
    assert MARKER not in str(frames)
    assert store.find_interrupt("gh235-int", Identity(kind="api_key", subject="o")) is not None


def _capture_resume(app, monkeypatch) -> list:
    store = app.state.task_store
    published: list = []
    real = store.deliver_resume

    def spy(task_id, envelope):
        published.append(envelope.value)
        return real(task_id, envelope)

    monkeypatch.setattr(store, "deliver_resume", spy)
    return published


@pytest.mark.parametrize("entry_status", ["absent", None])
async def test_missing_or_null_status_is_delivered_as_none(
    client, app, fake_model, monkeypatch, entry_status
):
    fake_model.script(tool_call("publish_note", {"note": "n"}), reply("after"))
    frames = await run(client, run_body("publish"))
    intr = frames[-1]["outcome"]["interrupts"][0]
    published = _capture_resume(app, monkeypatch)
    entry = {"interruptId": intr["id"], "payload": {"decision": "approved"}}
    if entry_status != "absent":
        entry["status"] = entry_status
    frames = await run(client, run_body(resume=[entry]))
    assert not _errors(frames)
    assert frames[-1]["type"] == "RUN_FINISHED"
    assert published == [{"status": None, "payload": {"decision": "approved"}}]


async def test_two_entry_resume_at_cap_is_run_error_not_429(client, app, monkeypatch):
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_TASK", 1)
    store = app.state.task_store
    record = store.create(new_task(), Identity(kind="api_key", subject="gh235-owner"))
    store.mark_interrupted(record.task.id, "gh235-cap")
    held = asyncio.create_task(client.post(f"/v1/tasks/{record.task.id}:subscribe"))
    try:
        await _hold(held)
        r = await asyncio.wait_for(
            client.post(
                "/ag-ui/run",
                json=run_body(
                    resume=[
                        {"interruptId": "gh235-cap", "status": "resolved"},
                        {"interruptId": "other", "status": "resolved"},
                    ]
                ),
            ),
            timeout=5,
        )
        assert r.status_code == 200, r.text
        errs = _errors(sse_frames(r.text))
        assert len(errs) == 1 and errs[0]["message"] == "invalid resume entry"
    finally:
        await _cancel(held)


async def test_two_entry_resume_below_cap_is_run_error(client, app):
    store = app.state.task_store
    record = store.create(new_task(), Identity(kind="api_key", subject="gh235-owner"))
    store.mark_interrupted(record.task.id, "gh235-below")
    frames = await run(
        client,
        run_body(
            resume=[
                {"interruptId": "gh235-below", "status": "resolved"},
                {"interruptId": "other", "status": "resolved"},
            ]
        ),
    )
    errs = _errors(frames)
    assert len(errs) == 1 and errs[0]["message"] == "invalid resume entry"
    assert MARKER not in str(frames)


async def test_bad_status_resume_at_cap_is_run_error_not_429(client, app, monkeypatch):
    monkeypatch.setattr(a2a_module, "_MAX_A2A_STREAMS_PER_TASK", 1)
    store = app.state.task_store
    record = store.create(new_task(), Identity(kind="api_key", subject="gh235-owner"))
    store.mark_interrupted(record.task.id, "gh235-cap-status")
    held = asyncio.create_task(client.post(f"/v1/tasks/{record.task.id}:subscribe"))
    try:
        await _hold(held)
        r = await asyncio.wait_for(
            client.post(
                "/ag-ui/run",
                json=run_body(resume=[{"interruptId": "gh235-cap-status", "status": "banana"}]),
            ),
            timeout=5,
        )
        assert r.status_code == 200, r.text
        errs = _errors(sse_frames(r.text))
        assert len(errs) == 1 and errs[0]["message"] == "invalid resume entry"
    finally:
        await _cancel(held)


def test_tool_call_args_with_nan_become_null():
    frames = _mapper().map(
        ToolCallEvent(tool_call_id="c1", tool_name="t", arguments={"x": float("nan")})
    )
    delta = next(f for f in frames if f["type"] == "TOOL_CALL_ARGS")["delta"]
    assert delta == '{"x":null}'
    assert "NaN" not in str(frames)


def test_tool_result_with_inf_becomes_null():
    m = _mapper()
    m.map(ToolCallEvent(tool_call_id="c1", tool_name="t", arguments={}))
    frames = m.map(
        ToolResultEvent(tool_call_id="c1", tool_name="t", ok=True, result={"x": float("inf")})
    )
    content = next(f for f in frames if f["type"] == "TOOL_CALL_RESULT")["content"]
    assert "Infinity" not in content and "inf" not in content.lower().replace("information", "")
    assert content == '{"x":null}'


def test_tool_json_serializer_failure_uses_fixed_fallback(monkeypatch):
    from agent_sdk.routes import ag_ui

    def boom(*a, **k):
        raise ValueError("x")

    monkeypatch.setattr(ag_ui, "to_jsonable_python", boom)
    assert ag_ui._tool_json({"x": 1}, _RESULT_FALLBACK) == _RESULT_FALLBACK


def test_tool_result_with_native_types_still_serializes():
    import datetime
    import decimal

    m = _mapper()
    m.map(ToolCallEvent(tool_call_id="c1", tool_name="t", arguments={}))
    result = {"when": datetime.date(2026, 1, 2), "amt": decimal.Decimal("1.5"), "id": uuid.uuid4()}
    frames = m.map(ToolResultEvent(tool_call_id="c1", tool_name="t", ok=True, result=result))
    content = next(f for f in frames if f["type"] == "TOOL_CALL_RESULT")["content"]
    assert content != "tool result not serializable"
    assert "2026-01-02" in content


def test_tool_result_str_with_lone_surrogate_is_scrubbed():
    # v0.22.0 release gate: an unencodable str result ended the whole run.
    from agent_sdk.common.json_strict import dumps_strict

    m = _mapper()
    m.map(ToolCallEvent(tool_call_id="c1", tool_name="t", arguments={}))
    frames = m.map(ToolResultEvent(tool_call_id="c1", tool_name="t", ok=True, result="a\ud83db"))
    content = next(f for f in frames if f["type"] == "TOOL_CALL_RESULT")["content"]
    assert content == "a\ufffdb"
    dumps_strict(frames)


def test_tool_result_model_dump_failure_uses_fallback():
    from pydantic import BaseModel, field_serializer

    class Bad(BaseModel):
        x: int = 1

        @field_serializer("x")
        def _boom(self, v):
            raise RuntimeError("boom")

    m = _mapper()
    m.map(ToolCallEvent(tool_call_id="c1", tool_name="t", arguments={}))
    frames = m.map(ToolResultEvent(tool_call_id="c1", tool_name="t", ok=True, result=Bad()))
    content = next(f for f in frames if f["type"] == "TOOL_CALL_RESULT")["content"]
    assert content == "tool result not serializable"


# Nested bodies go through the real parser (no interpreter shim): 65 to 255
# levels is valid JSON past the 64-level cap; 5000 also covers the interpreter's
# own RecursionError on versions that raise it.
JSON_HEADERS = {"content-type": "application/json"}
DEPTHS = [65, 100, 255, 5000]
TOO_DEEP = "nesting too deep"


def nested(depth: int, *, objects: bool = False) -> bytes:
    if objects:
        return ('{"a":' * depth + f'"{MARKER}"' + "}" * depth).encode()
    return ("[" * depth + f'"{MARKER}"' + "]" * depth).encode()


@pytest.mark.parametrize("objects", [False, True])
@pytest.mark.parametrize("depth", DEPTHS)
def test_loads_strict_nested_is_too_deep(depth, objects):
    with pytest.raises(json.JSONDecodeError) as ei:
        loads_strict(nested(depth, objects=objects))
    assert ei.value.msg == TOO_DEEP
    assert MARKER not in str(ei.value)


def test_loads_strict_recursion_error_is_mapped_without_echo(monkeypatch):
    def boom(*args, **kwargs):
        raise RecursionError(f"maximum recursion depth exceeded {MARKER}")

    monkeypatch.setattr(json_strict.json, "loads", boom)
    with pytest.raises(json.JSONDecodeError) as ei:
        loads_strict(b"[]")
    assert ei.value.msg == TOO_DEEP
    assert MARKER not in str(ei.value) and MARKER not in repr(ei.value)


@pytest.mark.parametrize("depth", DEPTHS)
async def test_mcp_post_nested_is_too_deep(client, depth):
    r = await client.post("/mcp", content=nested(depth), headers=JSON_HEADERS)
    assert r.status_code == 200, r.text
    assert r.json()["error"] == {"code": -32700, "message": TOO_DEEP}
    assert MARKER not in r.text


@pytest.mark.parametrize("depth", DEPTHS)
async def test_mcp_messages_nested_is_too_deep(client, app, depth):
    bearer = client.headers["authorization"].removeprefix("Bearer ")
    identity = app.state.auth.api_keys.verify(bearer)
    session_id = uuid.uuid4().hex
    queue: asyncio.Queue[str] = asyncio.Queue(maxsize=8)
    _sse_queues(app)[session_id] = (queue, f"{identity.kind}:{identity.subject}")
    try:
        r = await client.post(
            "/mcp/messages",
            params={"session_id": session_id},
            content=nested(depth),
            headers=JSON_HEADERS,
        )
        assert r.status_code == 202, r.text
        queued = queue.get_nowait()
        assert json.loads(queued)["error"] == {"code": -32700, "message": TOO_DEEP}
        assert MARKER not in queued
    finally:
        _sse_queues(app).pop(session_id, None)


@pytest.mark.parametrize("depth", DEPTHS)
async def test_a2a_message_send_nested_is_too_deep(client, depth):
    r = await client.post("/v1/message:send", content=nested(depth), headers=JSON_HEADERS)
    assert r.status_code == 400, r.text
    assert r.json()["error"] == {"code": -32700, "message": TOO_DEEP}
    assert MARKER not in r.text


@pytest.mark.parametrize("depth", DEPTHS)
async def test_ag_ui_run_nested_is_too_deep(client, depth):
    r = await client.post("/ag-ui/run", content=nested(depth), headers=JSON_HEADERS)
    assert r.status_code == 200, r.text
    errors = _errors(sse_frames(r.text))
    assert len(errors) == 1
    assert errors[0]["message"] == TOO_DEEP
    assert MARKER not in r.text


@pytest.mark.parametrize("objects", [False, True])
async def test_oauth_register_nested_is_invalid_client_metadata(client, objects):
    body = nested(2000, objects=objects)
    assert len(body) < 16 * 1024
    r = await client.post("/oauth/register", content=body, headers=JSON_HEADERS)
    assert r.status_code == 400, r.text
    assert r.json() == {
        "error": "invalid_client_metadata",
        "error_description": "request body must be valid JSON",
    }
    assert MARKER not in r.text


@pytest.mark.parametrize("objects", [False, True])
async def test_a2a_deep_metadata_never_breaks_task_list(client, objects):
    open_, close = ('{"a":', "}") if objects else ("[", "]")
    body = ('{"message":{"metadata":' + open_ * 300 + "1" * objects + close * 300 + "}}").encode()
    r = await client.post("/v1/message:send", content=body, headers=JSON_HEADERS)
    assert r.status_code == 400, r.text
    assert (await client.get("/v1/tasks")).status_code != 500
