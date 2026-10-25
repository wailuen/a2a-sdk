"""GH-257: one A2UI gate (app.state.a2ui_enabled) drives card, modes, capabilities.

Ruling: https://github.com/wailuen/a2a-sdk/issues/257#issuecomment-6393088260
"""
from __future__ import annotations

import gc
import uuid
from types import SimpleNamespace

import httpx
import pytest
from pydantic import BaseModel

from agent_sdk.agent.registry import ToolSet
from agent_sdk.app import Agent
from agent_sdk.example.agent import make_agent
from agent_sdk.models.content_types import A2UI_EXTENSION_URI, A2UI_MIME_TYPE
from agent_sdk.routes.a2a import _capabilities as a2a_capabilities
from agent_sdk.routes.agent_card import compute_a2ui_enabled
from agent_sdk.routes.ag_ui import _capabilities as ag_ui_capabilities
from agent_sdk.testing import FakeModelClient, reply, tool_call

from .conftest import sse_frames
from .test_ag_ui import run_body


class _In(BaseModel):
    x: str = "a"


def _plain_tools() -> ToolSet:
    ts = ToolSet()

    @ts.tool(tier=1, sample={"x": "a"})
    async def plain(inp: _In) -> dict:
        """No emits."""
        return {"x": inp.x}

    return ts


def _build(settings, model, emitting: bool):
    if emitting:
        return make_agent(settings, model_client=model).build_app()
    return Agent(settings=settings, persona="test", toolsets=[_plain_tools()], model_client=model).build_app()


async def _client(app):
    _, token = app.state.auth.api_keys.mint("t", admin=True)
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


def _msg(**extra) -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": "go"}],
            "messageId": uuid.uuid4().hex,
            "metadata": {"a2uiClientCapabilities": {"version": "v0.9.1", "tier": "core+extended"}},
        },
        **extra,
    }


def _has_a2ui(task: dict) -> bool:
    return any(
        (p.get("metadata") or {}).get("mimeType") == A2UI_MIME_TYPE
        for a in task.get("artifacts") or []
        for p in a["parts"]
    )


def test_helper_true_only_with_catalogs() -> None:
    assert compute_a2ui_enabled(None, []) is False
    from agent_sdk.models.content_types import KpiCard

    assert compute_a2ui_enabled(None, [KpiCard]) is True


def test_capabilities_helpers_gate_on_flag() -> None:
    msg = SimpleNamespace(metadata={"a2uiClientCapabilities": {"tier": "core"}})
    req = SimpleNamespace(headers={"x-a2a-extensions": A2UI_EXTENSION_URI})
    assert a2a_capabilities(msg, req, a2ui_enabled=False).tier == "none"  # type: ignore[arg-type]
    assert a2a_capabilities(msg, req, a2ui_enabled=True).tier != "none"  # type: ignore[arg-type]
    body = {"forwardedProps": {"a2uiClientCapabilities": {"tier": "core"}}}
    assert ag_ui_capabilities(body, a2ui_enabled=False).tier == "none"
    assert ag_ui_capabilities(body, a2ui_enabled=True).tier != "none"


@pytest.mark.parametrize("emitting", [False, True])
async def test_card_state_and_runtime_agree(settings, emitting) -> None:
    model = FakeModelClient()
    app = _build(settings, model, emitting)
    try:
        async with app.router.lifespan_context(app):
            enabled = app.state.a2ui_enabled
            assert enabled is emitting
            card = app.state.agent_card
            uris = [e["uri"] for e in card["capabilities"]["extensions"]]
            assert (A2UI_EXTENSION_URI in uris) is enabled
            assert ("application/a2ui+json" in card["defaultOutputModes"]) is enabled
            async with await _client(app) as c:
                if not emitting:
                    return
                model.script(tool_call("demo_kpis", {"title": "k"}), reply("done"))
                r = await c.post(
                    "/v1/message:send",
                    json=_msg(configuration={"blocking": True}),
                    headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
                )
                assert r.status_code == 200, r.text
                assert _has_a2ui(r.json()["result"] if "result" in r.json() else r.json())
    finally:
        app.state.credential_store.close()
        gc.collect()


