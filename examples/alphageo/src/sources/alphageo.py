"""AlphaGeoSource — climate-risk API client behind the SDK SourceAdapter seam.

All outbound HTTP goes through the base adapter's host-checked client
(``allowed_hosts`` enforced on every hop, incl. the Nominatim fallback).
AlphaGeo specifics ported from the original service:

- raw API key in the ``Authorization`` header (NO ``Bearer`` prefix), resolved
  PER CALL via ``self.credential("api_key")`` — the layered resolver returns
  the forwarded (``X-Agent-Credentials``) key first, else the stored key;
- endpoints require trailing slashes (301 otherwise);
- a 500 on an address-based request means AlphaGeo's geocoder failed (e.g.
  some non-US addresses) — fall back to Nominatim and retry with lat/lon;
- a 60/min client-side throttle and a 24h response cache, both tenant-isolated
  by a hash of the resolved key so one tenant's data never serves another.

Secrets hygiene: errors and logs NEVER carry the key, the address, query
params, response bodies, or upstream URLs — only an error category and (at
most) an HTTP status. The vendor key is sent to AlphaGeo only, never Nominatim.
"""

from __future__ import annotations

import asyncio
import hashlib
import time
from collections import OrderedDict, deque
from typing import Any

import httpx

from agent_sdk import AgentError, ErrorCategory, SourceAdapter

DEFAULT_BASE_URL = "https://app.alphageo.ai/api/public/v1"
PERIODS = ("2025", "2035", "2050", "2100")
SCENARIOS = ("SSP245", "SSP370", "SSP585")


def _redact(exc: Exception) -> str:
    """A short, leak-free reason for a section that failed (no detail, no
    input). Used for ``section_errors`` and partial-failure signalling."""
    if isinstance(exc, AgentError):
        return {
            ErrorCategory.AUTH: "authentication failed",
            ErrorCategory.RATE_LIMITED: "rate limited",
            ErrorCategory.TIMEOUT: "timed out",
            ErrorCategory.UPSTREAM: "upstream error",
            ErrorCategory.VALIDATION: "invalid request",
            ErrorCategory.NOT_FOUND: "not found",
        }.get(exc.category, "unavailable")
    return "unavailable"


class _RateGate:
    """Sliding-window throttle. ``acquire()`` awaits until under the per-minute
    limit (a politeness gate ahead of AlphaGeo's own 429)."""

    def __init__(self, per_minute: int) -> None:
        self._per_minute = per_minute
        self._hits: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        if self._per_minute <= 0:
            return
        async with self._lock:
            self._evict()
            if len(self._hits) >= self._per_minute:
                await asyncio.sleep(max(0.0, 60.0 - (time.monotonic() - self._hits[0])))
                self._evict()
            self._hits.append(time.monotonic())

    def _evict(self) -> None:
        now = time.monotonic()
        while self._hits and now - self._hits[0] >= 60.0:
            self._hits.popleft()


class _TtlCache:
    def __init__(self, ttl: float, maxsize: int = 512) -> None:
        self._ttl = ttl
        self._maxsize = maxsize
        self._data: OrderedDict[str, tuple[float, Any]] = OrderedDict()
        self._lock = asyncio.Lock()

    async def get(self, key: str) -> Any | None:
        async with self._lock:
            item = self._data.get(key)
            if item is None:
                return None
            expiry, value = item
            if time.monotonic() >= expiry:
                self._data.pop(key, None)
                return None
            self._data.move_to_end(key)
            return value

    async def set(self, key: str, value: Any) -> None:
        async with self._lock:
            self._data[key] = (time.monotonic() + self._ttl, value)
            self._data.move_to_end(key)
            while len(self._data) > self._maxsize:
                self._data.popitem(last=False)


