"""Climate tools: each normalizes its source call into one ClimateRiskReport,
and the report surfaces end to end as an A2A artifact via the agent loop.
"""

from __future__ import annotations

import uuid

import pytest

from agent_sdk.testing import reply, tool_call

from src.content import ClimateRiskReport
from src.sources.alphageo import AlphaGeoSource
from src.tools import climate

from .conftest import wait_for_state


# ── direct normalization (duck-typed stub source, no HTTP) ──
class _Stub:
    async def get_full_report(self, **kw):
        return {
            "scenario": "SSP245",
            "location": {"address": kw.get("address"), "resolved_latitude": 1.0, "resolved_longitude": 2.0},
            "scores_by_period": {"2050": {"overall": {"risk_score_pct": 70.0}, "hazard_scores": {}}},
            "financial_impact": {"insurance": {"annual_rate_pct": 1.1}},
            "section_errors": {},
        }

    async def get_profile(self, **kw):
        return {
            "scenario": "SSP245",
            "location": {"address": kw.get("address")},
            "scores_by_period": {kw["period"]: {"overall": {"risk_score_pct": 55.0}, "hazard_scores": {}}},
            "physical_risk": {"period": kw["period"], "hazards": {"heat_stress": {"cooling_degree_days": 1200}}},
            "section_errors": {},
        }

    async def get_scores(self, **kw):
        return {
            "scenario": "SSP245", "period": kw["period"],
            "location": {"resolved_latitude": 3.0, "resolved_longitude": 4.0},
            "overall": {"risk_score_pct": 60.0}, "hazard_scores": {"drought": {"risk_score": 40.0}},
        }

    async def get_risk_data(self, **kw):
        return {
            "scenario": "SSP245", "period": kw["period"], "location": {},
            "hazards": {"heat_stress": {"cooling_degree_days": 900}},
        }

    async def get_resilience_data(self, **kw):
        return {
            "scenario": "SSP245", "period": kw["period"], "location": {},
            "adaptation": {"heat_stress": {"urban_greenery": 0.3}},
            "societal_resilience": {"human_development_index": 0.8},
        }

    async def get_analytics(self, **kw):
        return {
            "scenario": "SSP245", "data_version": "v2",
            "location": {"resolved_latitude": 5.0, "resolved_longitude": 6.0},
            "insurance": {"annual_rate_pct": 2.0},
        }


def _periodloc(**kw):
    return climate.PeriodLocationInput(scenario="SSP245", period="2050", **kw)


def _loc(**kw):
    return climate.LocationInput(scenario="SSP245", **kw)


async def test_full_report_passthrough():
    r = await climate.alphageo_get_full_report(_loc(address="1 St, USA"), src=_Stub())
    assert isinstance(r, ClimateRiskReport)
    assert r.scores_by_period["2050"].overall.risk_score_pct == 70.0
    assert r.financial_impact["insurance"]["annual_rate_pct"] == 1.1


async def test_profile_passthrough_with_physical_risk():
    r = await climate.alphageo_get_climate_profile(_periodloc(address="x"), src=_Stub())
    assert r.physical_risk.period == "2050"
    assert r.physical_risk.hazards["heat_stress"]["cooling_degree_days"] == 1200


async def test_scores_normalizes_into_period_block():
    r = await climate.alphageo_get_scores(_periodloc(latitude=1.0, longitude=2.0), src=_Stub())
    assert set(r.scores_by_period) == {"2050"}
    assert r.scores_by_period["2050"].hazard_scores["drought"].risk_score == 40.0
    assert r.location.resolved_latitude == 3.0  # resolved coords carried through


async def test_risk_data_normalizes_into_physical_risk():
    r = await climate.alphageo_get_risk_data(_periodloc(address="x"), src=_Stub())
    assert r.scores_by_period == {}
    assert r.physical_risk.hazards["heat_stress"]["cooling_degree_days"] == 900


async def test_resilience_normalizes_into_societal_resilience():
    r = await climate.alphageo_get_resilience_data(_periodloc(address="x"), src=_Stub())
    assert r.societal_resilience["societal_resilience"]["human_development_index"] == 0.8
    assert r.societal_resilience["adaptation"]["heat_stress"]["urban_greenery"] == 0.3


async def test_analytics_normalizes_into_financial_impact():
    r = await climate.alphageo_get_analytics(_loc(latitude=1.0, longitude=2.0), src=_Stub())
    # scenario/data_version/location are stripped from the financial block
    assert "scenario" not in r.financial_impact
    assert r.financial_impact["insurance"]["annual_rate_pct"] == 2.0
    assert r.location.resolved_latitude == 5.0


# ── end to end: the card surfaces as an A2A artifact through the loop ──
def _send_body(text: str) -> dict:
    return {
        "message": {
            "role": "user",
            "parts": [{"kind": "text", "text": text}],
            "messageId": uuid.uuid4().hex,
        }
    }


async def _fake_full_report(self, **kw):
    return {
        "scenario": "SSP245",
        "location": {"address": kw.get("address"), "resolved_latitude": 40.0, "resolved_longitude": -74.0},
        "scores_by_period": {"2050": {"overall": {"risk_score_pct": 71.0}, "hazard_scores": {}}},
        "section_errors": {},
    }


async def test_tools_list_carries_title_and_readonly_annotations(client):
    """MCP tools/list advertises a display title and read-only annotations so
    Claude.ai does not flag these pure queries as destructive."""
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    r = await client.post("/mcp", json=body, headers={"MCP-Protocol-Version": "2025-06-18"})
    tools = {t["name"]: t for t in r.json()["result"]["tools"]}
    full = tools["alphageo_get_full_report"]
    assert full["title"] == "Full climate-risk report"
    assert full["annotations"]["readOnlyHint"] is True
    assert full["annotations"]["destructiveHint"] is False
    # outputSchema present (emits=ClimateRiskReport); inputSchema title is public
    assert "outputSchema" in full
    assert full["inputSchema"]["title"] == "LocationInput"


async def test_report_emits_as_artifact(client, fake_model, monkeypatch):
    monkeypatch.setattr(AlphaGeoSource, "get_full_report", _fake_full_report)
    fake_model.script(
        tool_call("alphageo_get_full_report", {"scenario": "SSP245", "address": "1 Main St, USA"}),
        reply("Heat is the dominant risk by 2050."),
    )
    r = await client.post("/v1/message:send", json=_send_body("climate risk for 1 Main St, USA"))
    assert r.status_code == 200, r.text
    done = await wait_for_state(client, r.json()["id"])
    assert done["status"]["state"] == "completed"
    art = done["artifacts"][0]
    assert art["metadata"]["data_type"] == "climate_risk_report"
