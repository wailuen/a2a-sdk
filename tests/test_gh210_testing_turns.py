"""GH-210: throttled, retrying A2A + AG-UI turn helper (agent_sdk.testing.turns)."""

from __future__ import annotations

import json
import logging
import subprocess
import sys
from pathlib import Path

import httpx
import pytest

from agent_sdk.testing import turns
from agent_sdk.testing.turns import SlotLimiter, run_turn

SECRET = "sk-SECRET-KEY-VALUE"
QUERY = "confidential-user-query-xyz"
BODY = "raw-upstream-body-abc"


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    async def fast(_s):
        return None

    monkeypatch.setattr(turns, "_sleep", fast)


@pytest.fixture
def key_file(tmp_path):
    p = tmp_path / "key"
    p.write_text(SECRET + "\n")
    return p


def _sse(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events).encode()


def _a2a_ok(text="hello"):
    return _sse(
        {"kind": "task", "id": "t1", "contextId": "c1"},
        {
            "kind": "status-update", "taskId": "t1", "contextId": "c1", "final": True,
            "status": {"state": "completed", "message": {"parts": [{"kind": "text", "text": text}]}},
        },
    )


def _client(handler):
    return httpx.AsyncClient(base_url="http://t", transport=httpx.MockTransport(handler),
                             headers={"Authorization": f"Bearer {SECRET}"})


async def _a2a(tmp_path, key_file, handler, **kw):
    async with _client(handler) as c:
        return await run_turn(
            transport="a2a", base_url="http://t", key_file=key_file, query=QUERY,
            run_key="r1", state_dir=tmp_path / "state", client=c, **kw,
        )


@pytest.mark.asyncio
async def test_429_then_success_is_retried_and_scored_on_success(tmp_path, key_file):
    calls = []

    def handler(req):
        calls.append(1)
        if len(calls) == 1:
            return httpx.Response(429, content=BODY.encode())
        return httpx.Response(200, content=_a2a_ok("fine"))

    out = await _a2a(tmp_path, key_file, handler)
    assert out["ok"] is True and out["reply"] == "fine"
    assert out["attempts"] == 2 and len(calls) == 2
    assert "failureClass" not in out or out["failureClass"] != "rate-limited"
    sd = tmp_path / "state"
    assert (sd / "acc-r1-a2a-task.txt").read_text() == "t1"
    assert (sd / "acc-r1-a2a-ctx.txt").read_text() == "c1"


@pytest.mark.asyncio
async def test_a2a_ids_not_written_on_failure(tmp_path, key_file):
    def handler(req):
        return httpx.Response(429)

    out = await _a2a(tmp_path, key_file, handler, budget_s=5)
    assert out["ok"] is False and out["failureClass"] == "rate-limited"
    sd = tmp_path / "state"
    assert not list(sd.glob("acc-r1-a2a-*")) if sd.exists() else True


@pytest.mark.asyncio
async def test_failed_task_and_empty_reply_are_retried(tmp_path, key_file):
    seq = [
        _sse({"kind": "task", "id": "t1", "contextId": "c1"},
             {"kind": "status-update", "taskId": "t1", "contextId": "c1", "final": True,
              "status": {"state": "failed"}}),
        _sse({"kind": "task", "id": "t2", "contextId": "c2"},
             {"kind": "status-update", "taskId": "t2", "contextId": "c2", "final": True,
              "status": {"state": "completed"}}),
        _a2a_ok("third"),
    ]
    it = iter(seq)
    out = await _a2a(tmp_path, key_file, lambda req: httpx.Response(200, content=next(it)))
    assert out["ok"] and out["reply"] == "third" and out["attempts"] == 3


def _a2a_failed(text):
    return _sse(
        {"kind": "task", "id": "t1", "contextId": "c1"},
        {"kind": "status-update", "taskId": "t1", "contextId": "c1", "final": True,
         "status": {"state": "failed", "message": {"parts": [{"kind": "text", "text": text}]}}},
    )