class AlphaGeoSource(SourceAdapter):
    source_name = "alphageo"
    allowed_hosts = ["app.alphageo.ai", "nominatim.openstreetmap.org"]

    def __init__(
        self,
        settings: Any,
        resolver: Any,
        *,
        base_url: str | None = None,
        cache_ttl_seconds: float = 24 * 3600,
        rate_limit_per_minute: int = 60,
    ) -> None:
        super().__init__(settings, resolver)
        configured = base_url or getattr(settings, "alphageo_base_url", None)
        self._base_url = (configured or DEFAULT_BASE_URL).rstrip("/")
        self._cache = _TtlCache(cache_ttl_seconds)
        self._gate = _RateGate(rate_limit_per_minute)

    # ── HTTP core ──
    @staticmethod
    def _cache_key(api_key: str, endpoint: str, params: dict[str, Any]) -> str:
        tenant = hashlib.sha256(api_key.encode()).hexdigest()[:16]
        flat = "&".join(f"{k}={params[k]}" for k in sorted(params))
        return f"{tenant}:{endpoint}:{flat}"

    async def _safe_get(
        self, url: str, params: dict[str, Any], headers: dict[str, str]
    ) -> httpx.Response:
        try:
            return await self.client.get(url, params=params, headers=headers)
        except httpx.TimeoutException as exc:
            raise AgentError(
                ErrorCategory.TIMEOUT, "upstream 'alphageo' timed out", source=self.source_name
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentError(
                ErrorCategory.UPSTREAM, "upstream 'alphageo' request failed", source=self.source_name
            ) from exc

    def _handle(self, resp: httpx.Response) -> dict[str, Any]:
        code = resp.status_code
        if code in (401, 403):
            raise AgentError(
                ErrorCategory.AUTH, "upstream 'alphageo' rejected credentials", source=self.source_name
            )
        if code == 429:
            raise AgentError(
                ErrorCategory.RATE_LIMITED, "upstream 'alphageo' rate limited", source=self.source_name
            )
        if code >= 400:
            # status only — never the response body (may echo the address/URL)
            raise AgentError(
                ErrorCategory.UPSTREAM,
                f"upstream 'alphageo' returned {code}",
                source=self.source_name,
            )
        if code == 204:
            return {}
        try:
            return resp.json()
        except ValueError as exc:
            raise AgentError(
                ErrorCategory.UPSTREAM, "upstream 'alphageo' returned malformed data", source=self.source_name
            ) from exc

    async def _geocode(self, address: str) -> dict[str, float] | None:
        """Nominatim fallback (no vendor key sent here). Returns lat/lon or
        None; never raises, never logs the address."""
        headers = {"User-Agent": "agent-sdk-alphageo/1.0 (climate risk)"}
        for query in self._geocode_queries(address):
            try:
                resp = await self.client.get(
                    "https://nominatim.openstreetmap.org/search",
                    params={"q": query, "format": "json", "limit": 1},
                    headers=headers,
                )
                data = resp.json()
                if data:
                    return {"latitude": float(data[0]["lat"]), "longitude": float(data[0]["lon"])}
            except (httpx.HTTPError, ValueError, KeyError, IndexError):
                continue
        return None

    @staticmethod
    def _geocode_queries(address: str) -> list[str]:
        import re

        queries = [address]
        stripped = re.sub(r",?\s*\d{4,6}\s*$", "", address).strip()
        if stripped and stripped != address:
            queries.append(stripped)
        return queries

    async def _api_get(self, endpoint: str, params: dict[str, Any]) -> dict[str, Any]:
        api_key = self.credential("api_key")  # raises AUTH if absent everywhere
        cache_key = self._cache_key(api_key, endpoint, params)
        cached = await self._cache.get(cache_key)
        if cached is not None:
            return cached

        await self._gate.acquire()
        headers = {"Authorization": api_key, "Accept": "application/json"}
        url = f"{self._base_url}{endpoint}"
        resp = await self._safe_get(url, params, headers)

        if resp.status_code == 500 and params.get("address"):
            coords = await self._geocode(params["address"])
            if coords:
                retry = {k: v for k, v in params.items() if k != "address"}
                retry.update(coords)
                resp = await self._safe_get(url, retry, headers)

        data = self._handle(resp)
        await self._cache.set(cache_key, data)
        return data

    # ── param validation (echoes allowed values, never the provided value) ──
    @staticmethod
    def _validate(
        scenario: str | None,
        period: str | None,
        address: str | None,
        latitude: float | None,
        longitude: float | None,
        *,
        require_period: bool,
    ) -> None:
        if scenario not in SCENARIOS:
            raise AgentError(
                ErrorCategory.VALIDATION,
                f"invalid scenario; allowed: {', '.join(SCENARIOS)}",
                source="alphageo",
            )
        if require_period and period not in PERIODS:
            raise AgentError(
                ErrorCategory.VALIDATION,
                f"invalid or missing period; allowed: {', '.join(PERIODS)}",
                source="alphageo",
            )
        if address is None and (latitude is None or longitude is None):
            raise AgentError(
                ErrorCategory.VALIDATION,
                "provide either an address or both latitude and longitude",
                source="alphageo",
            )

    @staticmethod
    def _params(
        scenario: str,
        period: str | None,
        address: str | None,
        latitude: float | None,
        longitude: float | None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"scenario": scenario}
        if period is not None:
            params["period"] = period
        if address is not None:
            params["address"] = address
        if latitude is not None:
            params["latitude"] = latitude
        if longitude is not None:
            params["longitude"] = longitude
        return params

    # ── endpoint methods (return formatted, snake_case dicts) ──
    async def get_scores(
        self, *, scenario: str, period: str,
        address: str | None = None, latitude: float | None = None, longitude: float | None = None,
    ) -> dict[str, Any]:
        self._validate(scenario, period, address, latitude, longitude, require_period=True)
        raw = await self._api_get("/scores/", self._params(scenario, period, address, latitude, longitude))
        return self._format_scores(raw)

    async def get_risk_data(
        self, *, scenario: str, period: str,
        address: str | None = None, latitude: float | None = None, longitude: float | None = None,
    ) -> dict[str, Any]:
        self._validate(scenario, period, address, latitude, longitude, require_period=True)
        raw = await self._api_get("/risk_data/", self._params(scenario, period, address, latitude, longitude))
        return self._format_risk(raw)

    async def get_resilience_data(
        self, *, scenario: str, period: str,
        address: str | None = None, latitude: float | None = None, longitude: float | None = None,
    ) -> dict[str, Any]:
        self._validate(scenario, period, address, latitude, longitude, require_period=True)
        raw = await self._api_get("/resilience_data/", self._params(scenario, period, address, latitude, longitude))
        return self._format_resilience(raw)

    async def get_analytics(
        self, *, scenario: str,
        address: str | None = None, latitude: float | None = None, longitude: float | None = None,
    ) -> dict[str, Any]:
        self._validate(scenario, None, address, latitude, longitude, require_period=False)
        raw = await self._api_get("/analytics/", self._params(scenario, None, address, latitude, longitude))
        return self._format_analytics(raw)

    # ── formatters (faithful to the original services) ──
    @staticmethod
    def _format_scores(raw: dict[str, Any]) -> dict[str, Any]:
        ids = raw.get("identifiers", {})
        overall = raw.get("overall_indicators", {})
        out: dict[str, Any] = {
            "scenario": ids.get("SCENARIO"),
            "period": ids.get("PERIOD"),
            "data_version": raw.get("data_version"),
            "location": {
                "resolved_latitude": ids.get("LATITUDE"),
                "resolved_longitude": ids.get("LONGITUDE"),
            },
            "overall": {
                "risk_score_pct": overall.get("OVERALL_RISK_SCORE_PCT"),
                "resilience_adjusted_pct": overall.get("OVERALL_RAJ_SCORE_PCT"),
                "risk_score": overall.get("OVERALL_RISK_SCORE"),
                "resilience_adjusted_score": overall.get("OVERALL_RAJ_SCORE"),
            },
            "hazard_scores": {},
        }
        hazard_map = {
            "heat_stress": ("heat_stress", "HEAT_SCORE", "HEAT_RAJ_SCORE"),
            "inland_flooding": ("inland_flooding", "INLAND_SCORE", "INLAND_RAJ_SCORE"),
            "coastal_flooding": ("coastal_flooding", "COASTAL_SCORE", "COASTAL_RAJ_SCORE"),
            "drought": ("drought", "DROUGHT_SCORE", "DROUGHT_RAJ_SCORE"),
            "hurricane_wind": ("hurricane_wind", "WIND_SCORE", "WIND_RAJ_SCORE"),
            "wildfire": ("wildfire", "FIRE_SCORE", "FIRE_RAJ_SCORE"),
            "hail": ("hail", "HAIL_SCORE", "HAIL_RAJ_SCORE"),
            "landslide": ("landslide", "LANDSLIDE_SCORE", "LANDSLIDE_RAJ_SCORE"),
            "earthquake": ("earthquake", "EARTHQUAKE_SCORE", "EARTHQUAKE_RAJ_SCORE"),
        }
        for hazard, (key, raw_f, raj_f) in hazard_map.items():
            section = raw.get(key, {})
            if section:
                out["hazard_scores"][hazard] = {
                    "risk_score": section.get(raw_f),
                    "resilience_adjusted_score": section.get(raj_f),
                }
        return out

    @staticmethod
    def _format_risk(raw: dict[str, Any]) -> dict[str, Any]:
        ids = raw.get("identifiers", {})
        out: dict[str, Any] = {
            "scenario": ids.get("SCENARIO"),
            "period": ids.get("PERIOD"),
            "data_version": raw.get("data_version"),
            "location": {
                "resolved_latitude": ids.get("LATITUDE"),
                "resolved_longitude": ids.get("LONGITUDE"),
            },
            "hazards": {},
        }
        labels = {
            "heat_stress": {"CDD": "cooling_degree_days", "HOTDAYS_ABV90P": "hot_days_above_90th_percentile"},
            "inland_flooding": {"HEAVY_PR_DAYS": "heavy_precipitation_days", "R_INUN_RP0100": "inundation_depth_100yr_return_m", "R_INUN_RP1000": "inundation_depth_1000yr_return_m"},
            "coastal_flooding": {"C_INUN_RP0100": "coastal_inundation_100yr_return_m", "C_INUN_RP1000": "coastal_inundation_1000yr_return_m", "SUBSIDENCE": "land_subsidence_m_per_year", "COASTAL_EROSION": "coastal_erosion"},
            "drought": {"MAX_CONS_DRYDAYS_1MM": "max_consecutive_dry_days", "HOTDAYS40C": "days_above_40c", "WS": "water_stress_index"},
            "hurricane_wind": {"HU_MAX_SPEED": "max_wind_speed_ms", "HU_AF": "annual_frequency"},
            "wildfire": {"MAX_CONS_DRYDAYS_1MM": "max_consecutive_dry_days", "HOTDAYS40C": "days_above_40c", "AVG_VC": "average_vegetation_cover_pct"},
            "hail": {"HAILDAYS": "hail_days", "PR_DAYS_10MM": "precipitation_days_above_10mm", "MAXTEMP": "max_temperature_c"},
            "landslide": {"P_LANDSLIDE": "landslide_probability", "HEAVY_PR_DAYS": "heavy_precipitation_days"},
            "earthquake": {"PGA": "peak_ground_acceleration_g"},
        }
        for hazard, fields in labels.items():
            section = raw.get(hazard, {})
            if section:
                out["hazards"][hazard] = {label: section.get(k) for k, label in fields.items()}
        return out

    @staticmethod
    def _format_resilience(raw: dict[str, Any]) -> dict[str, Any]:
        ids = raw.get("identifiers", {})
        out: dict[str, Any] = {
            "scenario": ids.get("SCENARIO"),
            "period": ids.get("PERIOD"),
            "data_version": raw.get("data_version"),
            "location": {
                "resolved_latitude": ids.get("LATITUDE"),
                "resolved_longitude": ids.get("LONGITUDE"),
            },
            "adaptation": {},
            "societal_resilience": {},
        }
        adaptation = {
            "heat_stress_adaptation": ("heat_stress", {"BUILDING_DENSITY": "building_density", "URBAN_GREENERY": "urban_greenery"}),
            "inland_flooding_adaptation": ("inland_flooding", {"POROSITY": "soil_porosity", "IF_DIRECT_BARRIER": "direct_barriers", "IF_DRAINAGE": "drainage_systems", "IF_NATURE_BASED_SOLUTION": "nature_based_solutions", "IF_STORAGE_AND_CONTROL": "storage_and_control"}),
            "coastal_flooding_adaptation": ("coastal_flooding", {"CF_COASTAL_DEFENSE": "coastal_defenses", "CF_NATURAL_BUFFER": "natural_buffers", "CF_DRAINAGE": "drainage_systems", "CF_STORAGE_AND_CONTROL": "storage_and_control"}),
            "hurricane_wind_adaptation": ("hurricane_wind", {"BUILDING_STRENGTH": "building_strength", "IF_STORAGE_AND_CONTROL": "storage_and_control", "IF_DIRECT_BARRIER": "direct_barriers"}),
            "drought_adaptation": ("drought", {"WATER_WORKS": "water_works", "WATER_STORAGE": "water_storage", "WATER_AMENITY": "water_amenities", "WATER_WELL": "water_wells"}),
            "wildfire_adaptation": ("wildfire", {"FIRE_RESPONSE": "fire_response_capacity", "FIRE_PREVENTION": "fire_prevention", "FIRE_DETECTION": "fire_detection"}),
            "hail_adaptation": ("hail", {"BUILDING_STRENGTH": "building_strength", "IF_DIRECT_BARRIER": "direct_barriers", "IF_STORAGE_AND_CONTROL": "storage_and_control", "IF_DRAINAGE": "drainage_systems", "IF_NATURE_BASED_SOLUTION": "nature_based_solutions"}),
            "landslide_adaptation": ("landslide", {"VEG_COVER": "vegetation_cover", "LANDSLIDE_DEFENSE": "landslide_defense_systems", "LANDSLIDE_C_DEFENSE": "coastal_landslide_defenses"}),
            "earthquake_adaptation": ("earthquake", {"BUILDING_SPARSITY": "building_sparsity"}),
        }
        for raw_key, (hazard, fields) in adaptation.items():
            section = raw.get(raw_key, {})
            if section:
                out["adaptation"][hazard] = {label: section.get(k) for k, label in fields.items()}
        soc = raw.get("societal_resilience", {})
        if soc:
            out["societal_resilience"] = {
                "gni_per_capita_usd": soc.get("LOC_GNI"),
                "vulnerable_population_pct": soc.get("VUL_POP"),
                "human_development_index": soc.get("HDI"),
                "governance_effectiveness": soc.get("GFCP"),
            }
        return out

    @staticmethod
    def _format_analytics(raw: dict[str, Any]) -> dict[str, Any]:
        ids = raw.get("identifiers", {})
        out: dict[str, Any] = {
            "scenario": ids.get("SCENARIO"),
            "data_version": raw.get("data_version"),
            "location": {
                "resolved_latitude": ids.get("LATITUDE"),
                "resolved_longitude": ids.get("LONGITUDE"),
            },
        }
        ins = raw.get("insurance", {})
        if ins:
            out["insurance"] = {"fire_rate_pct": ins.get("INS_RATE_FIRE"), "flood_rate_pct": ins.get("INS_RATE_FLOOD"), "annual_rate_pct": ins.get("INS_RATE_ANNUAL")}
        util = raw.get("utility", {})
        if util:
            out["utility_costs"] = {"cooling_rate_pct": util.get("UTIL_RATE_COOLING"), "heating_rate_pct": util.get("UTIL_RATE_HEATING"), "annual_rate_pct": util.get("UTIL_RATE_ANNUAL")}
        capex = raw.get("capex", {})
        if capex:
            out["capital_expenditure"] = {"fire_capex_pct": capex.get("CAPEX_FIRE"), "flood_capex_pct": capex.get("CAPEX_FLOOD"), "cooling_degree_day_capex_pct": capex.get("CAPEX_CDD"), "annual_capex_pct": capex.get("CAPEX_ANNUAL")}
        disc = raw.get("discount", {})
        if disc:
            out["discount_rates"] = {"10_year_pct": disc.get("10_YEAR_DISCOUNT"), "25_year_pct": disc.get("25_YEAR_DISCOUNT"), "75_year_pct": disc.get("75_YEAR_DISCOUNT")}
        downtime = raw.get("operation_downtime", {})
        efficiency = raw.get("operation_efficiency", {})
        out["operational_impact"] = {
            "downtime_days_annual": downtime.get("DOWNTIME_DAYS_ANNUAL") if downtime else None,
            "efficiency_loss_pct": efficiency.get("EFFICIENCY_LOSS_ANNUAL") if efficiency else None,
        }
        workforce = raw.get("workforce_productivity", {})
        if workforce:
            out["workforce_productivity"] = {"productivity_loss_pct": workforce.get("PRODUCTIVITY_LOSS_ANNUAL")}
        maint = raw.get("maintenance_cost", {})
        if maint:
            out["maintenance"] = {"annual_rate_pct": maint.get("MAINT_RATE_ANNUAL")}
        insur = raw.get("insurability", {})
        if insur:
            out["insurability"] = {"uninsurable_coastal": insur.get("UNINSURABLE_COASTAL"), "uninsurable_fire": insur.get("UNINSURABLE_FIRE"), "uninsurable_inland": insur.get("UNINSURABLE_INLAND"), "uninsurable_total": insur.get("UNINSURABLE_TOTAL")}
        return out

    # ── aggregators (concurrent; tolerate partial failure) ──
    async def get_full_report(
        self, *, scenario: str,
        address: str | None = None, latitude: float | None = None, longitude: float | None = None,
    ) -> dict[str, Any]:
        self._validate(scenario, None, address, latitude, longitude, require_period=False)
        score_calls = [
            self.get_scores(scenario=scenario, period=p, address=address, latitude=latitude, longitude=longitude)
            for p in PERIODS
        ]
        results = await asyncio.gather(
            *score_calls,
            self.get_analytics(scenario=scenario, address=address, latitude=latitude, longitude=longitude),
            self.get_resilience_data(scenario=scenario, period="2025", address=address, latitude=latitude, longitude=longitude),
            return_exceptions=True,
        )
        scores = results[:4]
        analytics, resilience = results[4], results[5]
        return self._assemble(
            scenario, address, latitude, longitude,
            dict(zip(PERIODS, scores)), analytics=analytics, resilience=resilience,
        )

    async def get_profile(
        self, *, scenario: str, period: str,
        address: str | None = None, latitude: float | None = None, longitude: float | None = None,
    ) -> dict[str, Any]:
        self._validate(scenario, period, address, latitude, longitude, require_period=True)
        scores, risk, resilience, analytics = await asyncio.gather(
            self.get_scores(scenario=scenario, period=period, address=address, latitude=latitude, longitude=longitude),
            self.get_risk_data(scenario=scenario, period=period, address=address, latitude=latitude, longitude=longitude),
            self.get_resilience_data(scenario=scenario, period=period, address=address, latitude=latitude, longitude=longitude),
            self.get_analytics(scenario=scenario, address=address, latitude=latitude, longitude=longitude),
            return_exceptions=True,
        )
        return self._assemble(
            scenario, address, latitude, longitude,
            {period: scores}, analytics=analytics, resilience=resilience, risk=risk, risk_period=period,
        )

    def _assemble(
        self,
        scenario: str,
        address: str | None,
        latitude: float | None,
        longitude: float | None,
        scores_by_period: dict[str, Any],
        *,
        analytics: Any = None,
        resilience: Any = None,
        risk: Any = None,
        risk_period: str | None = None,
    ) -> dict[str, Any]:
        """Merge concurrent results into the report dict + a redacted
        ``section_errors`` map. ``_REPORT`` sentinel marks the shape so tools
        can construct ClimateRiskReport directly."""
        section_errors: dict[str, str] = {}
        resolved_lat = resolved_lon = None
        period_block: dict[str, Any] = {}
        for period, result in scores_by_period.items():
            if isinstance(result, Exception):
                section_errors[f"scores_{period}"] = _redact(result)
                continue
            period_block[period] = {
                "overall": result.get("overall"),
                "hazard_scores": result.get("hazard_scores"),
            }
            loc = result.get("location") or {}
            if resolved_lat is None and loc.get("resolved_latitude") is not None:
                resolved_lat, resolved_lon = loc["resolved_latitude"], loc.get("resolved_longitude")

        report: dict[str, Any] = {
            "scenario": scenario,
            "location": {
                "address": address, "latitude": latitude, "longitude": longitude,
                "resolved_latitude": resolved_lat, "resolved_longitude": resolved_lon,
            },
            "scores_by_period": period_block,
            "section_errors": section_errors,
        }
        if analytics is not None:
            if isinstance(analytics, Exception):
                section_errors["financial_impact"] = _redact(analytics)
            else:
                report["financial_impact"] = {
                    k: v for k, v in analytics.items()
                    if k not in ("scenario", "data_version", "location")
                }
        if resilience is not None:
            if isinstance(resilience, Exception):
                section_errors["societal_resilience"] = _redact(resilience)
            else:
                report["societal_resilience"] = {
                    "adaptation": resilience.get("adaptation"),
                    "societal_resilience": resilience.get("societal_resilience"),
                }
        if risk is not None:
            if isinstance(risk, Exception):
                section_errors["physical_risk"] = _redact(risk)
            else:
                report["physical_risk"] = {"period": risk_period, "hazards": risk.get("hazards")}
        return report
