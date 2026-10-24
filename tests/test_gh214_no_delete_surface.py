"""GH-214: the SDK never emits deleteSurface for a surface in the artifact or
run that created it. Ruling: https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762

A spec renderer would paint each card and then unmount it. Surface lifetime is
client-managed; each turn uses a fresh surfaceId.
"""

from __future__ import annotations

import json

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities, translate
from agent_sdk.agent import runner as runner_module
from agent_sdk.agent.events import ArtifactEvent
from agent_sdk.agent.runner import build_artifact
from agent_sdk.models.content_types import KpiCard, MetricItem
from agent_sdk.routes.ag_ui import _RunMapper

_CAPS = A2uiCapabilities(tier="core", catalogs=["urn:a2ui-profile:standard:v1"])


def _event() -> ArtifactEvent:
    payload = KpiCard(metrics=[MetricItem(label="A", value=1)])
    return ArtifactEvent(data_type=payload.data_type, tool_name="t", model=payload)


def test_translate_emits_no_delete_surface():
    msgs = translate(KpiCard(metrics=[MetricItem(label="A", value=1)]), capabilities=_CAPS)
    assert msgs is not None
    assert [next(k for k in m if k != "version") for m in msgs] == [
        "createSurface",
        "updateComponents",
        "updateDataModel",
    ]


def test_a2a_artifact_is_text_plus_open_datapart():
    artifact = build_artifact(_event(), _CAPS)
    assert [p.kind for p in artifact.parts] == ["text", "data"]
    assert "deleteSurface" not in json.dumps(artifact.wire())


def test_ag_ui_emits_artifact_then_single_a2ui_update():
    mapper = _RunMapper(thread_id="t1", run_id="r1", capabilities=_CAPS)
    frames = mapper.map(_event())
    names = [f["name"] for f in frames if f.get("type") == "CUSTOM"]
    assert names == ["AGENT_ARTIFACT", "A2UI_UPDATE"]
    assert "deleteSurface" not in json.dumps(frames)


def test_custom_translate_delete_surface_is_not_delivered(monkeypatch):
    def _fake(payload, *, capabilities=None, **kwargs):
        return [
            {"version": "v0.9.1", "createSurface": {"surfaceId": "s", "catalogId": "c"}},
            {"version": "v0.9.1", "deleteSurface": {"surfaceId": "s"}},
        ]

    monkeypatch.setattr(runner_module, "translate", _fake)
    artifact = build_artifact(_event(), _CAPS)
    assert [p.kind for p in artifact.parts] == ["text", "data"]
    assert "deleteSurface" not in json.dumps(artifact.wire())


def test_empty_open_sequence_still_rejected(monkeypatch):
    monkeypatch.setattr(runner_module, "translate", lambda payload, **kw: [])
    with pytest.raises(ValueError, match="non-empty list"):
        build_artifact(_event(), _CAPS)


def test_agent_card_param_removed():
    from agent_sdk.a2ui.catalog import a2ui_extension

    assert "deleteSurfaceSemantics" not in a2ui_extension().params


def test_console_still_renders_surface_without_close():
    """The console keeps every surface mounted in the transcript: a2ui.js only
    unmounts on a received deleteSurface, which the SDK no longer sends.
    It must still accept one from another producer."""
    import pathlib

    js = pathlib.Path("agent_sdk/console/static/a2ui.js").read_text()
    assert "msg.deleteSurface" in js
    chat = pathlib.Path("agent_sdk/console/static/chat.js").read_text()
    assert "deleteSurface" not in chat
