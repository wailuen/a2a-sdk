"""Sample ToolSet — replace with your real tools (/add-tool).

One ToolSet per module; main.py collects them explicitly. The docstring is
the tool description the model sees. Tier 1 = query (exposed over A2A and
MCP), tier 2 = composite (A2A only). ``emits=`` declares the structured
artifact type and must be a registered Profile/domain content type.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from agent_sdk import ToolSet
from agent_sdk.models.content_types import KpiCard, MetricItem

from ..sources.sample_api import SampleApiAdapter

tools = ToolSet()


class WidgetInput(BaseModel):
    widget_id: str = Field(description="Widget identifier")


@tools.tool(tier=1, sample={"widget_id": "w-123"})
async def get_widget(inp: WidgetInput, *, api: SampleApiAdapter) -> dict[str, Any]:
    """Fetch a widget by id from the sample API."""
    return await api.get_widget(inp.widget_id)


class WidgetKpisInput(BaseModel):
    widget_id: str = Field(description="Widget identifier")


@tools.tool(tier=1, emits=KpiCard, sample={"widget_id": "w-123"})
async def widget_kpis(inp: WidgetKpisInput, *, api: SampleApiAdapter) -> KpiCard:
    """Summarize a widget's key metrics as a KPI card."""
    widget = await api.get_widget(inp.widget_id)
    return KpiCard(
        title=f"Widget {inp.widget_id}",
        metrics=[
            MetricItem(label="Status", value=str(widget.get("status", "unknown"))),
            MetricItem(label="Score", value=str(widget.get("score", "n/a"))),
        ],
    )
