"""GH-159: non-text input parts are rejected, never silently dropped."""
import uuid

import pytest

from agent_sdk.testing import FakeModelClient, reply

FILE = {"kind": "file", "file": {"bytes": "c2VjcmV0LWJ5dGVz", "mimeType": "image/png"}}
DATA = {"kind": "data", "data": {"secret": "s3cr3t-value"}}
TEXT = {"kind": "text", "text": "hello"}


def _msg(parts, **extra):
    return {"message": {"role": "user", "parts": parts, "messageId": uuid.uuid4().hex, **extra}}


def _task_count(app):
    return len(app.state.task_store._records) if hasattr(app.state.task_store, "_records") else None


@pytest.fixture(autouse=True)
def _fake(app):
    app.state.model_client = FakeModelClient([reply("ok")] * 5)


@pytest.mark.parametrize("path", ["/v1/message:send", "/v1/message:stream"])
@pytest.mark.parametrize(
    "parts", [[FILE], [DATA], [TEXT, FILE], [DATA, TEXT]], ids=["file", "data", "mixed-file", "mixed-data"]
)
async def test_non_text_rejected(app, client, path, parts):
    before = _task_count(app)
    r = await client.post(path, json=_msg(parts))
    assert r.status_code == 415
    err = r.json()["error"]
    assert err["code"] == -32005
    assert "s3cr3t" not in r.text and "c2VjcmV0" not in r.text
    assert _task_count(app) == before


@pytest.mark.parametrize("path", ["/v1/message:send", "/v1/message:stream"])
@pytest.mark.parametrize("text", ["", "   "])
async def test_empty_text_rejected(app, client, path, text):
    before = _task_count(app)
    r = await client.post(path, json=_msg([{"kind": "text", "text": text}]))
    assert r.status_code == 400
    assert r.json()["error"]["code"] == -32602
    assert _task_count(app) == before


async def test_resume_rejects_non_text_and_empty(app, client):
    for parts, code in (([FILE], -32005), ([{"kind": "text", "text": ""}], -32602)):
        r = await client.post("/v1/message:send", json=_msg(parts, taskId="no-such-task"))
        assert r.json()["error"]["code"] == code


async def test_text_only_still_accepted(client):
    r = await client.post("/v1/message:send", json=_msg([TEXT]))
    assert r.status_code == 200


async def _agui(client, content):
    r = await client.post(
        "/ag-ui/run",
        json={"threadId": "t1", "runId": "r1", "messages": [{"role": "user", "content": content}]},
    )
    return r.text


async def test_agui_non_text_part_rejected(app, client):
    before = _task_count(app)
    text = await _agui(client, [{"type": "text", "text": "hi"}, {"type": "binary", "data": "AAAA"}])
    assert "RUN_ERROR" in text and "binary" in text
    assert _task_count(app) == before


async def test_agui_text_list_content_works(client):
    text = await _agui(client, [{"type": "text", "text": "hi"}])
    assert "RUN_ERROR" not in text and "RUN_FINISHED" in text


@pytest.mark.parametrize("kind", ["a" * 10000, "ünïcödé", "binary"])
async def test_agui_error_label_bounded(client, kind):
    r = await client.post(
        "/ag-ui/run",
        json={"threadId": "t1", "runId": "r1", "messages": [{"role": "user", "content": [{"type": kind}]}]},
    )
    assert "RUN_ERROR" in r.text and len(r.text) < 2000
    assert ("a" * 100) not in r.text and "ünï" not in r.text


@pytest.mark.parametrize("resume", [True, "x", {"a": 1}, {}, []], ids=["true", "str", "dict", "empty-dict", "empty-list"])
async def test_agui_non_list_resume_does_not_bypass_rejection(app, client, resume):
    before = _task_count(app)
    r = await client.post(
        "/ag-ui/run",
        json={
            "threadId": "t1",
            "runId": "r1",
            "resume": resume,
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "hi"}, {"type": "binary", "data": "AAAA"}]}
            ],
        },
    )
    assert "RUN_ERROR" in r.text and "RUN_FINISHED" not in r.text
    assert _task_count(app) == before


