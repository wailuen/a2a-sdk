"""GH-74: _capabilities() must fail-closed (tier='none') when
forwardedProps.a2uiClientCapabilities is absent — never fail-open to tier='core'.
"""

from __future__ import annotations

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.routes.ag_ui import _capabilities
from agent_sdk.testing import reply, tool_call

from .conftest import sse_frames


# ── unit: _capabilities() ──


def test_capabilities_absent_key_returns_none_tier():
    """No a2uiClientCapabilities key → tier='none' (fail-closed)."""
    body = {"forwardedProps": {}}
    caps = _capabilities(body, a2ui_enabled=True)
    assert caps.tier == "none"


def test_capabilities_absent_forwardedProps_returns_none_tier():
    """No forwardedProps at all → tier='none'."""
    body = {}
    caps = _capabilities(body, a2ui_enabled=True)
    assert caps.tier == "none"


def test_capabilities_explicit_core_tier():
    """Explicit tier='core' is preserved."""
    body = {"forwardedProps": {"a2uiClientCapabilities": {"tier": "core"}}}
    caps = _capabilities(body, a2ui_enabled=True)
    assert caps.tier == "core"


def test_capabilities_explicit_extended_tier():
    """Explicit tier='core+extended' is preserved."""
    body = {"forwardedProps": {"a2uiClientCapabilities": {"tier": "core+extended"}}}
    caps = _capabilities(body, a2ui_enabled=True)
    assert caps.tier == "core+extended"


def test_from_metadata_unchanged_for_none():
    """from_metadata(None) still returns the default tier='core' — not changed."""
    caps = A2uiCapabilities.from_metadata(None)
    assert caps.tier == "core"


# ── integration: AG-UI SSE stream ──


def run_body(text: str = "hello", **extra) -> dict:
    return {
        "threadId": "t1",
        "runId": "r1",
        "messages": [{"id": "m1", "role": "user", "content": text}],
        "state": {},
        "tools": [],
        "context": [],
        **extra,
    }


async def ag_run(client, body) -> list[dict]:
    r = await client.post("/ag-ui/run", json=body)
    assert r.status_code == 200, r.text
    return sse_frames(r.text)


@pytest.mark.asyncio
async def test_no_a2ui_update_when_capabilities_absent(client, fake_model):
    """AG-UI run with no forwardedProps.a2uiClientCapabilities must produce
    zero A2UI_UPDATE CUSTOM frames."""
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    # forwardedProps present but no a2uiClientCapabilities key
    frames = await ag_run(client, run_body("kpis", forwardedProps={}))
    custom_names = [f["name"] for f in frames if f["type"] == "CUSTOM"]
    assert "A2UI_UPDATE" not in custom_names, (
        f"A2UI_UPDATE emitted despite absent capability claim: {custom_names}"
    )


@pytest.mark.asyncio
async def test_no_a2ui_update_when_no_forwarded_props(client, fake_model):
    """AG-UI run with no forwardedProps at all must produce zero A2UI_UPDATE frames."""
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    frames = await ag_run(client, run_body("kpis"))
    custom_names = [f["name"] for f in frames if f["type"] == "CUSTOM"]
    assert "A2UI_UPDATE" not in custom_names, (
        f"A2UI_UPDATE emitted despite no forwardedProps: {custom_names}"
    )


@pytest.mark.asyncio
async def test_a2ui_update_present_when_tier_core(client, fake_model):
    """AG-UI run with forwardedProps.a2uiClientCapabilities: {tier: core}
    must still produce A2UI_UPDATE frames."""
    fake_model.script(tool_call("demo_kpis", {"title": "Q2"}), reply("done"))
    frames = await ag_run(
        client,
        run_body(
            "kpis",
            forwardedProps={"a2uiClientCapabilities": {"tier": "core"}},
        ),
    )
    custom_names = [f["name"] for f in frames if f["type"] == "CUSTOM"]
    assert "A2UI_UPDATE" in custom_names, (
        f"A2UI_UPDATE missing despite explicit tier=core: {custom_names}"
    )
