"""RT-004: build_artifact() must not emit an empty open A2UI DataPart.

split_a2ui_delivery() partitions translate() output into (open, close)
arrays. The close DataPart is only appended when close_messages is
non-empty (runner.py); the open DataPart was appended unconditionally,
so a translate() output that is entirely deleteSurface (open_messages
== []) produced a {"messages": []} DataPart instead of failing
deterministically. The SDK's own translate() always emits createSurface
first, so this is latent for Standard Profile / registered domain types
today — it guards against a future custom translate() output.
"""

from __future__ import annotations

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent import runner as runner_module
from agent_sdk.agent.events import ArtifactEvent
from agent_sdk.agent.runner import build_artifact
from agent_sdk.models.content_types import KpiCard, MetricItem


def test_rt004_all_delete_surface_translate_output_raises(monkeypatch):
    payload = KpiCard(metrics=[MetricItem(label="A", value=1)])
    event = ArtifactEvent(data_type=payload.data_type, tool_name="test_tool", model=payload)

    def _fake_translate(payload, *, capabilities=None, **kwargs):
        return [{"version": "v0.9.1", "deleteSurface": {"surfaceId": "surface-x"}}]

    monkeypatch.setattr(runner_module, "translate", _fake_translate)

    caps = A2uiCapabilities(tier="core", catalogs=["urn:a2ui-profile:standard:v1"])
    with pytest.raises(ValueError, match="empty open"):
        build_artifact(event, caps)


def test_rt004_normal_translate_output_unaffected():
    """Sanity: the SDK's own translate() (create/update/update/delete) still
    produces a non-empty open sequence and build_artifact() succeeds."""
    payload = KpiCard(metrics=[MetricItem(label="A", value=1)])
    event = ArtifactEvent(data_type=payload.data_type, tool_name="test_tool", model=payload)
    caps = A2uiCapabilities(tier="core", catalogs=["urn:a2ui-profile:standard:v1"])

    artifact = build_artifact(event, caps)

    assert artifact is not None
    assert len(artifact.parts) == 3
