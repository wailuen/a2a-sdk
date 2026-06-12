# AlphaGeo scenarios — climate risk analysis (SCN-001 … SCN-010)

Generated and live-tested 2026-06-12. All scenarios passed; A2UI
`ClimateRiskReport` surface emitted on all turns.

Test transport: AG-UI SSE over Azure OpenAI + AlphaGeo API.
Test driver: `ChatDriver.agui_turn()` in `agent_sdk/testing/chat.py`.
Entrypoint: `python scripts/test_chat.py` (thin shim over `python -m agent_sdk test-chat`).

---

## A. Real estate investment

### SCN-001 — NYC Coastal Real Estate, 2050 SSP585

**Domain:** A — Real estate investment
**Persona:** Commercial RE acquisition analyst evaluating a long-term hold
**Capability:** buildable
**Tools:** `get_climate_risk_report` (lat=40.7128, lon=-74.006, year=2050, scenario=SSP585)

**Turn 1 (initial)**
> Generate the full climate risk report for latitude 40.7128, longitude -74.006
> (lower Manhattan) in 2050 under SSP585. We are evaluating a long-term
> commercial real estate acquisition.

**Turn 2 (reactive follow-up)**
> You mentioned coastal flooding and hurricane wind as dominant hazards. What
> does the resilience infrastructure actually look like for this location — are
> coastal defenses and drainage systems factored in, and how much do they reduce
> the risk-adjusted score versus the raw score?

**A2UI surface:** `ClimateRiskReport` — overall score, top hazards, resilience
breakdown
**PRD signal:** Analyst needs raw vs resilience-adjusted delta per hazard; the
`adaptation_measures` field in the report directly answers this.

---

### SCN-006 — Tampa Bay Coastal Flooding, 2050 SSP585

**Domain:** A — Real estate investment
**Persona:** RE portfolio manager stress-testing Gulf Coast concentration
**Capability:** buildable
**Tools:** `get_climate_risk_report` (lat=27.9506, lon=-82.4572, year=2050, scenario=SSP585)

**Turn 1 (initial)**
> Assess coastal flooding and storm-surge risk for Tampa Bay, Florida
> (latitude 27.9506, longitude -82.4572) in 2050 under SSP585. We are
> stress-testing a real-estate portfolio concentrated in this market.

**Turn 2 (reactive follow-up)**
> Tampa has some of the longest storm-surge exposure in the US. What does the
> 100-year coastal inundation depth look like for this location versus the
> 1000-year event — and are the existing coastal defense measures rated as
> strong or weak in the resilience data?

**A2UI surface:** `ClimateRiskReport` — coastal flooding hazard detail, return
periods, adaptation measures
**PRD signal:** Return-period breakdown (100-year vs 1000-year inundation depth)
is in `hazard_indicators`; surfaces the value of indicator-level granularity
over aggregate scores.

---

## B. Insurance / underwriting

### SCN-002 — Miami Insurance Pricing, 2100 SSP370

**Domain:** B — Insurance / underwriting
**Persona:** Insurance actuary pricing a 30-year commercial property policy
**Capability:** buildable
**Tools:** `get_climate_risk_report` (lat=25.7617, lon=-80.1918, year=2100, scenario=SSP370)

**Turn 1 (initial)**
> Assess climate risk for Miami, Florida at latitude 25.7617, longitude -80.1918
> in 2100 under SSP370. I am pricing a 30-year commercial property insurance
> policy.

**Turn 2 (reactive follow-up)**
> Given that risk profile, what does the financial-impact data say specifically
> about expected annual insurance rates and capital expenditure requirements
> for this Miami location? How does the resilience-adjusted score change the
> picture?

**A2UI surface:** `ClimateRiskReport` — financial impact block, insurance rate
indicators, resilience-adjusted vs raw score
**PRD signal:** Actuary workflow requires financial_impact fields alongside
physical hazard scores; both are present in a single tool call.

---

### SCN-007 — Los Angeles Wildfire & Drought, 2035 SSP370

