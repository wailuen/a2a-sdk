"""GH-191: console chat retry policy (retry.js run under node) + chat.js wiring."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

STATIC = Path(__file__).resolve().parent.parent / "agent_sdk" / "console" / "static"
CHAT_JS = (STATIC / "chat.js").read_text()

DRIVER = r"""
import { postWithRetry, decideRetry, parseRetryAfter } from "%s";
const out = {};
const mk = (status, ra) => ({ ok: status < 300, status, headers: { get: () => ra ?? null }, text: async () => "body" });
async function run(responses) {
  const lines = [], waits = []; let calls = 0;
  const resp = await postWithRetry(
    async () => { const r = responses[Math.min(calls++, responses.length - 1)]; if (r instanceof Error) throw r; return r; },
    { systemLine: (t) => lines.push(t), traceFrame() {}, label: "run request", sleep: async (ms) => waits.push(ms) });
  return { ok: resp !== null, calls, waits, lines };
}
for (const s of [400, 401, 403, 404, 413, 415, 422, 500]) out["no" + s] = await run([mk(s)]);
out.ra = await run([mk(429, "7"), mk(200)]);
out.cap = await run([mk(503, "999"), mk(200)]);
out.missing = await run([mk(429), mk(429), mk(200)]);
out.exhaust = await run([mk(429, "1")]);
out.net = await run([new Error("x"), mk(200)]);
out.netExhaust = await run([new Error("x")]);
out.parse = [parseRetryAfter("5"), parseRetryAfter("junk"), parseRetryAfter(null)];
console.log(JSON.stringify(out));
"""


@pytest.fixture(scope="module")
def result(tmp_path_factory: pytest.TempPathFactory) -> dict:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not available")
    d = tmp_path_factory.mktemp("js")
    f = d / "driver.mjs"
    f.write_text(DRIVER % (STATIC / "retry.js").as_posix())
    p = subprocess.run([node, str(f)], capture_output=True, text=True, timeout=30)
    assert p.returncode == 0, p.stderr
    return json.loads(p.stdout)


@pytest.mark.parametrize("status", [400, 401, 403, 404, 413, 415, 422, 500])
def test_no_retry_statuses_fail_on_first_response(result: dict, status: int) -> None:
    r = result[f"no{status}"]
    assert r["calls"] == 1 and not r["ok"] and r["waits"] == []
    assert f"HTTP {status}" in r["lines"][-1]


def test_retry_after_header_is_honoured(result: dict) -> None:
    assert result["ra"]["waits"] == [7000] and result["ra"]["ok"]


def test_retry_after_capped_at_30s(result: dict) -> None:
    assert result["cap"]["waits"] == [30000]


def test_missing_header_uses_backoff(result: dict) -> None:
    assert result["missing"]["waits"] == [1000, 2000] and result["missing"]["ok"]


def test_retries_are_bounded(result: dict) -> None:
    r = result["exhaust"]
    assert not r["ok"] and r["calls"] == 4


def test_network_failure_retries_then_gives_up(result: dict) -> None:
    assert result["net"]["ok"] and result["net"]["calls"] == 2
    assert not result["netExhaust"]["ok"]


def test_parse_retry_after(result: dict) -> None:
    assert result["parse"] == [5000, None, None]


def test_chat_js_uses_policy_and_does_not_repost_after_drop() -> None:
    assert "postWithRetry" in CHAT_JS
    assert "prevents server-side duplicate-run rejection" not in CHAT_JS
    assert "body.runId = uuid(); // fresh" not in CHAT_JS
    assert "was not resent" in CHAT_JS
    assert CHAT_JS.count("postSse(`${state.base}/ag-ui/run`") == 1


def test_all_console_js_files_parse(tmp_path: Path) -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node not installed")
    files = sorted(STATIC.glob("*.js"))
    assert files
    for f in files:
        copy = tmp_path / (f.stem + ".mjs")
        copy.write_text(f.read_text())
        proc = subprocess.run([node, "--check", str(copy)], capture_output=True, text=True)
        assert proc.returncode == 0, f"{f.name}: {proc.stderr[:300]}"
