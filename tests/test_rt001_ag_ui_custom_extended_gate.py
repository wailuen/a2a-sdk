"""RT-001 — AG-UI A2UI_UPDATE must not be suppressed for Extended types under tier='core'.

LRN-049: CUSTOM events (A2UI_UPDATE) must be gated ONLY on tier=='none'.
Reusing the A2A DataPart extended/catalog gate (translate()/allows()) over-suppresses
Extended standard-profile types when the client claims tier='core'.
"""

from __future__ import annotations

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.events import ArtifactEvent
from agent_sdk.models.content_types import WaterfallChart, WaterfallSegment
from agent_sdk.routes.ag_ui import _RunMapper


def _waterfall() -> WaterfallChart:
    return WaterfallChart(
        title="Revenue Bridge",
        segments=[WaterfallSegment(label="Start", value=100.0, type="initial", cumulative=100.0)],
    )


def _mapper(tier: str) -> _RunMapper:
    return _RunMapper(
        thread_id="t1",
        run_id="r1",
        capabilities=A2uiCapabilities(tier=tier),
    )


def _a2ui_frames(mapper: _RunMapper, payload: WaterfallChart) -> list[dict]:
    event = ArtifactEvent(
        data_type=WaterfallChart.data_type,
        tool_name="test_tool",
        model=payload,
    )
    frames = mapper.map(event)
    return [f for f in frames if f.get("type") == "CUSTOM" and f.get("name") == "A2UI_UPDATE"]


def test_extended_type_emits_a2ui_update_under_tier_core():
    """An Extended ContentModel (WaterfallChart) with tier='core' must still
    produce an A2UI_UPDATE CUSTOM frame — suppression only on tier='none'."""
    mapper = _mapper("core")
    a2ui = _a2ui_frames(mapper, _waterfall())
    assert a2ui, (
        "A2UI_UPDATE missing for Extended type under tier='core'; "
        "CUSTOM events must be suppressed only on tier='none'"
    )


def test_extended_type_emits_a2ui_update_under_tier_core_extended():
    """Sanity: Extended type with tier='core+extended' must also emit A2UI_UPDATE."""
    mapper = _mapper("core+extended")
    a2ui = _a2ui_frames(mapper, _waterfall())
    assert a2ui, "A2UI_UPDATE missing for Extended type under tier='core+extended'"


def test_extended_type_suppressed_under_tier_none():
    """Extended type with tier='none' must NOT emit A2UI_UPDATE."""
    mapper = _mapper("none")
    a2ui = _a2ui_frames(mapper, _waterfall())
    assert not a2ui, "A2UI_UPDATE emitted under tier='none'; should be suppressed"
