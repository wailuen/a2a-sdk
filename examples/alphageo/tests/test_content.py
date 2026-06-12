"""ClimateRiskReport: registration, wire shape, and the text fallback that is
the ONLY thing a non-AlphaGeo client sees.
"""

from __future__ import annotations

from agent_sdk.models.content_types import content_type_for

from src.content import CATALOG_ID, ClimateRiskReport


def test_registered_under_own_catalog():
    assert content_type_for("climate_risk_report") is ClimateRiskReport
    assert ClimateRiskReport.catalog_id == CATALOG_ID == "urn:alphageo:climate:v1"
    assert ClimateRiskReport.component == "ClimateRiskReport"


def _report(**kw):
    base = {
        "scenario": "SSP245",
        "location": {"address": "1 Test St, Testville, USA"},
        "scores_by_period": {
            "2050": {
                "overall": {"risk_score_pct": 72.34, "resilience_adjusted_pct": 60.1},
                "hazard_scores": {
                    "heat_stress": {"risk_score": 88.0, "resilience_adjusted_score": 70.0},
                    "drought": {"risk_score": 41.0, "resilience_adjusted_score": 33.0},
                },
            }
        },
    }
    base.update(kw)
    return ClimateRiskReport.model_validate(base)


def test_wire_is_snake_case_and_drops_none():
    wire = _report().wire()
    assert wire["scenario"] == "SSP245"
    assert "risk_score_pct" in wire["scores_by_period"]["2050"]["overall"]
    # exclude_none: unset optional sections never appear on the wire
    assert "physical_risk" not in wire
    assert "financial_impact" not in wire


def test_plain_text_single_period_and_top_hazards():
    text = _report().to_plain_text()
    assert "1 Test St, Testville, USA" in text
    assert "SSP245" in text
    assert "Period 2050" in text  # single-period special case
    # hazards ranked by raw risk score; heat_stress (88) before drought (41)
    assert text.index("heat stress") < text.index("drought")


def test_plain_text_multi_period_lists_each():
    r = _report(scores_by_period={
        "2025": {"overall": {"risk_score_pct": 40.0, "resilience_adjusted_pct": 35.0}},
        "2050": {"overall": {"risk_score_pct": 72.0, "resilience_adjusted_pct": 60.0}},
    })
    text = r.to_plain_text()
    assert "Overall risk by period:" in text
    assert "2025:" in text and "2050:" in text


def test_physical_risk_surfaces_in_text_fallback():
    # the ONLY place a non-AlphaGeo client sees physical hazard indicators
    r = _report(
        scores_by_period={},
        physical_risk={
            "period": "2050",
            "hazards": {"heat_stress": {"cooling_degree_days": 1234.5, "hot_days_above_90th_percentile": 30}},
        },
    )
    text = r.to_plain_text()
    assert "Physical hazard indicators (2050):" in text
    assert "heat stress" in text
    assert "cooling degree days" in text


def test_section_errors_surface_in_text_and_never_crash():
    r = _report(section_errors={"financial_impact": "upstream error", "scores_2100": "timed out"})
    text = r.to_plain_text()
    assert "financial impact data unavailable: upstream error" in text
    assert "scores 2100 data unavailable: timed out" in text


def test_required_fields_enforced():
    import pytest
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ClimateRiskReport.model_validate({"location": {}})  # missing scenario
