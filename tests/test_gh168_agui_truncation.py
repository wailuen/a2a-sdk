"""GH-168: AG-UI history truncation keeps head and tail with a marker."""
import logging

import pytest
from pydantic import ValidationError

from agent_sdk.config import BaseAgentSettings
from agent_sdk.routes.ag_ui import _fold_history


def _text(folded, i=-1):
    return folded[i]["content"][0]["text"]


def _msgs(assistant):
    return [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": assistant},
        {"role": "user", "content": "next"},
    ]


def test_default_setting_is_32000():
    s = BaseAgentSettings(_env_file=None, DEV_MODE=True)
    assert s.agui_max_message_chars == 32000


def test_setting_overrides_default(monkeypatch):
    monkeypatch.setenv("AGENT_SDK_AGUI_MAX_MESSAGE_CHARS", "5000")
    s = BaseAgentSettings(_env_file=None, DEV_MODE=True)
    assert s.agui_max_message_chars == 5000


@pytest.mark.parametrize("bad", ["999", "0", "-1", "abc"])
def test_invalid_setting_fails_boot(monkeypatch, bad):
    monkeypatch.setenv("AGENT_SDK_AGUI_MAX_MESSAGE_CHARS", bad)
    with pytest.raises(ValidationError):
        BaseAgentSettings(_env_file=None, DEV_MODE=True)


def test_over_limit_keeps_head_tail_and_marker(caplog):
    body = "HEAD" + "x" * 5000 + "TAIL-ID-9f3a"
    with caplog.at_level(logging.WARNING, logger="agent_sdk.ag_ui"):
        folded = _fold_history(_msgs(body), max_chars=1000)
    out = _text(folded, 1)
    assert len(out) <= 1000
    assert out.startswith("HEAD")
    assert out.endswith("TAIL-ID-9f3a")
    assert "[... " in out and " chars omitted ...]" in out
    omitted = int(out.split("[... ")[1].split(" chars")[0])
    assert omitted == len(body) - (len(out) - len(f"\n[... {omitted} chars omitted ...]\n"))
    assert "truncated" in caplog.text


def test_control_chars_stripped_before_cut():
    body = "a" * 600 + "\x00" * 500 + "b" * 600
    out = _text(_fold_history(_msgs(body), max_chars=1300), 1)
    assert out == "a" * 600 + "b" * 600


def test_under_limit_unchanged():
    body = "y" * 1000
    assert _text(_fold_history(_msgs(body), max_chars=1000), 1) == body
    assert _text(_fold_history(_msgs(body), 32000), 1) == body


async def test_route_uses_configured_limit(monkeypatch, tmp_path, fake_model):
    import gc

    import httpx

    from agent_sdk.example.agent import make_agent
    from agent_sdk.testing import reply

    from .conftest import sse_frames

    monkeypatch.setenv("AGENT_SDK_AGUI_MAX_MESSAGE_CHARS", "1000")
    settings = BaseAgentSettings(
        _env_file=None, DEV_MODE=True, DATA_DIR=str(tmp_path / "data"), AGENT_NAME="t"
    )
    app = make_agent(settings, model_client=fake_model).build_app()
    fake_model.script(reply("ok"))
    body = {
        "threadId": "t1",
        "runId": "r1",
        "messages": [
            {"id": "m1", "role": "user", "content": "hi"},
            {"id": "m2", "role": "assistant", "content": "A" * 5000 + " TAILID-42"},
            {"id": "m3", "role": "user", "content": "next"},
        ],
        "state": {},
        "tools": [],
        "context": [],
        "forwardedProps": {},
    }
    try:
        async with app.router.lifespan_context(app):
            _, token = app.state.auth.api_keys.mint("t", admin=True)
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
                headers={"Authorization": f"Bearer {token}"},
            ) as c:
                r = await c.post("/ag-ui/run", json=body)
        assert r.status_code == 200
        assert sse_frames(r.text)
    finally:
        app.state.credential_store.close()
        gc.collect()
    texts = [
        p["text"]
        for m in fake_model.calls[0]["messages"]
        if m["role"] == "assistant"
        for p in m["content"]
        if "text" in p
    ]
    assert texts
    assert len(texts[0]) <= 1000
    assert texts[0].endswith("TAILID-42")
    assert "omitted" in texts[0].lower() or "truncat" in texts[0].lower()
