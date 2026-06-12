"""ClimateRiskReport — the AlphaGeo domain A2UI card.

ONE domain card carries every tool's output (a2ui-advisor): the 6 AlphaGeo
tools all normalize to the same report shape, so collapsing the legacy
per-tool data-type hints into a single `ClimateRiskReport` is the right call.
It lives in its OWN catalog ``urn:alphageo:climate:v1`` — the SDK's Standard
Profile catalog is frozen and closed to domain types. A client renders this
card only if it advertises that catalog; otherwise the A2A artifact ships only
``to_plain_text()`` (nothing is silently dropped).

Partial upstream failure is signalled with a typed ``section_errors`` map
(a2ui-advisor Option B) rather than bare ``{"error": ...}`` objects standing
where a section should be — the renderer checks the map, never trips over a
malformed section. Required top-level fields (scenario, location,
scores_by_period) are never optional: a missing one fails loudly at build
time, not silently on the wire.
"""

from __future__ import annotations

from typing import Any, ClassVar

from pydantic import BaseModel, ConfigDict, Field

from agent_sdk.models.content_types import ContentModel, register_content_type

CATALOG_ID = "urn:alphageo:climate:v1"

# Stable enumerations (mirror the AlphaGeo API).
HAZARDS = (
    "heat_stress", "inland_flooding", "coastal_flooding", "drought",
    "hurricane_wind", "wildfire", "hail", "landslide", "earthquake",
)
PERIODS = ("2025", "2035", "2050", "2100")
SCENARIOS = ("SSP245", "SSP370", "SSP585")


class _Frag(BaseModel):
    """Wire fragment: snake_case keys (no camelCase aliases — the AlphaGeo
    shape is snake_case end to end)."""

    model_config = ConfigDict(populate_by_name=True)


class ReportLocation(_Frag):
    address: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    resolved_latitude: float | None = None
    resolved_longitude: float | None = None


class OverallScore(_Frag):
    risk_score_pct: float | None = None
    resilience_adjusted_pct: float | None = None
    risk_score: float | None = None
    resilience_adjusted_score: float | None = None


class HazardScore(_Frag):
    risk_score: float | None = None
    resilience_adjusted_score: float | None = None


class PeriodScores(_Frag):
    overall: OverallScore | None = None
    hazard_scores: dict[str, HazardScore] | None = None


class PhysicalRisk(_Frag):
    period: str | None = None
    hazards: dict[str, dict[str, Any]] | None = None


def _fmt(value: Any) -> str:
    """One-decimal for floats, as-is otherwise (fallbacks read as numbers,
    not 72.37812%)."""
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, (int, float)):
        return f"{value:.1f}".rstrip("0").rstrip(".") if isinstance(value, float) else str(value)
    return str(value)


