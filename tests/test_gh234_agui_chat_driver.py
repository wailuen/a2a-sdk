"""GH-234: ChatDriver AG-UI driver — headers, terminal event, text join, RUN_ERROR."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import httpx
import pytest

from agent_sdk.testing.chat import ChatDriver
from agent_sdk.testing.turns import run_turn

SECRET = "sentinel-SECRET-9f3a"
NO_TERMINAL = "stream closed without a terminal event"
ROOT = Path(__file__).resolve().parent.parent
STATIC = ROOT / "agent_sdk" / "console" / "static"


def _sse(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


def _content(delta, mid="m1"):
    return {"type": "TEXT_MESSAGE_CONTENT", "messageId": mid, "delta": delta}


FINISHED = {"type": "RUN_FINISHED", "outcome": {"type": "success"}}
ERROR = {"type": "RUN_ERROR", "message": "boom"}


def _driver(body, seen=None, status=200, **kw):
    def handler(req):
        if seen is not None:
            seen.append(req)
        return httpx.Response(status, content=body)

    client = httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler))
    return ChatDriver(client, **kw)


def _emits():
    log = {"error": [], "text": []}
    return log, {"error": log["error"].append, "text": log["text"].append}


@pytest.mark.asyncio
async def test_headers_sent_with_credentials_and_accept():
    seen = []
    d = _driver(_sse(_content("hi"), FINISHED), seen, credentials={"X-Agent-Credentials": SECRET})
    await d.agui_turn("q", "th", [])
    req = seen[0]
    assert req.headers["x-agent-credentials"] == SECRET
    assert req.headers["accept"] == "text/event-stream"
    assert SECRET.encode() not in req.content and SECRET not in str(req.url)


@pytest.mark.asyncio
async def test_unterminated_stream_fires_fixed_error():
    d = _driver(_sse(_content("part")))
    log, emit = _emits()
    out = await d.agui_turn("q", "th", [], emit=emit)
    assert log["error"] == [NO_TERMINAL]
    assert log["text"] == ["part"]
    assert out == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("frames", [[_content("part")], [_content("part"), ERROR]])
async def test_turn_does_not_append_partial_reply(frames):
    d = _driver(_sse(*frames))
    msgs: list = []
    out = await d.agui_turn("q", "th", msgs)
    assert out == ""
    assert [m for m in msgs if m["role"] == "assistant"] == []


@pytest.mark.asyncio
@pytest.mark.parametrize("frames", [[_content("part")], [_content("part"), ERROR]])
async def test_resume_does_not_append_partial_reply(frames):
    d = _driver(_sse(*frames))
    msgs = [{"role": "user", "content": "q"}]
    out = await d.agui_resume("i1", "th", msgs, payload={"decision": "yes"})
    assert out == ""
    assert [m for m in msgs if m["role"] == "assistant"] == []


@pytest.mark.asyncio
async def test_frames_after_run_error_ignored():
    d = _driver(_sse(_content("a"), ERROR, _content("late"), FINISHED))
    log, emit = _emits()
    out = await d.agui_turn("q", "th", [], emit=emit)
    assert log["text"] == ["a"]
    assert log["error"] == ["boom"]
    assert out == ""


@pytest.mark.asyncio
async def test_messages_joined_with_newline_deltas_concatenated():
    d = _driver(_sse(
        _content("Hel", "a"), _content("lo", "a"),
        _content("Wor", "b"), _content("ld", "b"),
        FINISHED,
    ))
    assert await d.agui_turn("q", "th", []) == "Hello\nWorld"


@pytest.mark.asyncio
async def test_text_message_chunk_handled():
    d = _driver(_sse(
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "a", "delta": "one"},
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "a", "delta": "!"},
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "b", "delta": "two"},
        FINISHED,
    ))
    assert await d.agui_turn("q", "th", []) == "one!\ntwo"


@pytest.mark.asyncio
async def test_credentials_never_leak_in_any_outcome():
    cases = {
        "finished": (200, _sse(_content("hi"), FINISHED)),
        "unterminated": (200, _sse(_content("hi"))),
        "run_error": (200, _sse(_content("hi"), ERROR)),
        "http_error": (500, b"upstream"),
    }
    for name, (status, body) in cases.items():
        seen = []
        d = _driver(body, seen, status=status, credentials={"X-Agent-Credentials": SECRET})
        log, emit = _emits()
        if name == "http_error":
            with pytest.raises(httpx.HTTPStatusError) as ei:
                await d.agui_turn("q", "th", [], emit=emit)
            assert SECRET not in str(ei.value) and SECRET not in repr(ei.value), name
        else:
            await d.agui_turn("q", "th", [], emit=emit)
        req = seen[0]
        assert req.headers["x-agent-credentials"] == SECRET
        assert SECRET.encode() not in req.content, name
        assert SECRET not in str(req.url), name
        assert all(SECRET not in s for s in log["error"] + log["text"]), name


async def _run(tmp_path, body):
    client = httpx.AsyncClient(
        base_url="http://t", transport=httpx.MockTransport(lambda r: httpx.Response(200, content=body))
    )
    kf = tmp_path / "key"
    kf.write_text("k\n")
    async with client as c:
        return await run_turn(
            transport="agui", base_url="http://t", key_file=kf, query="q",
            run_key="r1", state_dir=tmp_path / "state", client=c, budget_s=5,
        )


@pytest.mark.asyncio
async def test_run_turn_unterminated_stream_fails(tmp_path):
    out = await _run(tmp_path, _sse(_content("partial")))
    assert out["ok"] is False and out["reply"] == ""


@pytest.mark.asyncio
async def test_run_turn_partial_then_run_error_fails(tmp_path):
    out = await _run(tmp_path, _sse(_content("partial"), ERROR))
    assert out["ok"] is False and out["reply"] == ""


@pytest.mark.asyncio
async def test_run_turn_normal_stream_passes(tmp_path):
    out = await _run(tmp_path, _sse(_content("fine"), FINISHED))
    assert out["ok"] is True and out["reply"] == "fine"


_NODE = shutil.which("node")
needs_node = pytest.mark.skipif(_NODE is None, reason="node is not installed")


def _extract(chat_js: str, signature: str) -> str:
    start = chat_js.index(signature)
    end = chat_js.index("\n  }\n", start) + len("\n  }\n")
    return chat_js[start:end]


_HARNESS = r"""
const state = { threadId: "T1", aguiMessages: [], catalogIds: [] };
let n = 0;
const uuid = () => "uuid-" + (++n);
const catalogIdsReady = Promise.resolve();
const log = { forms: 0, lines: [], placeholder: "" };
const formNodes = [];
function mkForm() {
  const f = { removed: false, listeners: {}, children: [] };
  f.remove = () => { f.removed = true; };
  f.appendChild = (c) => { f.children.push(c); };
  f.addEventListener = (t, fn) => { f.listeners[t] = fn; };
  return f;
}
const el = (tag) => (tag === "form" ? mkForm() : { textContent: "", appendChild() {}, addEventListener() {} });
const transcript = { appendChild(c) { if (c.listeners) formNodes.push(c); }, scrollTop: 0, scrollHeight: 0 };
const input = { placeholder: "" };
const systemLine = (m) => log.lines.push(m);
const traceFrame = () => {};
const fmtJson = (x) => JSON.stringify(x);
const formFields = (schema) => (schema && schema.fields) || null;
const buildResumePayload = () => ({ ok: true, payload: { decision: "yes" } });
const buildPayloadFromValues = () => ({ ok: true, payload: { decision: "yes" } });
const streamingBubble = () => { let t = ""; return { append(d) { t += d; }, text: () => t }; };
const handleCustom = () => {};
let pendingInterrupt = null;
let shownForm = null;
let postFails = false;
let onPost = null;
const postSse = () => ({});
const postWithRetry = async () => { if (onPost) onPost(); return postFails ? null : {}; };
const readSse = async (resp, cb) => { for (const f of FRAMES) cb({ json: f, data: "" }); };
"""


def _node_run(frames, scenario: str) -> dict:
    assert _NODE is not None
    chat_js = (STATIC / "chat.js").read_text()
    fns = "\n".join(
        _extract(chat_js, sig)
        for sig in (
            "  function removeInterruptForm()",
            "  function interruptForm(",
            "  async function sendAgui(",
        )
    )
    script = (
        f"const FRAMES = {json.dumps(frames)};\n{_HARNESS}\n{fns}\n"
        f"(async () => {{ {scenario}\n"
        "process.stdout.write(JSON.stringify({ msgs: state.aguiMessages, pending: pendingInterrupt, "
        "forms: formNodes.map(f => f.removed), placeholder: input.placeholder })); })();\n"
    )
    out = subprocess.run([_NODE, "-e", script], capture_output=True, text=True, timeout=20, check=True)
    return json.loads(out.stdout)


_FIN = {"type": "RUN_FINISHED", "outcome": {"type": "success"}}


def _msg(t, mid=None, delta=None):
    f = {"type": t}
    if mid is not None:
        f["messageId"] = mid
    if delta is not None:
        f["delta"] = delta
    return f


@needs_node
def test_console_folds_in_first_frame_order_after_run_finished():
    frames = [
        _msg("TEXT_MESSAGE_CHUNK", "c1", "chunk"),
        _msg("TEXT_MESSAGE_START", "s1"),
        _msg("TEXT_MESSAGE_CONTENT", "s1", "start"),
        _msg("TEXT_MESSAGE_END", "s1"),
        _msg("TEXT_MESSAGE_CHUNK", None, "A"),
        _msg("TEXT_MESSAGE_CHUNK", "c1", "!"),
        _FIN,
    ]
    out = _node_run(frames, 'await sendAgui("hi");')
    assistant = [(m["id"], m["content"]) for m in out["msgs"] if m["role"] == "assistant"]
    assert [a[0] for a in assistant[:2]] == ["c1", "s1"]
    assert assistant[0][1] == "chunk!" and assistant[1][1] == "start"
    assert assistant[2][1] == "A" and assistant[2][0].startswith("uuid-")


@needs_node
def test_console_nothing_folded_without_run_finished():
    frames = [
        _msg("TEXT_MESSAGE_START", "s1"),
        _msg("TEXT_MESSAGE_CONTENT", "s1", "x"),
        _msg("TEXT_MESSAGE_END", "s1"),
        _msg("TEXT_MESSAGE_CHUNK", "c1", "y"),
    ]
    out = _node_run(frames, 'await sendAgui("hi");')
    assert [m for m in out["msgs"] if m["role"] == "assistant"] == []


@needs_node
def test_console_idless_chunk_without_earlier_id_gets_uuid():
    frames = [_msg("TEXT_MESSAGE_CHUNK", None, "a"), _msg("TEXT_MESSAGE_CHUNK", None, "b"), _FIN]
    out = _node_run(frames, 'await sendAgui("hi");')
    assistant = [m for m in out["msgs"] if m["role"] == "assistant"]
    assert len(assistant) == 1 and assistant[0]["content"] == "ab"
    assert assistant[0]["id"].startswith("uuid-")


_PENDING = 'pendingInterrupt = { interruptId: "i1", responseSchema: { fields: ["decision"] }, message: "m" };'


@needs_node
def test_failed_resume_restores_interrupt_and_single_form():
    scenario = (
        _PENDING + " interruptForm(pendingInterrupt); postFails = true;"
        ' await sendAgui("yes");'
    )
    out = _node_run([], scenario)
    assert out["pending"]["interruptId"] == "i1"
    assert out["placeholder"].startswith("Resume:")
    live = [r for r in out["forms"] if not r]
    assert len(live) == 1


@needs_node
def test_failed_resume_not_restored_after_thread_reset():
    scenario = (
        _PENDING + " postFails = true; onPost = () => { state.threadId = 'T2'; };"
        ' await sendAgui("yes");'
    )
    out = _node_run([], scenario)
    assert out["pending"] is None
    assert [r for r in out["forms"] if not r] == []


@needs_node
def test_failed_resume_not_restored_when_new_interrupt_pending():
    scenario = (
        _PENDING + " postFails = true;"
        ' onPost = () => { pendingInterrupt = { interruptId: "i2", responseSchema: {}, message: "n" }; };'
        ' await sendAgui("yes");'
    )
    out = _node_run([], scenario)
    assert out["pending"]["interruptId"] == "i2"
    assert [r for r in out["forms"] if not r] == []


@needs_node
def test_interrupt_form_is_single_instance():
    scenario = (
        _PENDING + " interruptForm(pendingInterrupt); interruptForm(pendingInterrupt);"
    )
    out = _node_run([], scenario)
    assert out["forms"] == [True, False]


@pytest.mark.asyncio
async def test_chunk_without_message_id_inherits_open_chunk():
    """w063 RT-001: AG-UI carries messageId on the first chunk only."""
    d = _driver(_sse(
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "a", "delta": "Hel"},
        {"type": "TEXT_MESSAGE_CHUNK", "delta": "lo"},
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "b", "delta": "World"},
        {"type": "TEXT_MESSAGE_CHUNK", "delta": "!"},
        FINISHED,
    ))
    assert await d.agui_turn("q", "th", []) == "Hello\nWorld!"


@pytest.mark.asyncio
async def test_empty_message_adds_no_separator_and_chunk_id_resets():
    d = _driver(_sse(
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "m0"},
        {"type": "TEXT_MESSAGE_CHUNK", "messageId": "m1", "delta": "a"},
        {"type": "TEXT_MESSAGE_START", "messageId": "m2", "role": "assistant"},
        _content("b", "m2"),
        {"type": "TEXT_MESSAGE_END", "messageId": "m2"},
        {"type": "TEXT_MESSAGE_CHUNK", "delta": "c"},
        FINISHED,
    ))
    assert await d.agui_turn("q", "th", []) == "a\nb\nc"
