"""GH-154: per-task current-date line appended last to the system prompt."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone

import httpx
import pytest

from agent_sdk import BaseAgentSettings
from agent_sdk.agent import runner
from agent_sdk.agent.runner import current_date_line
from agent_sdk.example.agent import make_agent
from agent_sdk.testing import FakeModelClient, reply

from .test_a2a import send_body, wait_for_state
from .test_ag_ui import run, run_body


def test_current_date_line_utc():
    now = datetime(2026, 3, 4, 23, 30, tzinfo=timezone.utc)
    assert current_date_line("UTC", now=now) == "Today is 2026-03-04 (UTC)."


def test_current_date_line_zone_shifts_date():
    now = datetime(2026, 3, 4, 23, 30, tzinfo=timezone.utc)
    assert (
        current_date_line("Asia/Singapore", now=now)
        == "Today is 2026-03-05 (Asia/Singapore)."
    )


def test_invalid_timezone_fails_boot(tmp_path):
    with pytest.raises(ValueError, match="TIMEZONE"):
        BaseAgentSettings(
            DEV_MODE=True, DATA_DIR=str(tmp_path), AGENT_NAME="a",
            AGENT_SDK_TIMEZONE="Mars/Base",
        )


def _build(tmp_path, **env):
    fm = FakeModelClient()
    s = BaseAgentSettings(
        DEV_MODE=True, DATA_DIR=str(tmp_path / "d"), AGENT_NAME="a", **env
    )
    return make_agent(s, model_client=fm).build_app(), fm


async def _client(app):
    _, token = app.state.auth.api_keys.mint("t", admin=True)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


def _clock(monkeypatch, values):
    it = iter(values)
    monkeypatch.setattr(runner, "_clock_now", lambda: next(it))


async def _a2a(c, text="hi", metadata=None):
    body = send_body(text)
    if metadata is not None:
        body["message"]["metadata"] = metadata
    r = await c.post("/v1/message:send", json=body)
    assert r.status_code == 200
    await wait_for_state(c, r.json()["id"])


async def test_two_tasks_across_midnight(tmp_path, monkeypatch):
    app, fm = _build(tmp_path)
    fm.script(reply("a"), reply("b"))
    _clock(monkeypatch, [
        datetime(2026, 1, 1, 23, 59, tzinfo=timezone.utc),
        datetime(2026, 1, 2, 0, 1, tzinfo=timezone.utc),
    ])
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            await _a2a(c)
            await _a2a(c)
    assert fm.calls[0]["system"].endswith("\n\nToday is 2026-01-01 (UTC).")
    assert fm.calls[1]["system"].endswith("\n\nToday is 2026-01-02 (UTC).")
    assert app.state.system_prompt not in ("",) and "Today is" not in app.state.system_prompt


async def test_a2a_user_zone_overrides(tmp_path, monkeypatch):
    app, fm = _build(tmp_path)
    fm.script(reply("a"), reply("b"))
    now = datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)
    _clock(monkeypatch, [now, now])
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            await _a2a(c, metadata={"timezone": "Asia/Tokyo"})
            await _a2a(c, metadata={"timezone": "../../etc/passwd"})
    assert fm.calls[0]["system"].endswith("Today is 2026-01-02 (Asia/Tokyo).")
    assert fm.calls[1]["system"].endswith("Today is 2026-01-01 (UTC).")


async def test_ag_ui_user_zone_and_fallback(tmp_path, monkeypatch):
    app, fm = _build(tmp_path)
    fm.script(reply("a"), reply("b"), reply("c"))
    now = datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)
    _clock(monkeypatch, [now, now, now])
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            await run(c, run_body(forwardedProps={"timezone": "Asia/Tokyo"}))
            await run(c, run_body(forwardedProps={"timezone": "Nope/Zone"}))
            await run(c, run_body(forwardedProps={"timezone": "A" * 500}))
    assert fm.calls[0]["system"].endswith("Today is 2026-01-02 (Asia/Tokyo).")
    assert fm.calls[1]["system"].endswith("Today is 2026-01-01 (UTC).")
    assert fm.calls[2]["system"].endswith("Today is 2026-01-01 (UTC).")


async def test_agent_zone_setting(tmp_path, monkeypatch):
    app, fm = _build(tmp_path, AGENT_SDK_TIMEZONE="Asia/Singapore")
    fm.script(reply("a"))
    _clock(monkeypatch, [datetime(2026, 1, 1, 20, 0, tzinfo=timezone.utc)])
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            await _a2a(c)
    assert fm.calls[0]["system"].endswith("Today is 2026-01-02 (Asia/Singapore).")


async def test_disabled_is_byte_identical(tmp_path):
    app, fm = _build(tmp_path, AGENT_SDK_INJECT_CURRENT_DATE="false")
    fm.script(reply("a"))
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            await _a2a(c)
    assert fm.calls[0]["system"] == app.state.system_prompt


async def test_resumed_task_reuses_original_date(tmp_path, monkeypatch):
    app, fm = _build(tmp_path)
    fm.script(reply("a"))
    _clock(monkeypatch, [datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc)])
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            await _a2a(c)
            rec = next(iter(app.state.task_store._records.values())) if hasattr(
                app.state.task_store, "_records") else None
    if rec is not None:
        assert rec.date_line == "Today is 2026-01-01 (UTC)."


async def test_hostile_zone_never_leaks(tmp_path, monkeypatch, sdk_caplog):
    import json
    import logging
    import uuid

    marker = f"IGNORE-PRIOR-{uuid.uuid4().hex}"
    hostile = f"Asia/Tokyo\n{marker}\x00"
    app, fm = _build(tmp_path)
    fm.script(reply("a"), reply("b"))
    now = datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)
    _clock(monkeypatch, [now, now])
    # RT-003 (w045 round 7): build_app() above ran configure_logging(), which
    # can switch agent_sdk.propagate off mid-test, so root caplog may capture
    # nothing. Attach a handler straight to the agent_sdk logger AFTER the
    # build (configure_logging resets its level on first call) and prove the
    # capture works with a positive control before the negative assertions.
    control = f"control-{uuid.uuid4().hex}"
    formatter = logging.Formatter("%(message)s %(exc_text)s")
    with sdk_caplog("agent_sdk", logging.DEBUG) as records:
        logging.getLogger("agent_sdk.agent.runner").debug(control)
        out: dict = {}
        await _drive_hostile(app, hostile, out)
    log_text = "\n".join(formatter.format(r) for r in records)
    assert control in log_text
    task_json, ag_text = out["task_json"], out["ag_text"]
    assert marker not in log_text
    assert "\x00" not in log_text
    assert marker not in task_json
    assert marker not in json.dumps(ag_text, default=str)
    assert len(fm.calls) == 2
    for call in fm.calls:
        assert marker not in call["system"]
        assert "\x00" not in call["system"]
        assert call["system"].endswith("\n\nToday is 2026-01-01 (UTC).")


async def _drive_hostile(app, hostile, out):
    async with app.router.lifespan_context(app):
        async with await _client(app) as c:
            body = send_body("hi")
            body["message"]["metadata"] = {"timezone": hostile}
            r = await c.post("/v1/message:send", json=body)
            assert r.status_code == 200
            tid = r.json()["id"]
            await wait_for_state(c, tid)
            task_json = json.dumps((await c.get(f"/v1/tasks/{tid}")).json()["status"])
            out["ag_text"] = await run(c, run_body(forwardedProps={"timezone": hostile}))
            out["task_json"] = task_json


def test_default_boots_without_zone_data(tmp_path, monkeypatch):
    # RT-001 (w045 round 7): Windows / Alpine / distroless hosts have no
    # system zone data. The default zone (UTC) must not need any, and with
    # injection off no zone is loaded at all.
    import sys
    import zoneinfo

    # Block the pip fallback, including submodules an earlier test already
    # imported (zoneinfo reads from the cached `tzdata.zoneinfo` package).
    for name in [m for m in sys.modules if m == "tzdata" or m.startswith("tzdata.")]:
        monkeypatch.setitem(sys.modules, name, None)
    monkeypatch.setitem(sys.modules, "tzdata", None)
    zoneinfo.reset_tzpath([])
    zoneinfo.ZoneInfo.clear_cache()
    try:
        with pytest.raises(zoneinfo.ZoneInfoNotFoundError):
            zoneinfo.ZoneInfo("UTC")  # control: zone data really is gone
        s = BaseAgentSettings(DEV_MODE=True, DATA_DIR=str(tmp_path), AGENT_NAME="a")
        assert s.timezone == "UTC"
        now = datetime(2026, 3, 4, 23, 30, tzinfo=timezone.utc)
        assert current_date_line(s.timezone, now=now) == "Today is 2026-03-04 (UTC)."
        assert runner.valid_timezone("UTC") == "UTC"
        assert runner.valid_timezone("Asia/Tokyo") is None  # falls back, no raise
        off = BaseAgentSettings(
            DEV_MODE=True, DATA_DIR=str(tmp_path), AGENT_NAME="a",
            AGENT_SDK_INJECT_CURRENT_DATE="false", AGENT_SDK_TIMEZONE="Asia/Tokyo",
        )
        assert off.timezone == "Asia/Tokyo"
        with pytest.raises(ValueError, match="tzdata"):
            BaseAgentSettings(
                DEV_MODE=True, DATA_DIR=str(tmp_path), AGENT_NAME="a",
                AGENT_SDK_TIMEZONE="Asia/Tokyo",
            )
    finally:
        zoneinfo.reset_tzpath()
        zoneinfo.ZoneInfo.clear_cache()