async def test_agui_non_text_in_current_turn_user_message_rejected(client):
    r = await client.post(
        "/ag-ui/run",
        json={
            "threadId": "t1",
            "runId": "r1",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "summarize"}, {"type": "binary", "data": "AAAA"}]},
                {"role": "user", "content": [{"type": "text", "text": "please"}]},
            ],
        },
    )
    assert "RUN_ERROR" in r.text and "RUN_FINISHED" not in r.text


async def test_agui_non_text_in_earlier_history_is_skipped_not_rejected(app, client):
    # Ruling refinement (issue 159 comment 6135432947): only the current turn
    # (user messages after the last assistant message) is checked. A rejected
    # message kept in earlier history must not lock the thread, and its binary
    # payload must never reach the model.
    r = await client.post(
        "/ag-ui/run",
        json={
            "threadId": "t1",
            "runId": "r1",
            "messages": [
                {"role": "user", "content": [{"type": "binary", "data": "AAAA"}]},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": [{"type": "text", "text": "hi"}]},
            ],
        },
    )
    assert "RUN_ERROR" not in r.text and "RUN_FINISHED" in r.text
    sent = repr(app.state.model_client.calls[-1]["messages"])
    assert "AAAA" not in sent and "hi" in sent


async def test_agui_non_text_in_current_turn_after_assistant_rejected(client):
    r = await client.post(
        "/ag-ui/run",
        json={
            "threadId": "t1",
            "runId": "r1",
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": "hi"}]},
                {"role": "assistant", "content": "ok"},
                {"role": "user", "content": [{"type": "text", "text": "x"}, {"type": "image", "data": "AAAA"}]},
            ],
        },
    )
    assert "RUN_ERROR" in r.text and "RUN_FINISHED" not in r.text


async def test_agui_rejected_message_kept_in_history_keeps_failing(client):
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "x"}, {"type": "binary", "data": "AAAA"}]},
        {"role": "user", "content": [{"type": "text", "text": "hi again"}]},
    ]
    for _ in range(2):
        r = await client.post("/ag-ui/run", json={"threadId": "t1", "runId": "r1", "messages": messages})
        assert "RUN_ERROR" in r.text and "RUN_FINISHED" not in r.text
    r = await client.post("/ag-ui/run", json={"threadId": "t1", "runId": "r1", "messages": messages[1:]})
    assert "RUN_ERROR" not in r.text and "RUN_FINISHED" in r.text


@pytest.mark.parametrize(
    "content",
    [
        {"type": "binary", "data": "SECRETBYTES", "mimeType": "image/png"},
        {"type": "text", "text": "hi"},
        42,
        True,
    ],
    ids=["dict-binary", "dict-text", "int", "bool"],
)
async def test_agui_non_list_non_str_content_rejected(app, client, content):
    """RT-001 (round 5): the GH-159 allowlist must cover every content shape,
    not only lists — a bare part object must not fall through to the fold."""
    before = _task_count(app)
    text = await _agui(client, content)
    assert "RUN_ERROR" in text and "RUN_FINISHED" not in text
    assert "SECRETBYTES" not in text
    assert _task_count(app) == before


@pytest.mark.parametrize("content", ["hi", None])
async def test_agui_string_or_absent_content_not_shape_rejected(client, content):
    messages = [{"role": "user", "content": "hello"}, {"role": "user", "content": content}]
    r = await client.post("/ag-ui/run", json={"threadId": "t1", "runId": "r1", "messages": messages})
    assert "RUN_ERROR" not in r.text and "RUN_FINISHED" in r.text


def test_fold_never_stringifies_structured_content():
    from agent_sdk.routes.ag_ui import _fold_history

    folded = _fold_history(
        [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": {"type": "binary", "data": "SECRETBYTES"}},
        ],
        32000,
    )
    assert "SECRETBYTES" not in repr(folded)
