"""GH-234: ChatDriver AG-UI driver — headers, terminal event, text join, RUN_ERROR."""

from __future__ import annotations

import json
import os
import re
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
_IN_CI = os.environ.get("CI", "").strip().lower() in {"1", "true", "yes"}


def test_gh234_node_available_in_ci():
    if not _IN_CI:
        pytest.skip("not running in CI; local runs may lack node")
    assert _NODE is not None, "node is required in CI for the chat.js AG-UI live tests"


def _extract(chat_js: str, signature: str) -> str:
    start = chat_js.index(signature)
    end = chat_js.index("\n  }\n", start) + len("\n  }\n")
    return chat_js[start:end]


_HARNESS = r"""
const state = { threadId: "T1", aguiMessages: [], catalogIds: [], busy: false, contextId: null, abort: null };
const BUSY_NOTE = "busy: wait for the current run to finish";
const sendBtn = { disabled: false };
const resetBtn = { addEventListener(t, fn) { resetBtn.fn = fn; } };
const trace = { id: "trace" };
const ctx = { toast() {} };
const resetSurfaces = () => {};
const clear = (n) => { if (n.children) n.children.length = 0; };
let n = 0;
const uuid = () => "uuid-" + (++n);
const catalogIdsReady = Promise.resolve();
const log = { forms: 0, lines: [], placeholder: "", custom: 0 };
const formNodes = [];
function mkForm() {
  const f = { removed: false, listeners: {}, children: [] };
  f.remove = () => { f.removed = true; };
  f.appendChild = (c) => { f.children.push(c); };
  f.addEventListener = (t, fn) => { f.listeners[t] = fn; };
  return f;
}
const el = (tag) => (tag === "form" ? mkForm() : { textContent: "", appendChild() {}, addEventListener() {} });
const transcript = { children: [], appendChild(c) { transcript.children.push(c); if (c.listeners) formNodes.push(c); }, scrollTop: 0, scrollHeight: 0 };
const input = { placeholder: "", focus() {} };
let posts = 0;
let lastBody = null;
let postThrows = false;
const systemLine = (m) => log.lines.push(m);
const traceFrame = () => {};
const fmtJson = (x) => JSON.stringify(x);
const formFields = (schema) => (schema && schema.fields) || null;
const buildResumePayload = () => ({ ok: true, payload: { decision: "yes" } });
const buildPayloadFromValues = () => ({ ok: true, payload: { decision: "yes" } });
const streamingBubble = () => { let t = ""; return { append(d) { t += d; }, text: () => t }; };
const handleCustom = () => { log.custom++; };
const bubble = () => {};
const handleA2aArtifact = () => {};
const auditLine = () => {};
let lastSignal = null;
let lastRetrySignal = null;
let onFrame = null;
let pendingInterrupt = null;
let shownForm = null;
let postFails = false;
let onPost = null;
const postSse = (url, body, headers, signal) => { lastBody = body; lastSignal = signal; return {}; };
const postWithRetry = async (fn, opts) => {
  lastRetrySignal = opts ? opts.signal : null;
  posts++;
  if (onPost) onPost();
  if (postThrows) throw new Error("kaput");
  const r = fn();
  return postFails ? null : r;
};
const readSse = async (resp, cb) => { for (const f of FRAMES) { if (onFrame) onFrame(f); cb({ json: f, data: "" }); } };
"""


def _reset_handler(chat_js: str) -> str:
    m = re.search(r'resetBtn\.addEventListener\("click", \(\) => \{[\s\S]*?\n  \}\);\n', chat_js)
    assert m, "reset handler not found in chat.js"
    return m.group(0)