@pytest.mark.asyncio
async def test_too_many_requests_text_on_failed_task_is_retried(tmp_path, key_file):
    seq = iter([_a2a_failed("Too Many Requests, slow down"), _a2a_ok("ok now")])
    out = await _a2a(tmp_path, key_file, lambda req: httpx.Response(200, content=next(seq)))
    assert out["ok"] and out["reply"] == "ok now" and out["attempts"] == 2


@pytest.mark.asyncio
async def test_completed_reply_mentioning_rate_limit_is_not_retried(tmp_path, key_file):
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(200, content=_a2a_ok("Our API rate limit is 100 req/min."))

    out = await _a2a(tmp_path, key_file, handler)
    assert out["ok"] is True and out["attempts"] == 1 and len(calls) == 1


@pytest.mark.asyncio
async def test_agui_completed_reply_mentioning_rate_limit_is_not_retried(tmp_path, key_file):
    async with _client(lambda req: httpx.Response(200, content=_agui_ok("The rate limit is 5."))) as c:
        out = await run_turn(
            transport="agui", base_url="http://t", key_file=key_file, query=QUERY,
            run_key="r2", state_dir=tmp_path / "state", client=c,
        )
    assert out["ok"] is True and out["attempts"] == 1


@pytest.mark.asyncio
async def test_agui_run_error_too_many_requests_is_retried(tmp_path, key_file):
    seq = iter([
        _sse({"type": "RUN_ERROR", "message": "too many requests"}),
        _agui_ok("fine"),
    ])
    async with _client(lambda req: httpx.Response(200, content=next(seq))) as c:
        out = await run_turn(
            transport="agui", base_url="http://t", key_file=key_file, query=QUERY,
            run_key="r3", state_dir=tmp_path / "state", client=c,
        )
    assert out["ok"] is True and out["attempts"] == 2


@pytest.mark.asyncio
async def test_in_flight_attempt_is_bounded_by_budget(tmp_path, key_file):
    import asyncio
    import time

    async def handler(req):
        await asyncio.sleep(30)
        return httpx.Response(200, content=_a2a_ok())

    t0 = time.monotonic()
    out = await _a2a(tmp_path, key_file, handler, budget_s=0.5)
    assert time.monotonic() - t0 < 5
    assert out["ok"] is False and out["reason"] == "budget-exceeded"
    assert out["failureClass"] == "turn-failed"


@pytest.mark.asyncio
async def test_total_budget_enforced(tmp_path, key_file, monkeypatch):
    t = {"now": 0.0}
    monkeypatch.setattr(turns, "_now", lambda: t["now"])

    async def adv(s):
        t["now"] += s

    monkeypatch.setattr(turns, "_sleep", adv)
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(429)

    out = await _a2a(tmp_path, key_file, handler, budget_s=100)
    assert out["failureClass"] == "rate-limited"
    assert t["now"] <= 100
    assert turns.DEFAULT_BUDGET_S < 600


def _agui_ok(text="agui reply"):
    return _sse(
        {"type": "TEXT_MESSAGE_CONTENT", "delta": text},
        {"type": "RUN_FINISHED"},
    )


@pytest.mark.asyncio
async def test_agui_message_list_restored_after_failed_attempt(tmp_path, key_file):
    seen = []

    def handler(req):
        seen.append(json.loads(req.content)["messages"])
        if len(seen) == 1:
            return httpx.Response(429)
        return httpx.Response(200, content=_agui_ok())

    async with _client(handler) as c:
        out = await run_turn(
            transport="agui", base_url="http://t", key_file=key_file, query=QUERY,
            run_key="r2", state_dir=tmp_path / "state", client=c,
        )
    assert out["ok"] and out["reply"] == "agui reply"
    assert seen[0] == seen[1] == [{"role": "user", "content": QUERY}]
    saved = json.loads((tmp_path / "state" / "acc-r2-agui-msgs.json").read_text())
    assert [m["role"] for m in saved] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_agui_failure_leaves_state_file_untouched(tmp_path, key_file):
    sd = tmp_path / "state"
    sd.mkdir()
    f = sd / "acc-r3-agui-msgs.json"
    prior = [{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}]
    f.write_text(json.dumps(prior))
    async with _client(lambda req: httpx.Response(429)) as c:
        out = await run_turn(
            transport="agui", base_url="http://t", key_file=key_file, query=QUERY,
            run_key="r3", state_dir=sd, client=c, budget_s=5,
        )
    assert out["failureClass"] == "rate-limited"
    assert json.loads(f.read_text()) == prior


