"""w050 round 5 (fresh-lens): a string no writer can encode must never be
STORED in a task.

Root cause: the "must encode as UTF-8" rule lived only in the outbound
writer (``dumps_strict``). The two places that admit strings into stored
task state did not apply it:

* ingress — ``loads_strict`` decoded ``"\\ud800"`` escapes into lone
  surrogates, so a client message created a task that no later read could
  serialize (GET /v1/tasks/{id} and GET /v1/tasks both 502), and an AG-UI
  ``threadId`` crashed the RUN_STARTED write with no terminal frame;
* the artifact commit gate — ``build_artifact`` checked with plain
  ``json.dumps``, so a tool result holding a lone surrogate committed the
  task COMPLETED while the stream sent a FAILED tail.

Both now refuse the value BEFORE any task, stream or worker exists (ingress)
or before COMPLETED (artifact gate).
"""

from __future__ import annotations

import json
import uuid
from typing import Any

import pytest

from agent_sdk.agent.registry import ToolRegistry, ToolSet
from agent_sdk.common.json_strict import loads_strict
from agent_sdk.models.content_types import BarChart, BarItem
from agent_sdk.testing import reply, tool_call

from tests.conftest import sse_frames, wait_for_state
from tests.test_gh173_mcp_non_finite_output import _mcp_init

LONE = json.loads('"a\\ud800b"')
ESCAPED_LONE = "a\\ud800b"  # the JSON text a client sends

_tools = ToolSet()


@_tools.tool(tier=1, emits=BarChart, read_only=True)
async def cut_emoji_chart() -> BarChart:
    """Returns a bar chart whose label holds a lone surrogate."""
    return BarChart.model_construct(
        bars=[BarItem.model_construct(category=LONE, value=1.0)]
    )


def _raw(text: str) -> bytes:
    return text.encode("utf-8")


def _a2a_body(text_json: str, *, message_id: str | None = None, context_id: str | None = None) -> bytes:
    mid = message_id if message_id is not None else f'"{uuid.uuid4().hex}"'
    ctx = f',"contextId":{context_id}' if context_id is not None else ""
    return _raw(
        '{"message":{"role":"user","parts":[{"kind":"text","text":%s}],'
        '"messageId":%s%s}}' % (text_json, mid, ctx)
    )


# ── the shared parser ──


@pytest.mark.parametrize(
    "raw",
    [
        '"\\ud800"',
        '"a\\udc00b"',
        '{"\\ud800": 1}',
        '[["ok", "\\udbff"]]',
        '"\\ud800\\u0041"',  # high followed by a non-low escape
    ],
)
def test_loads_strict_rejects_lone_surrogate_escapes(raw):
    with pytest.raises(json.JSONDecodeError) as exc:
        loads_strict(raw)
    assert "\\ud" not in str(exc.value).lower()  # SI-2: no echo
    with pytest.raises(json.JSONDecodeError):
        loads_strict(raw.encode("utf-8"))


def test_loads_strict_rejects_raw_encoded_surrogate_bytes():
    # json.loads(bytes) decodes with 'surrogatepass', so ED A0 80 is a lone
    # surrogate too, not a decode error.
    with pytest.raises(json.JSONDecodeError):
        loads_strict(b'"\xed\xa0\x80"')


def test_loads_strict_keeps_paired_surrogates_and_plain_text():
    assert loads_strict('"\\ud83d\\ude00"') == "\U0001f600"
    assert loads_strict('{"k": ["\\\\ud800", "中"]}') == {"k": ["\\ud800", "中"]}


# ── A2A ingress: refused before any task exists ──


@pytest.mark.parametrize(
    "body",
    [
        _a2a_body(f'"{ESCAPED_LONE}"'),
        _a2a_body('"hi"', message_id=f'"{ESCAPED_LONE}"'),
        _a2a_body('"hi"', context_id=f'"{ESCAPED_LONE}"'),
    ],
    ids=["text", "messageId", "contextId"],
)
async def test_a2a_message_send_refuses_lone_surrogate(client, body):
    r = await client.post(
        "/v1/message:send", content=body, headers={"content-type": "application/json"}
    )
    assert r.status_code == 400, r.text
    assert r.json()["error"]["code"] == -32700
    lst = await client.get("/v1/tasks")
    assert lst.status_code == 200, lst.text
    assert lst.json()["tasks"] == []  # no task was created


async def test_a2a_message_stream_refuses_lone_surrogate(client):
    r = await client.post(
        "/v1/message:stream",
        content=_a2a_body(f'"{ESCAPED_LONE}"'),
        headers={"content-type": "application/json"},
    )
    assert r.status_code == 400, r.text
    lst = await client.get("/v1/tasks")
    assert lst.status_code == 200 and lst.json()["tasks"] == []


# ── AG-UI ingress: one terminal frame, no crash ──


