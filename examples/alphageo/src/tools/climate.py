"""Climate-risk tools — every one emits a single ``ClimateRiskReport`` card.

The 6 tools mirror the original AlphaGeo MCP surface. Each calls
``AlphaGeoSource`` (which owns auth, host-checking, caching, throttling and
the Nominatim fallback) and normalizes the result into one ``ClimateRiskReport``
— the same domain card regardless of which endpoint produced the data, so a
renderer learns one component, not six.

``alphageo_get_full_report`` is the preferred entry point: it fans out all
periods + analytics + resilience concurrently and tolerates partial failure
via the card's ``section_errors`` map. The single-endpoint tools exist for
targeted follow-ups.

Inputs: ``scenario`` and ``period`` are constrained enums (the schema guides
the model so it rarely sends a bad value); ``address``/``latitude``/
``longitude`` are unconstrained so a provided value is never echoed back in a
validation error. Location validity (address OR lat+lon) is enforced inside
the adapter with a leak-free message.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from agent_sdk import ToolSet

from ..content import ClimateRiskReport
from ..sources.alphageo import AlphaGeoSource

tools = ToolSet()

Scenario = Literal["SSP245", "SSP370", "SSP585"]
Period = Literal["2025", "2035", "2050", "2100"]

_SCENARIO = Field(description="Climate scenario: SSP245 (moderate), SSP370 (high), SSP585 (very high).")
_PERIOD = Field(description="Projection year: 2025, 2035, 2050, or 2100.")
_ADDRESS = Field(default=None, description="Free-text address (geocoded by the API; Nominatim fallback if needed).")
_LAT = Field(default=None, description="Latitude in decimal degrees. Provide with longitude instead of an address.")
_LON = Field(default=None, description="Longitude in decimal degrees. Provide with latitude instead of an address.")

# Operator note (not a per-call arg): these tools need an AlphaGeo API key,
# supplied by the operator's stored credential or forwarded by the client via
# the credential-forwarding extension. The model never sets it.


class PeriodLocationInput(BaseModel):
    # extra="forbid": an unexpected arg from the model is a loud error, not a
    # silently-dropped field. Public name — it surfaces as the MCP inputSchema title.
    model_config = ConfigDict(extra="forbid")
    scenario: Scenario = _SCENARIO
    period: Period = _PERIOD
    address: str | None = _ADDRESS
    latitude: float | None = _LAT
    longitude: float | None = _LON


class LocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scenario: Scenario = _SCENARIO
    address: str | None = _ADDRESS
    latitude: float | None = _LAT
    longitude: float | None = _LON


# ── normalizers: faithful single-endpoint output → one report card ──
def _location(result_loc: dict[str, Any] | None, inp: Any) -> dict[str, Any]:
    loc = result_loc or {}
    return {
        "address": inp.address,
        "latitude": inp.latitude,
        "longitude": inp.longitude,
        "resolved_latitude": loc.get("resolved_latitude"),
        "resolved_longitude": loc.get("resolved_longitude"),
    }


@tools.tool(tier=1, emits=ClimateRiskReport, title="Full climate-risk report", read_only=True)
async def alphageo_get_full_report(inp: LocationInput, *, src: AlphaGeoSource) -> ClimateRiskReport:
    """Comprehensive climate-risk report for a location: overall + per-hazard
    risk scores across 2025/2035/2050/2100, plus financial impact and societal
    resilience. Preferred tool — one call covers most questions. Sections that
    fail are reported individually, never failing the whole report."""
    report = await src.get_full_report(
        scenario=inp.scenario, address=inp.address, latitude=inp.latitude, longitude=inp.longitude
    )
    return ClimateRiskReport.model_validate(report)


@tools.tool(tier=1, emits=ClimateRiskReport, title="Single-period climate profile", read_only=True)
async def alphageo_get_climate_profile(inp: PeriodLocationInput, *, src: AlphaGeoSource) -> ClimateRiskReport:
    """Full single-period profile: scores, physical hazard data, resilience and
    financial impact for one projection year. Use when the user fixes a year and
    wants every dimension for it."""
    report = await src.get_profile(
        scenario=inp.scenario, period=inp.period,
        address=inp.address, latitude=inp.latitude, longitude=inp.longitude,
    )
    return ClimateRiskReport.model_validate(report)


@tools.tool(tier=1, emits=ClimateRiskReport, title="Climate-risk scores", read_only=True)
async def alphageo_get_scores(inp: PeriodLocationInput, *, src: AlphaGeoSource) -> ClimateRiskReport:
    """Overall and per-hazard risk scores (and resilience-adjusted scores) for a
    single scenario and projection year."""
    scores = await src.get_scores(
        scenario=inp.scenario, period=inp.period,
        address=inp.address, latitude=inp.latitude, longitude=inp.longitude,
    )
    period = scores.get("period") or inp.period
    return ClimateRiskReport.model_validate({
        "scenario": inp.scenario,
        "location": _location(scores.get("location"), inp),
        "scores_by_period": {
            period: {"overall": scores.get("overall"), "hazard_scores": scores.get("hazard_scores")}
        },
    })


@tools.tool(tier=1, emits=ClimateRiskReport, title="Physical hazard indicators", read_only=True)
async def alphageo_get_risk_data(inp: PeriodLocationInput, *, src: AlphaGeoSource) -> ClimateRiskReport:
    """Underlying physical hazard indicators (e.g. cooling degree days,
    inundation depth, max wind speed) for a single scenario and projection year."""
    risk = await src.get_risk_data(
        scenario=inp.scenario, period=inp.period,
        address=inp.address, latitude=inp.latitude, longitude=inp.longitude,
    )
    return ClimateRiskReport.model_validate({
        "scenario": inp.scenario,
        "location": _location(risk.get("location"), inp),
        "scores_by_period": {},
        "physical_risk": {"period": risk.get("period") or inp.period, "hazards": risk.get("hazards")},
    })


@tools.tool(tier=1, emits=ClimateRiskReport, title="Resilience & adaptation", read_only=True)
async def alphageo_get_resilience_data(inp: PeriodLocationInput, *, src: AlphaGeoSource) -> ClimateRiskReport:
    """Adaptation measures by hazard plus societal-resilience context (GNI per
    capita, HDI, governance, vulnerable population) for a scenario and year."""
    resilience = await src.get_resilience_data(
        scenario=inp.scenario, period=inp.period,
        address=inp.address, latitude=inp.latitude, longitude=inp.longitude,
    )
    return ClimateRiskReport.model_validate({
        "scenario": inp.scenario,
        "location": _location(resilience.get("location"), inp),
        "scores_by_period": {},
        "societal_resilience": {
            "adaptation": resilience.get("adaptation"),
            "societal_resilience": resilience.get("societal_resilience"),
        },
    })


@tools.tool(tier=1, emits=ClimateRiskReport, title="Financial-impact analytics", read_only=True)
async def alphageo_get_analytics(inp: LocationInput, *, src: AlphaGeoSource) -> ClimateRiskReport:
    """Financial-impact analytics: insurance rates, utility costs, capital
    expenditure, discount rates and insurability for a scenario (scenario-level,
    no single year)."""
    analytics = await src.get_analytics(
        scenario=inp.scenario, address=inp.address, latitude=inp.latitude, longitude=inp.longitude
    )
    financial = {k: v for k, v in analytics.items() if k not in ("scenario", "data_version", "location")}
    return ClimateRiskReport.model_validate({
        "scenario": inp.scenario,
        "location": _location(analytics.get("location"), inp),
        "scores_by_period": {},
        "financial_impact": financial,
    })