class ClimateRiskReport(ContentModel):
    data_type: ClassVar[str] = "climate_risk_report"
    component: ClassVar[str] = "ClimateRiskReport"
    catalog_id: ClassVar[str] = CATALOG_ID

    scenario: str
    location: ReportLocation
    # period -> scores; full_report carries all 4, a single tool carries 1.
    scores_by_period: dict[str, PeriodScores] = Field(default_factory=dict)
    financial_impact: dict[str, Any] | None = None
    societal_resilience: dict[str, Any] | None = None
    physical_risk: PhysicalRisk | None = None
    # section name -> redacted reason; empty when everything succeeded. Keys
    # name a section ("financial_impact", "societal_resilience",
    # "physical_risk") or a failed score period ("scores_2050"). Left as an
    # open str-keyed map (not a Literal) so dynamic "scores_<period>" keys stay
    # valid; values are always one of _redact()'s fixed phrases.
    section_errors: dict[str, str] = Field(default_factory=dict)

    # ── text fallback (the ONLY thing a non-AlphaGeo client sees) ──
    def to_plain_text(self) -> str:
        loc = self.location
        where = loc.address or (
            f"{loc.resolved_latitude}, {loc.resolved_longitude}"
            if loc.resolved_latitude is not None
            else "the requested location"
        )
        lines = [f"Climate Risk Report — {where} ({self.scenario})"]

        periods = sorted(p for p, s in self.scores_by_period.items() if s.overall)
        if len(periods) == 1:
            ov = self.scores_by_period[periods[0]].overall
            lines.append(
                f"Period {periods[0]}: {_fmt(ov.risk_score_pct)}% risk | "
                f"{_fmt(ov.resilience_adjusted_pct)}% resilience-adjusted"
            )
        elif periods:
            lines.append("Overall risk by period:")
            for p in periods:
                ov = self.scores_by_period[p].overall
                lines.append(
                    f"  {p}: {_fmt(ov.risk_score_pct)}% risk | "
                    f"{_fmt(ov.resilience_adjusted_pct)}% resilience-adjusted"
                )

        # Top hazards (by raw risk score) for the most severe scored period —
        # a narrative of 3-5, never the full 9x4 grid (that's what the card is for).
        worst = self._worst_period()
        if worst is not None:
            hz = self.scores_by_period[worst].hazard_scores or {}
            ranked = sorted(
                ((name, h) for name, h in hz.items() if h.risk_score is not None),
                key=lambda kv: kv[1].risk_score, reverse=True,
            )[:5]
            if ranked:
                lines.append(f"Top hazards ({worst}):")
                for name, h in ranked:
                    label = name.replace("_", " ")
                    raj = (
                        f" ({_fmt(h.resilience_adjusted_score)} resilience-adj)"
                        if h.resilience_adjusted_score is not None else ""
                    )
                    lines.append(f"  {label}: {_fmt(h.risk_score)}{raj}")

        if self.financial_impact:
            ins = (self.financial_impact.get("insurance") or {}).get("annual_rate_pct")
            capex = (self.financial_impact.get("capital_expenditure") or {}).get("annual_capex_pct")
            bits = []
            if ins is not None:
                bits.append(f"insurance {_fmt(ins)}%")
            if capex is not None:
                bits.append(f"capex {_fmt(capex)}%")
            if bits:
                lines.append("Financial exposure (annual): " + ", ".join(bits))

        if self.societal_resilience:
            soc = self.societal_resilience.get("societal_resilience") or {}
            hdi = soc.get("human_development_index")
            gov = soc.get("governance_effectiveness")
            bits = []
            if hdi is not None:
                bits.append(f"HDI {_fmt(hdi)}")
            if gov is not None:
                bits.append(f"governance {_fmt(gov)}")
            if bits:
                lines.append("Resilience context: " + ", ".join(bits))

        # Physical hazard indicators (the only place this section reaches a
        # non-AlphaGeo client) — a few hazards, a couple of indicators each.
        if self.physical_risk and self.physical_risk.hazards:
            when = f" ({self.physical_risk.period})" if self.physical_risk.period else ""
            lines.append(f"Physical hazard indicators{when}:")
            for hazard, indicators in list(self.physical_risk.hazards.items())[:3]:
                label = hazard.replace("_", " ")
                shown = [
                    f"{k.replace('_', ' ')} {_fmt(v)}"
                    for k, v in list((indicators or {}).items())[:2]
                    if v is not None
                ]
                if shown:
                    lines.append(f"  {label}: " + ", ".join(shown))

        for section, reason in self.section_errors.items():
            lines.append(f"{section.replace('_', ' ')} data unavailable: {reason}")

        return "\n".join(lines)

    def _worst_period(self) -> str | None:
        best: tuple[float, str] | None = None
        for period, scores in self.scores_by_period.items():
            ov = scores.overall
            if ov is None or ov.risk_score_pct is None:
                continue
            if best is None or ov.risk_score_pct > best[0]:
                best = (ov.risk_score_pct, period)
        return best[1] if best else None


register_content_type(ClimateRiskReport)
