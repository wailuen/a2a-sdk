"""echo-analyst assembly — the §4.1 shape, with no external services."""

from __future__ import annotations

import asyncio
from typing import Any

from pydantic import BaseModel, Field

from ..agent.loop import ToolInterrupt
from ..agent.registry import ToolSet
from ..app import Agent
from ..config import BaseAgentSettings
from ..models.content_types import (
    KpiCard,
    MetricItem,
    TimeSeriesChart,
    TimeSeriesDataPoint,
)


tools = ToolSet()


class EchoInput(BaseModel):
    text: str = Field(description="Text to echo back")


@tools.tool(tier=1, read_only=True, title="Echo", tags=["demo", "echo"])
async def echo(inp: EchoInput) -> dict[str, Any]:
    """Echo the input text back, reversed and as-is."""
    return {"text": inp.text, "reversed": inp.text[::-1], "length": len(inp.text)}


class KpiInput(BaseModel):
    title: str = Field(description="Title for the KPI card")


@tools.tool(tier=1, emits=KpiCard, sample={"title": "Demo KPIs"}, read_only=True, title="Demo Kpis", tags=["demo", "kpi"])
async def demo_kpis(inp: KpiInput) -> KpiCard:
    """Produce a demonstration KPI card with fixed sample metrics."""
    return KpiCard(
        title=inp.title,
        metrics=[
            MetricItem(label="Revenue", value="$1.2M", trend="up", change_pct=5.0),
            MetricItem(label="Churn", value="2.1%", trend="down", change_pct=-0.4),
        ],
    )


class TrendInput(BaseModel):
    series_name: str = Field(description="Name of the demo series")
    points: int = Field(default=6, ge=2, le=24, description="Number of points")


@tools.tool(tier=2, emits=TimeSeriesChart, sample={"series_name": "demo", "points": 6}, title="Demo Trend", tags=["demo", "chart"])
async def demo_trend(inp: TrendInput) -> TimeSeriesChart:
    """Produce a demonstration time series (composite Tier 2 tool)."""
    await asyncio.sleep(0)  # exercise the async path
    data = [
        TimeSeriesDataPoint(date=f"2026-{month:02d}-01", value=100.0 + 7.5 * i)
        for i, month in enumerate(range(1, inp.points + 1))
    ]
    return TimeSeriesChart(chart_type="line", title=inp.series_name, data=data)


class PublishInput(BaseModel):
    note: str = Field(description="Note to publish")


@tools.tool(tier=2, title="Publish Note", tags=["demo", "publish"])
async def publish_note(inp: PublishInput) -> dict[str, Any]:
    """Publish a note (requires user confirmation — interrupt demo)."""

    async def confirmed(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            payload = value.get("payload")
            status = value.get("status")
            if status in (None, "resolved") and isinstance(payload, dict):
                status = payload.get("decision") or payload.get("status")
        else:
            status = value
        if str(status).lower() in ("approved", "yes", "confirm", "true"):
            return {"published": True, "note": inp.note}
        return {"published": False, "reason": "user declined"}

    raise ToolInterrupt(
        reason="confirmation",
        message=f"Publish this note? {inp.note!r}",
        response_schema={
            "type": "object",
            "properties": {"status": {"enum": ["approved", "denied"]}},
            "required": ["status"],
        },
        resume_handler=confirmed,
    )


def make_agent(settings: BaseAgentSettings | None = None, **agent_kwargs: Any) -> Agent:
    from pathlib import Path

    return Agent(
        settings=settings or BaseAgentSettings(),
        artifacts_dir=Path(__file__).parent / "artifacts",
        skills_dir=Path(__file__).parent / "skills",
        toolsets=[tools],
        **agent_kwargs,
    )