def _node_run(frames, scenario: str) -> dict:
    assert _NODE is not None
    chat_js = (STATIC / "chat.js").read_text()
    fns = _reset_handler(chat_js) + "\n".join(
        _extract(chat_js, sig)
        for sig in (
            "  function removeInterruptForm()",
            "  function interruptForm(",
            "  function staleGuard(",
            "  async function postAbortable(",
            "  async function runExclusive(",
            "  async function sendA2a(",
            "  async function sendAgui(",
            "  async function send()",
        )
    )
    script = (
        f"const FRAMES = {json.dumps(frames)};\n{_HARNESS}\n{fns}\n"
        f"(async () => {{ {scenario}\n"
        "process.stdout.write(JSON.stringify({ msgs: state.aguiMessages, pending: pendingInterrupt, "
        "forms: formNodes.map(f => f.removed), placeholder: input.placeholder, posts, lastBody, "
        "busy: state.busy, lines: log.lines, thread: state.threadId, "
        "ctx: state.contextId, custom: log.custom, signalMatches: lastSignal ? lastSignal === (state.abort && state.abort.signal) : null, aborted: state.abort ? state.abort.signal.aborted : null, "
        "inputValue: input.value, retrySignalMatches: lastRetrySignal ? lastRetrySignal === (state.abort && state.abort.signal) : null, "
        "live: transcript.children.filter(c => c.listeners && !c.removed).length })); })();\n"
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


_SUBMIT = "formNodes[formNodes.length - 1].listeners.submit({ preventDefault() {} });"
_SETTLE = "await new Promise(r => setTimeout(r, 20));"
_INTERRUPT_FIN = {
    "type": "RUN_FINISHED",
    "outcome": {"type": "interrupt", "interrupts": [
        {"id": "i9", "message": "ok?", "responseSchema": {"fields": ["decision"]}}]},
}


@needs_node
def test_stale_thread_run_finished_neither_captures_interrupt_nor_folds():
    frames = [_msg("TEXT_MESSAGE_START", "s1"), _msg("TEXT_MESSAGE_CONTENT", "s1", "x"), _INTERRUPT_FIN]
    out = _node_run(frames, "onPost = () => { state.threadId = 'T2'; }; await sendAgui('hi');")
    assert out["msgs"] == []
    assert out["pending"] is None
    assert out["live"] == 0 and out["forms"] == []


@needs_node
def test_same_thread_interrupt_still_captured():
    out = _node_run([_INTERRUPT_FIN], "await sendAgui('hi');")
    assert out["pending"]["interruptId"] == "i9"
    assert out["live"] == 1
    assert [m["role"] for m in out["msgs"]] == ["user"]


@needs_node
def test_run_error_removes_interrupt_form():
    scenario = _PENDING + ' interruptForm(pendingInterrupt); await sendAgui("yes");'
    out = _node_run([{"type": "RUN_ERROR", "message": "boom"}], scenario)
    assert out["pending"] is None
    assert out["live"] == 0


@needs_node
def test_form_submit_ignored_when_interrupt_no_longer_pending():
    scenario = (
        _PENDING + " interruptForm(pendingInterrupt); pendingInterrupt = null;"
        f" {_SUBMIT} {_SETTLE}"
    )
    out = _node_run([_FIN], scenario)
    assert out["posts"] == 0


@needs_node
def test_form_submit_respects_busy_guard():
    scenario = (
        _PENDING + " interruptForm(pendingInterrupt); state.busy = true;"
        f" {_SUBMIT} {_SETTLE}"
    )
    out = _node_run([_FIN], scenario)
    assert out["posts"] == 0
    assert out["live"] == 1 and out["busy"] is True


@needs_node
def test_form_submit_sends_resume_and_resets_busy():
    scenario = _PENDING + f" interruptForm(pendingInterrupt); {_SUBMIT} {_SETTLE}"
    out = _node_run([_FIN], scenario)
    assert out["posts"] == 1
    assert out["lastBody"]["resume"][0]["interruptId"] == "i1"
    assert out["busy"] is False and out["live"] == 0


@needs_node
def test_form_submit_failure_is_caught_and_busy_released():
    scenario = (
        _PENDING + " interruptForm(pendingInterrupt); postThrows = true;"
        f" {_SUBMIT} {_SETTLE}"
    )
    out = _node_run([], scenario)
    assert out["busy"] is False
    assert any(line.startswith("error: kaput") for line in out["lines"])


@needs_node
def test_user_role_message_not_folded():
    frames = [
        _msg("TEXT_MESSAGE_START", "u1") | {"role": "user"},
        _msg("TEXT_MESSAGE_CONTENT", "u1", "echo"),
        _msg("TEXT_MESSAGE_START", "a1") | {"role": "assistant"},
        _msg("TEXT_MESSAGE_CONTENT", "a1", "real"),
        _msg("TEXT_MESSAGE_START", "n1") | {"role": 7},
        _msg("TEXT_MESSAGE_CONTENT", "n1", "nonstring"),
        _FIN,
    ]
    out = _node_run(frames, 'await sendAgui("hi");')
    assert [(m["id"], m["content"]) for m in out["msgs"] if m["role"] == "assistant"] == [
        ("a1", "real"), ("n1", "nonstring")]


@needs_node
def test_empty_string_role_is_ignored_like_chat_driver():
    # v0.22.0 release gate: C-072 records a role only when it is a non-empty string.
    frames = [
        _msg("TEXT_MESSAGE_START", "e1") | {"role": ""},
        _msg("TEXT_MESSAGE_CONTENT", "e1", "kept"),
        _msg("TEXT_MESSAGE_CHUNK", "e2", "chunk") | {"role": ""},
        _FIN,
    ]
    out = _node_run(frames, 'await sendAgui("hi");')
    assert [(m["id"], m["content"]) for m in out["msgs"] if m["role"] == "assistant"] == [
        ("e1", "kept"), ("e2", "chunk")]


@needs_node
def test_chunk_first_role_recorded_and_non_assistant_skipped():
    frames = [
        _msg("TEXT_MESSAGE_CHUNK", "c1", "a") | {"role": "tool"},
        _msg("TEXT_MESSAGE_CHUNK", None, "b"),
        _FIN,
    ]
    out = _node_run(frames, 'await sendAgui("hi");')
    assert [m for m in out["msgs"] if m["role"] == "assistant"] == []


@needs_node
def test_content_without_start_kept_as_assistant():
    frames = [_msg("TEXT_MESSAGE_CONTENT", "z1", "no start"), _FIN]
    out = _node_run(frames, 'await sendAgui("hi");')
    assert [(m["id"], m["content"]) for m in out["msgs"] if m["role"] == "assistant"] == [("z1", "no start")]


@needs_node
def test_body_includes_user_but_history_appends_only_on_run_finished():
    frames = [_msg("TEXT_MESSAGE_CONTENT", "z1", "partial")]
    out = _node_run(frames, 'await sendAgui("hi");')
    assert [m["role"] for m in out["lastBody"]["messages"]] == ["user"]
    assert out["msgs"] == []
    out = _node_run([_msg("TEXT_MESSAGE_CONTENT", "z1", "ok"), _FIN], 'await sendAgui("hi");')
    assert [m["role"] for m in out["msgs"]] == ["user", "assistant"]


@needs_node
def test_run_error_does_not_append_user_message():
    out = _node_run([{"type": "RUN_ERROR", "message": "x"}], 'await sendAgui("hi");')
    assert out["msgs"] == []


@needs_node
def test_reset_handler_clears_pending_interrupt_and_form():
    scenario = _PENDING + " interruptForm(pendingInterrupt); transcript.children.push({});" + (
        " resetBtn.fn();"
    )
    out = _node_run([], scenario)
    assert out["pending"] is None
    assert out["live"] == 0 and out["forms"] == [True]
    assert out["thread"] != "T1"


_ACTIVE_ASSISTANT = lambda out: [(m["id"], m["content"]) for m in out["msgs"] if m["role"] == "assistant"]  # noqa: E731


@needs_node
def test_chunk_role_ignored_after_content_text_for_same_id():
    frames = [
        _msg("TEXT_MESSAGE_CONTENT", "k1", "a"),
        _msg("TEXT_MESSAGE_CHUNK", "k1", "b") | {"role": "tool"},
        _FIN,
    ]
    out = _node_run(frames, 'await sendAgui("hi");')
    assert _ACTIVE_ASSISTANT(out) == [("k1", "ab")]


@needs_node
def test_chunk_role_ignored_after_earlier_chunk_text():
    frames = [
        _msg("TEXT_MESSAGE_CHUNK", "k1", "a"),
        _msg("TEXT_MESSAGE_CHUNK", "k1", "b") | {"role": "tool"},
        _FIN,
    ]
    out = _node_run(frames, 'await sendAgui("hi");')
    assert _ACTIVE_ASSISTANT(out) == [("k1", "ab")]


@needs_node
def test_fold_skips_empty_text_and_mints_id_for_idless_buffer():
    frames = [
        _msg("TEXT_MESSAGE_START", "e1"),
        _msg("TEXT_MESSAGE_END", "e1"),
        _msg("TEXT_MESSAGE_CONTENT", None, "orphan"),
        _FIN,
    ]
    out = _node_run(frames, 'await sendAgui("hi");')
    got = _ACTIVE_ASSISTANT(out)
    assert len(got) == 1 and got[0][1] == "orphan"
    assert isinstance(got[0][0], str) and got[0][0]


_A2A_TASK = {"kind": "task", "id": "t1", "contextId": "ctx-new", "status": {"state": "working"}}


@needs_node
def test_a2a_context_write_back_kept_without_reset():
    out = _node_run([_A2A_TASK], 'await sendA2a("hi");')
    assert out["ctx"] == "ctx-new"


@needs_node
def test_a2a_context_write_back_dropped_after_reset():
    scenario = "onFrame = () => { state.threadId = 'T2'; }; await sendA2a('hi');"
    out = _node_run([_A2A_TASK], scenario)
    assert out["ctx"] is None


@needs_node
def test_reset_aborts_in_flight_request():
    out = _node_run([], "state.abort = new AbortController(); resetBtn.fn();")
    assert out["aborted"] is True


@needs_node
@pytest.mark.parametrize("call", ['sendAgui("hi")', 'sendA2a("hi")'])
def test_run_paths_pass_controller_signal_through_post_sse(call):
    out = _node_run([], f"state.abort = new AbortController(); await {call};")
    assert out["signalMatches"] is True


@needs_node
def test_stale_custom_and_system_lines_dropped():
    frames = [{"type": "CUSTOM", "name": "AGENT_NOTE", "value": {"note": "x"}}, _FIN]
    out = _node_run(frames, "onFrame = () => { state.threadId = 'T2'; }; await sendAgui('hi');")
    assert out["custom"] == 0
    assert "run finished" not in out["lines"]
    assert not any("stream closed" in ln or "stream dropped" in ln for ln in out["lines"])


@needs_node
def test_same_thread_custom_still_handled():
    frames = [{"type": "CUSTOM", "name": "AGENT_NOTE", "value": {"note": "x"}}, _FIN]
    out = _node_run(frames, "await sendAgui('hi');")
    assert out["custom"] == 1 and "run finished" in out["lines"]


@needs_node
def test_resume_click_while_busy_shows_fixed_busy_note():
    scenario = "state.busy = true; let ran = false; await runExclusive(async () => { ran = true; }); if (ran) throw new Error('ran');"
    out = _node_run([], scenario)
    assert out["lines"] == ["busy: wait for the current run to finish"]


def test_chat_js_has_no_second_raw_fetch():
    src = (STATIC / "chat.js").read_text()
    assert len(re.findall(r"(?<![\w.])fetch\(", src)) == 1
    assert "signal" in src and "AbortController" in src


@needs_node
def test_post_sse_passes_signal_and_keeps_auth_header(tmp_path):
    assert _NODE is not None
    mod = tmp_path / "api.mjs"
    mod.write_text((STATIC / "api.js").read_text())
    script = (
        f"import {{ postSse, setKey }} from {json.dumps(mod.as_uri())};\n"
        "globalThis.sessionStorage = { _v: {}, getItem(k) { return this._v[k] || null; }, setItem(k, v) { this._v[k] = v; } };\n"
        "let seen; globalThis.fetch = async (u, init) => { seen = init; return {}; };\n"
        "setKey('K'); const ac = new AbortController();\n"
        "await postSse('/x', {}, undefined, ac.signal);\n"
        "const a = seen.signal === ac.signal && seen.headers.Authorization === 'Bearer K';\n"
        "await postSse('/x', {});\n"
        "process.stdout.write(JSON.stringify({ a, none: seen.signal === undefined }));\n"
    )
    f = tmp_path / "run.mjs"
    f.write_text(script)
    out = subprocess.run([_NODE, str(f)], capture_output=True, text=True, timeout=20, check=True)
    assert json.loads(out.stdout) == {"a": True, "none": True}


# GH-263 item 1: the CHUNK role check keys on the frame's own messageId.
@needs_node
def test_idless_chunk_role_is_not_recorded_on_the_minted_id():
    frames = [_msg("TEXT_MESSAGE_CHUNK", None, "a") | {"role": "user"}, _FIN]
    out = _node_run(frames, 'await sendAgui("hi");')
    assistant = _ACTIVE_ASSISTANT(out)
    assert [c for _, c in assistant] == ["a"]
    assert assistant[0][0].startswith("uuid-")


@needs_node
def test_chunk_with_own_id_still_records_role_once():
    frames = [_msg("TEXT_MESSAGE_CHUNK", "k1", "a") | {"role": "user"}, _FIN]
    assert _ACTIVE_ASSISTANT(_node_run(frames, 'await sendAgui("hi");')) == []


# GH-263 item 4: a real mid-stream flip, counted by frames, not tied to the first frame or onPost.
_FLIP_AFTER_SECOND = "let k = 0; onFrame = () => { if (++k === 3) state.threadId = 'T2'; };"


@needs_node
def test_agui_thread_flip_after_second_frame_drops_the_rest():
    note = {"type": "CUSTOM", "name": "AGENT_NOTE", "value": {"note": "x"}}
    frames = [{"type": "RUN_STARTED", "runId": "r1"}, note, note, note, _FIN]
    out = _node_run(frames, _FLIP_AFTER_SECOND + " await sendAgui('hi');")
    assert out["custom"] == 1
    assert out["msgs"] == []
    assert "run finished" not in out["lines"]
    assert not any("stream closed" in ln for ln in out["lines"])


@needs_node
def test_a2a_thread_flip_after_second_frame_drops_the_rest():
    frames = [{"kind": "task", "id": f"t{i}", "contextId": f"c{i}", "status": {"state": "working"}} for i in (1, 2, 3)]
    out = _node_run(frames, _FLIP_AFTER_SECOND + " await sendA2a('hi');")
    assert out["lines"] == ["task t1 \u00b7 working", "task t2 \u00b7 working"]
    assert out["ctx"] == "c2"


# GH-263 item 5.
@needs_node
def test_a2a_thread_is_captured_before_the_catalog_await():
    out = _node_run([_A2A_TASK], "const p = sendA2a('hi'); state.threadId = 'T2'; await p;")
    assert out["ctx"] is None
    assert out["lines"] == []


@needs_node
def test_send_while_busy_shows_the_fixed_note_and_keeps_the_text():
    out = _node_run([], "state.busy = true; input.value = 'hi'; await send();")
    assert out["lines"] == ["busy: wait for the current run to finish"]
    assert out["inputValue"] == "hi"
    assert out["posts"] == 0


@needs_node
@pytest.mark.parametrize("call", ['sendAgui("hi")', 'sendA2a("hi")'])
def test_run_paths_pass_the_same_signal_to_the_retry_wait(call):
    out = _node_run([], f"state.abort = new AbortController(); await {call};")
    assert out["retrySignalMatches"] is True
