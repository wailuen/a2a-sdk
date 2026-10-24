"""RT-001 — AG-UI ArtifactEvent branch must reject malformed A2UI wire output
identically to the A2A build_artifact() path (SC-D1 parity).

Mirrors test_rt004_open_delivery_guard.py::test_rt004_all_delete_surface_translate_output_raises.
Before this fix, ag_ui.py's ArtifactEvent branch called translate() then
split_a2ui_delivery() directly with no validation, so a translate() output
that is empty after dropping deleteSurface (empty open sequence) silently produced an
empty A2UI_UPDATE {"messages": []} frame and the run succeeded — while the
identical output on A2A failed the task deterministically (-32006). Both
transports must now reject identically.
"""

from __future__ import annotations

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.events import ArtifactEvent
from agent_sdk.models.content_types import KpiCard, MetricItem
from agent_sdk.routes import ag_ui as ag_ui_module
from agent_sdk.routes.ag_ui import _RunMapper


def test_rt001_all_delete_surface_translate_output_raises(monkeypatch):
    payload = KpiCard(metrics=[MetricItem(label="A", value=1)])
    event = ArtifactEvent(data_type=payload.data_type, tool_name="test_tool", model=payload)

    def _fake_translate(payload, *, capabilities=None, **kwargs):
        return [{"version": "v0.9.1", "deleteSurface": {"surfaceId": "surface-x"}}]

    monkeypatch.setattr(ag_ui_module, "translate", _fake_translate)

    mapper = _RunMapper(
        thread_id="t1",
        run_id="r1",
        capabilities=A2uiCapabilities(tier="core", catalogs=["urn:a2ui-profile:standard:v1"]),
    )
    with pytest.raises(ValueError, match="empty open"):
        mapper.map(event)


def test_rt001_normal_translate_output_unaffected():
    """Sanity: the SDK's own translate() output still succeeds and yields
    one A2UI_UPDATE frame (open only, GH-214), unaffected by the added guard."""
    payload = KpiCard(metrics=[MetricItem(label="A", value=1)])
    event = ArtifactEvent(data_type=payload.data_type, tool_name="test_tool", model=payload)
    mapper = _RunMapper(
        thread_id="t1",
        run_id="r1",
        capabilities=A2uiCapabilities(tier="core", catalogs=["urn:a2ui-profile:standard:v1"]),
    )
    frames = mapper.map(event)
    a2ui = [f for f in frames if f.get("type") == "CUSTOM" and f.get("name") == "A2UI_UPDATE"]
    assert len(a2ui) == 1