async def test_modes_with_a2ui_off(settings) -> None:
    app = _build(settings, FakeModelClient(), False)
    try:
        async with app.router.lifespan_context(app):
            async with await _client(app) as c:
                r = await c.post(
                    "/v1/message:send",
                    json=_msg(configuration={"acceptedOutputModes": ["application/a2ui+json"]}),
                )
                assert r.json()["error"]["code"] == -32005
                for mode in ("application/*", "*/*"):
                    app.state.model_client = FakeModelClient().script(reply("ok"))
                    r = await c.post(
                        "/v1/message:send",
                        json=_msg(configuration={"acceptedOutputModes": [mode], "blocking": True}),
                    )
                    assert "error" not in r.json(), r.text
    finally:
        app.state.credential_store.close()
        gc.collect()


async def test_modes_with_a2ui_on_accept_a2ui_mime(settings) -> None:
    model = FakeModelClient().script(reply("ok"))
    app = _build(settings, model, True)
    try:
        async with app.router.lifespan_context(app):
            async with await _client(app) as c:
                cfg = {"acceptedOutputModes": ["application/a2ui+json"], "blocking": True}
                r = await c.post("/v1/message:send", json=_msg(configuration=cfg))
                assert r.status_code == 415
                assert r.json()["error"]["code"] == -32005
                r = await c.post(
                    "/v1/message:send",
                    json=_msg(configuration=cfg),
                    headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
                )
                assert "error" not in r.json(), r.text
    finally:
        app.state.credential_store.close()
        gc.collect()


def test_capabilities_helpers_fail_closed_without_argument() -> None:
    msg = SimpleNamespace(metadata={"a2uiClientCapabilities": {"tier": "core"}})
    req = SimpleNamespace(headers={"x-a2a-extensions": A2UI_EXTENSION_URI})
    assert a2a_capabilities(msg, req).tier == "none"  # type: ignore[arg-type]
    body = {"forwardedProps": {"a2uiClientCapabilities": {"tier": "core"}}}
    assert ag_ui_capabilities(body).tier == "none"


async def test_a2ui_off_content_model_tool_gets_no_a2ui_part(settings) -> None:
    model = FakeModelClient().script(tool_call("demo_kpis", {"title": "k"}), reply("done"))
    app = _build(settings, model, True)
    app.state.a2ui_enabled = False  # gate off while the tool still returns a ContentModel
    try:
        async with app.router.lifespan_context(app):
            async with await _client(app) as c:
                r = await c.post(
                    "/v1/message:send",
                    json=_msg(configuration={"blocking": True}),
                    headers={"X-A2A-Extensions": A2UI_EXTENSION_URI},
                )
                task = r.json()
                assert task["artifacts"], r.text
                assert not _has_a2ui(task)
    finally:
        app.state.credential_store.close()
        gc.collect()


async def test_ag_ui_off_drops_forwarded_caps(settings) -> None:
    model = FakeModelClient().script(tool_call("demo_kpis", {"title": "k"}), reply("done"))
    app = _build(settings, model, True)
    app.state.a2ui_enabled = False  # gate off while the tool still returns a ContentModel
    try:
        async with app.router.lifespan_context(app):
            async with await _client(app) as c:
                body = run_body(
                    "go",
                    forwardedProps={"a2uiClientCapabilities": {"version": "v0.9.1", "tier": "core+extended"}},
                )
                r = await c.post("/ag-ui/run", json=body)
                frames = sse_frames(r.text)
                assert any(f["type"] == "TOOL_CALL_RESULT" for f in frames), r.text
                assert not [f for f in frames if f["type"] == "CUSTOM" and f["name"] == "A2UI_UPDATE"]
    finally:
        app.state.credential_store.close()
        gc.collect()