**Domain:** B — Insurance / underwriting
**Persona:** Commercial property underwriter across LA County
**Capability:** buildable
**Tools:** `get_climate_risk_report` (lat=34.0522, lon=-118.2437, year=2035, scenario=SSP370)

**Turn 1 (initial)**
> What are the wildfire and drought risk scores for Los Angeles, California
> (latitude 34.0522, longitude -118.2437) in 2035 under SSP370? We are
> underwriting a large commercial property portfolio across LA County.

**Turn 2 (reactive follow-up)**
> With both wildfire and drought elevated, pull the physical hazard indicators:
> specifically max consecutive dry days, average vegetation cover, and the water
> stress index for this LA location. That helps us model which zip codes within
> the county face the worst combination.

**A2UI surface:** `ClimateRiskReport` — wildfire + drought hazard scores,
physical indicator detail
**PRD signal:** Sub-hazard indicator breakdown (dry days, vegetation, water
stress) drives zip-code-level granularity; surfaces appetite for batch / multi-
location queries.

---

### SCN-008 — New Orleans Extreme Risk, 2050 SSP585

**Domain:** B — Insurance / underwriting
**Persona:** Reinsurance analyst assessing market insurability at the 2050 horizon
**Capability:** buildable
**Tools:** `get_climate_risk_report` (lat=29.9511, lon=-90.0715, year=2050, scenario=SSP585)

**Turn 1 (initial)**
> Run the full climate risk report for New Orleans, Louisiana (latitude 29.9511,
> longitude -90.0715) in 2050 under SSP585. We need to understand whether this
> market is still insurable at that horizon.

**Turn 2 (reactive follow-up)**
> Given that exposure profile, what does the insurability data say for New
> Orleans — specifically the uninsurable coastal, uninsurable inland, and
> uninsurable fire flags? And does the adaptation infrastructure (levees,
> drainage, nature-based solutions) materially change the resilience-adjusted
> score versus raw risk?

**A2UI surface:** `ClimateRiskReport` — insurability flags, adaptation
infrastructure, resilience-adjusted delta
**PRD signal:** Insurability flags are a first-class output; shows the agent
can deliver a market-level underwriting verdict, not just a raw score.

---

## C. Infrastructure operations

### SCN-003 — Phoenix Data Center, Heat Stress SSP245

**Domain:** C — Infrastructure operations
**Persona:** Data center site selection engineer
**Capability:** buildable
**Tools:**
`get_climate_risk_report` (lat=33.4484, lon=-112.0740, year=2035, scenario=SSP245)
`get_climate_risk_report` (lat=33.4484, lon=-112.0740, year=2050, scenario=SSP245)

**Turn 1 (initial)**
> What are the heat stress scores for Phoenix, Arizona (latitude 33.4484,
> longitude -112.0740) in 2035 and 2050 under SSP245? We are evaluating a
> data-center site.

**Turn 2 (reactive follow-up)**
> The heat data shows significant exposure. Can you pull the analytics —
> specifically operational downtime days and workforce productivity loss — for
> this Phoenix location under SSP245? That is what we need for the business-case
> model.

**A2UI surface:** `ClimateRiskReport` — heat stress scores across years,
operational analytics block
**PRD signal:** Multi-year comparison (2035 vs 2050) within a single session;
operational downtime analytics are a distinct output track from physical hazard
scores.

---

### SCN-010 — Seattle Climate Profile, 2035 & 2100 SSP370

**Domain:** C — Infrastructure operations
**Persona:** Corporate real estate director evaluating climate-resilient campus
relocation
**Capability:** buildable
**Tools:**
`get_climate_risk_report` (lat=47.6062, lon=-122.3321, year=2035, scenario=SSP370)
`get_climate_risk_report` (lat=47.6062, lon=-122.3321, year=2100, scenario=SSP370)

**Turn 1 (initial)**
> What is the climate risk profile for Seattle, Washington (latitude 47.6062,
> longitude -122.3321) in 2035 under SSP370? We are evaluating Seattle as a
> climate-resilient relocation destination for a corporate campus.

**Turn 2 (reactive follow-up)**
> Seattle scores lower than most coastal cities — but what does the 2100
> projection look like under SSP370? Specifically, which hazards are projected
> to increase the most between 2035 and 2100, and what is the trajectory of the
> overall risk-adjusted score?