def test_slot_limit_enforced_across_processes(tmp_path):
    code = (
        "import sys,time\n"
        "from agent_sdk.testing.turns import SlotLimiter\n"
        "l=SlotLimiter(sys.argv[1],2)\n"
        "assert l.try_acquire() is not None\n"
        "print('held',flush=True)\n"
        "time.sleep(30)\n"
    )
    procs = [
        subprocess.Popen([sys.executable, "-c", code, str(tmp_path)],
                         stdout=subprocess.PIPE, text=True)
        for _ in range(2)
    ]
    try:
        for p in procs:
            assert p.stdout.readline().strip() == "held"
        assert SlotLimiter(tmp_path, 2).try_acquire() is None
        procs[0].kill()
        procs[0].wait()
        got = SlotLimiter(tmp_path, 2).try_acquire()
        assert got is not None
        got.release()
    finally:
        for p in procs:
            p.kill()
            p.wait()
            p.stdout.close()


def test_default_slot_count_is_three():
    assert turns.DEFAULT_SLOTS == 3


def test_helper_takes_key_file_not_key():
    import inspect

    params = inspect.signature(run_turn).parameters
    assert "key_file" in params
    assert not {"key", "token", "api_key"} & set(params)
    src = Path(turns.__file__).read_text()
    import re

    assert "getenv" not in src
    assert not re.search(r"environ[^\n]*(KEY|TOKEN|SECRET)", src, re.I)


@pytest.mark.asyncio
async def test_no_secret_in_state_lock_logs_or_record(tmp_path, key_file, caplog):
    caplog.set_level(logging.DEBUG)
    seq = iter([429, 200])

    def handler(req):
        assert req.headers["authorization"] == f"Bearer {SECRET}"
        return httpx.Response(next(seq), content=BODY.encode() if False else _a2a_ok())

    lock_dir = tmp_path / "locks"
    out = await _a2a(tmp_path, key_file, handler, lock_dir=lock_dir)
    assert out["ok"]

    async with _client(lambda req: httpx.Response(429, content=BODY.encode())) as c:
        bad = await run_turn(
            transport="a2a", base_url="http://t", key_file=key_file, query=QUERY,
            run_key="r9", state_dir=tmp_path / "state", lock_dir=lock_dir, client=c,
            budget_s=5,
        )
    blob = json.dumps(bad) + caplog.text
    for p in list((tmp_path / "state").rglob("*")) + list(lock_dir.rglob("*")):
        if p.is_file():
            blob += p.read_text(errors="ignore")
    for needle in (SECRET, "Authorization", "Bearer", BODY):
        assert needle not in blob
    assert QUERY not in json.dumps(bad) + caplog.text
    assert bad["status"] == 429 and bad["failureClass"] == "rate-limited"


def _acceptance_js() -> str:
    return (Path(__file__).resolve().parent.parent / "harness/workflows/acceptance-api.js").read_text()


def test_prompt_requires_bash_timeout_covering_helper_budget():
    js = _acceptance_js()
    assert js.count("timeout 600000 (ms)") == 2
    assert "score that transport 10" not in js


def test_rate_limited_result_is_never_counted_as_passed():
    js = _acceptance_js()
    assert "r.failureClass === 'rate-limited' ? Object.assign({}, r, { passed: false })" in js
    assert "not run (rate-limited)" in js


def test_template_mirror_is_identical():
    root = Path(__file__).resolve().parent.parent
    mirror = root / "template/.claude/workflows/acceptance-api.js"
    if mirror.exists():
        assert mirror.read_text() == _acceptance_js()