def _agui_body(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "threadId": "t1",
        "runId": "r1",
        "messages": [{"id": "m1", "role": "user", "content": "hi"}],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
    body.update(over)
    return body


@pytest.mark.parametrize(
    "field,value",
    [
        ("threadId", ESCAPED_LONE),
        ("runId", ESCAPED_LONE),
        ("state", {"k": ESCAPED_LONE}),
    ],
)
async def test_ag_ui_lone_surrogate_ends_with_one_run_error(client, field, value):
    body = json.dumps(_agui_body(**{field: "@@PLACEHOLDER@@"}))
    body = body.replace(
        '"@@PLACEHOLDER@@"',
        json.dumps(value).replace("\\\\ud800", "\\ud800"),
    )
    assert "\\ud800" in body
    r = await client.post(
        "/ag-ui/run",
        content=_raw(body),
        headers={"content-type": "application/json", "accept": "text/event-stream"},
    )
    assert r.status_code == 200, r.text
    r.content.decode("utf-8")  # the whole stream is valid UTF-8
    frames = sse_frames(r.text)
    terminals = [f for f in frames if f["type"] in ("RUN_ERROR", "RUN_FINISHED")]
    assert len(terminals) == 1, frames
    assert terminals[0]["type"] == "RUN_ERROR"
    assert frames[0]["type"] == "RUN_STARTED"
    lst = await client.get("/v1/tasks")
    assert lst.status_code == 200, lst.text


# ── MCP ingress ──


async def test_mcp_tools_call_lone_surrogate_argument_is_parse_error(client):
    headers = await _mcp_init(client)
    raw = _raw(
        '{"jsonrpc":"2.0","id":7,"method":"tools/call",'
        '"params":{"name":"x","arguments":{"q":"%s"}}}' % ESCAPED_LONE
    )
    r = await client.post(
        "/mcp", content=raw, headers={**headers, "content-type": "application/json"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["error"]["code"] == -32700


# ── OAuth dynamic client registration (same shared parser) ──


async def test_oauth_register_lone_surrogate_is_invalid_client_metadata(client):
    raw = _raw(
        '{"redirect_uris":["https://c.example.com/cb"],"client_name":"%s"}' % ESCAPED_LONE
    )
    r = await client.post(
        "/oauth/register", content=raw, headers={"content-type": "application/json"}
    )
    if r.status_code == 404:
        pytest.skip("OAuth registration not enabled in the default fixture")
    assert r.status_code == 400, r.text
    assert r.json()["error"] == "invalid_client_metadata"
    assert "\\ud800" not in r.text.lower()  # SI-2: no echo


# ── the artifact commit gate: FAILED, never a poisoned COMPLETED ──


async def test_tool_result_lone_surrogate_fails_task_and_reads_stay_200(
    client, fake_model
):
    client.app.state.registry = ToolRegistry([_tools], {})
    fake_model.script(tool_call("cut_emoji_chart", {}), reply("done"))
    r = await client.post(
        "/v1/message:send",
        json={
            "message": {
                "role": "user",
                "parts": [{"kind": "text", "text": "chart"}],
                "messageId": uuid.uuid4().hex,
            }
        },
    )
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    task = await wait_for_state(client, task_id)  # asserts GET is 200
    assert task["status"]["state"] == "failed", task
    assert not task.get("artifacts"), task
    lst = await client.get("/v1/tasks")
    assert lst.status_code == 200, lst.text
    assert [t["id"] for t in lst.json()["tasks"]] == [task_id]


# ── round 6: the status-commit choke point ──
#
# Ingress and the artifact gate are not the only producers of stored task
# text. Model text (TextEvent), ProgressEvent/NoteEvent and ToolProgressEvent
# messages all reach set_task_status through _agent_message. Before round 6 a
# lone surrogate there was stored as-is, and GET /v1/tasks/{id} and
# GET /v1/tasks then answered 502 -32006 for the whole identity.

from agent_sdk.agent.events import ToolProgressEvent  # noqa: E402
from agent_sdk.agent.runner import _agent_message, set_task_status  # noqa: E402
from agent_sdk.common.json_strict import dumps_strict, scrub_unencodable  # noqa: E402
from agent_sdk.models.a2a import Message, TaskState, TaskStatus, TextPart  # noqa: E402
from agent_sdk.models.errors import WireError  # noqa: E402

FFFD = "�"

_progress_tools = ToolSet()


@_progress_tools.tool(tier=1, emits=BarChart, read_only=True)
async def cut_emoji_progress():
    """Reports progress text holding a lone surrogate, then a clean chart."""
    yield ToolProgressEvent(message=f"fetched {LONE}", tool_name="cut_emoji_progress")
    yield BarChart(bars=[BarItem(category="ok", value=1.0)])


def _send_body(text: str = "go") -> dict[str, Any]:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


def test_scrub_unencodable_replaces_surrogates_at_any_depth():
    assert scrub_unencodable(LONE) == f"a{FFFD}b"
    assert scrub_unencodable({LONE: [LONE, ("x", LONE)]}) == {
        f"a{FFFD}b": [f"a{FFFD}b", ("x", f"a{FFFD}b")]
    }
    clean = {"k": ["v", 1, None, 2.5]}
    assert scrub_unencodable(clean) is clean  # unchanged → same object
    assert scrub_unencodable("\U0001f600") == "\U0001f600"  # a real emoji stays


async def test_model_text_lone_surrogate_keeps_task_reads_200(client, fake_model):
    fake_model.script(reply("hello " + LONE))
    r = await client.post("/v1/message:send", json=_send_body())
    assert r.status_code == 200, r.text
    task_id = r.json()["id"]
    task = await wait_for_state(client, task_id)  # asserts GET is 200
    assert task["status"]["state"] == "completed", task
    text = task["status"]["message"]["parts"][0]["text"]
    assert text == f"hello a{FFFD}b"
    assert any(
        p.get("text") == f"hello a{FFFD}b"
        for m in task.get("history", [])
        for p in m["parts"]
    ), task
    lst = await client.get("/v1/tasks")
    assert lst.status_code == 200, lst.text
    assert [t["id"] for t in lst.json()["tasks"]] == [task_id]


async def test_tool_progress_lone_surrogate_streams_and_reads_200(client, fake_model):
    client.app.state.registry = ToolRegistry([_progress_tools], {})
    fake_model.script(tool_call("cut_emoji_progress", {}), reply("done"))
    r = await client.post("/v1/message:stream", json=_send_body())
    assert r.status_code == 200, r.text
    r.content.decode("utf-8")  # the whole stream is valid UTF-8
    frames = sse_frames(r.text)
    assert f"fetched a{FFFD}b" in r.text, r.text
    finals = [f for f in frames if (f.get("result") or f).get("final")]
    assert finals and (finals[-1].get("result") or finals[-1])["status"]["state"] == "completed"
    task_id = (frames[0].get("result") or frames[0]).get("taskId") or (
        frames[0].get("result") or frames[0]
    ).get("id")
    got = await client.get(f"/v1/tasks/{task_id}")
    assert got.status_code == 200, got.text
    lst = await client.get("/v1/tasks")
    assert lst.status_code == 200, lst.text
    assert task_id in [t["id"] for t in lst.json()["tasks"]]


def test_set_task_status_scrubs_message_and_error():
    class _Rec:
        pass

    from agent_sdk.models.a2a import Task

    rec = _Rec()
    rec.task = Task(id="t", contextId="c", status=TaskStatus(state=TaskState.WORKING))
    msg = Message(
        role="agent",
        parts=[TextPart(text=LONE)],
        messageId="m",
        metadata={LONE: LONE},
    )
    set_task_status(
        rec, TaskState.FAILED, msg, error=WireError(code=-32603, message=LONE)
    )
    wire = rec.task.wire()
    dumps_strict(wire)  # must not raise
    assert wire["status"]["message"]["parts"][0]["text"] == f"a{FFFD}b"
    assert wire["status"]["message"]["metadata"] == {f"a{FFFD}b": f"a{FFFD}b"}
    assert wire["status"]["error"]["message"] == f"a{FFFD}b"
    # the builder applies the same rule, so history entries are clean too
    built = _agent_message(rec, LONE, metadata={"k": [LONE]})
    dumps_strict(built.wire())


async def test_previously_stored_bad_record_does_not_block_reads(client, fake_model):
    """A record stored before this fix (or written by a durable store
    straight into ``record.task``) must not 502 every read."""
    fake_model.script(reply("ok"), reply("ok"))
    ids = []
    for _ in range(2):
        r = await client.post("/v1/message:send", json=_send_body())
        assert r.status_code == 200, r.text
        ids.append(r.json()["id"])
        await wait_for_state(client, ids[-1])
    store = client.app.state.task_store
    record = store.get(ids[0])
    record.task.status = TaskStatus(
        state=TaskState.COMPLETED,
        message=Message.model_construct(
            role="agent",
            kind="message",
            parts=[TextPart(text=LONE)],
            message_id="m",
        ),
    )
    with pytest.raises(ValueError):
        dumps_strict(record.task.wire())  # the poisoned shape is real
    got = await client.get(f"/v1/tasks/{ids[0]}")
    assert got.status_code == 200, got.text
    assert got.json()["status"]["message"]["parts"][0]["text"] == f"a{FFFD}b"
    lst = await client.get("/v1/tasks")
    assert lst.status_code == 200, lst.text
    assert sorted(t["id"] for t in lst.json()["tasks"]) == sorted(ids)