**A2UI surface:** `ClimateRiskReport` — overall risk trajectory, hazard
escalation by type
**PRD signal:** Long-horizon trajectory query (35-year gap 2035→2100) with
hazard-ranked change; surfaces the value of time-series comparison within a
single agent session.

---

## D. Industrial operations

### SCN-004 — Houston Industrial Facility, SSP585

**Domain:** D — Industrial operations  
**Persona:** EH&S director at a petrochemical operator
**Capability:** buildable
**Tools:** `get_climate_risk_report` (lat=29.7604, lon=-95.3698, year=2050, scenario=SSP585)

**Turn 1 (initial)**
> Run a full climate risk report for Houston, Texas at latitude 29.7604,
> longitude -95.3698 under SSP585. We operate a petrochemical facility there
> and need to understand the compound hazard exposure.

**Turn 2 (reactive follow-up)**
> With both inland flooding and hurricane wind showing high scores, which of
> those two hazards has the weaker resilience infrastructure in place — meaning
> the largest gap between raw risk score and resilience-adjusted score? That
> gap tells us where adaptation capex will have the most leverage.

**A2UI surface:** `ClimateRiskReport` — compound hazard scores, per-hazard
resilience gap
**PRD signal:** Adaptation-capex prioritisation requires per-hazard raw vs
resilience-adjusted delta; confirms the report structure supports comparative
gap analysis across hazard categories.

---

## E. Long-term trajectory

### SCN-005 — Chicago Long-Term Trajectory, 2025→2100 SSP245

**Domain:** E — Long-term trajectory
**Persona:** Institutional investor building a 75-year climate scenario model
**Capability:** buildable
**Tools:**
`get_climate_risk_report` (lat=41.8781, lon=-87.6298, year=2025, scenario=SSP245)
`get_climate_risk_report` (lat=41.8781, lon=-87.6298, year=2100, scenario=SSP245)

**Turn 1 (initial)**
> Give me the climate risk scores for Chicago, Illinois (latitude 41.8781,
> longitude -87.6298) for the 2025 baseline under SSP245, and compare it to
> the 2100 projection.

**Turn 2 (reactive follow-up)**
> Chicago looks like a relatively lower-risk city versus coastal peers. From the
> resilience data, what societal-resilience indicators (governance, GNI per
> capita, human development index) look strongest for this location — and which
> hazard categories have the least adaptation infrastructure currently in place?

**A2UI surface:** `ClimateRiskReport` — baseline vs long-horizon scores,
societal resilience indicators
**PRD signal:** Societal resilience indicators (governance, GNI, HDI) are in the
report structure and surface well as a secondary "where to invest" signal for
long-horizon investors.

---

## F. Comparative / portfolio

### SCN-009 — Denver vs Miami, 2050 SSP370

**Domain:** F — Comparative / portfolio
**Persona:** Infrastructure investment director choosing between two metro markets
**Capability:** buildable
**Tools:**
`get_climate_risk_report` (lat=39.7392, lon=-104.9903, year=2050, scenario=SSP370)
`get_climate_risk_report` (lat=25.7617, lon=-80.1918, year=2050, scenario=SSP370)

**Turn 1 (initial)**
> Compare the overall climate risk score for Denver, Colorado (latitude 39.7392,
> longitude -104.9903) and Miami, Florida (latitude 25.7617, longitude -80.1918)
> both in 2050 under SSP370. Start with Denver.

**Turn 2 (reactive follow-up)**
> Now give me Miami under the same parameters — SSP370, 2050 — so I can compare
> the overall risk scores and the top three hazards side by side. We are deciding
> where to concentrate a long-duration infrastructure investment.

**A2UI surface:** `ClimateRiskReport` × 2 (one per turn) — overall score + top-3
hazards for each city
**PRD signal:** Multi-city comparison within a session is the most common
portfolio workflow; A2UI surfaces are emitted per turn and the model synthesises
the comparison in the final reply. Surfaces appetite for a batch / side-by-side
card mode.
