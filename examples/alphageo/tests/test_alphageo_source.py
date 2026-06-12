"""AlphaGeoSource: per-call key + tenant-isolated cache, Nominatim fallback
(vendor key NEVER sent there), leak-free errors, and partial-failure
aggregation. All HTTP is a MockTransport — no network, no real key.
"""

from __future__ import annotations

from types import SimpleNamespace

import httpx
import pytest

from agent_sdk import AgentError, ErrorCategory
from src.sources.alphageo import AlphaGeoSource

VENDOR_KEY = "SECRET-VENDOR-KEY-123"
SECRET_ADDRESS = "1 Confidential Way, Hidden City, USA"


def _scores_payload(lat=40.0, lon=-74.0):
    return {
        "data_version": "v2",
        "identifiers": {"SCENARIO": "SSP245", "PERIOD": "2050", "LATITUDE": lat, "LONGITUDE": lon},
        "overall_indicators": {
            "OVERALL_RISK_SCORE_PCT": 72.0, "OVERALL_RAJ_SCORE_PCT": 60.0,
            "OVERALL_RISK_SCORE": 7.2, "OVERALL_RAJ_SCORE": 6.0,
        },
        "heat_stress": {"HEAT_SCORE": 80.0, "HEAT_RAJ_SCORE": 65.0},
    }


def _make_source(handler, *, key_holder):
    settings = SimpleNamespace(alphageo_base_url="https://app.alphageo.ai/api/public/v1")
    resolver = lambda source, field: key_holder.get("k") if field == "api_key" else None
    src = AlphaGeoSource(settings, resolver)
    src._client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler), event_hooks={"request": [src._on_request]}
    )
    return src


async def test_per_call_key_and_tenant_isolated_cache():
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers.get("authorization", ""))
        return httpx.Response(200, json=_scores_payload())

    key_holder = {"k": VENDOR_KEY}
    src = _make_source(handler, key_holder=key_holder)
    try:
        await src.get_scores(scenario="SSP245", period="2050", latitude=40.0, longitude=-74.0)
        # second identical call → served from cache, NO new upstream request
        await src.get_scores(scenario="SSP245", period="2050", latitude=40.0, longitude=-74.0)
        assert seen == [VENDOR_KEY]  # raw key in Authorization (no "Bearer "), one hit

        # a DIFFERENT tenant key must not read the first tenant's cache entry
        key_holder["k"] = "OTHER-TENANT-KEY"
        await src.get_scores(scenario="SSP245", period="2050", latitude=40.0, longitude=-74.0)
        assert seen == [VENDOR_KEY, "OTHER-TENANT-KEY"]
    finally:
        await src.aclose()


async def test_geocode_fallback_never_sends_vendor_key_to_nominatim():
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.host == "nominatim.openstreetmap.org":
            return httpx.Response(200, json=[{"lat": "40.0", "lon": "-74.0"}])
        # AlphaGeo: 500 while an address is present, 200 once lat/lon resolved
        if "address" in request.url.params:
            return httpx.Response(500, json={"detail": "geocoding failed"})
        return httpx.Response(200, json=_scores_payload())

    src = _make_source(handler, key_holder={"k": VENDOR_KEY})
    try:
        out = await src.get_scores(scenario="SSP245", period="2050", address=SECRET_ADDRESS)
        assert out["overall"]["risk_score_pct"] == 72.0  # succeeded after fallback

        nominatim = [r for r in requests if r.url.host == "nominatim.openstreetmap.org"]
        assert nominatim, "expected a Nominatim fallback call"
        for r in nominatim:
            # the vendor key must never reach Nominatim — not in headers, not anywhere
            assert "authorization" not in {k.lower() for k in r.headers}
            assert VENDOR_KEY not in str(r.url)
            assert VENDOR_KEY not in "".join(r.headers.values())
        # the retry to AlphaGeo dropped the address and used resolved lat/lon
        retried = [r for r in requests if r.url.host == "app.alphageo.ai" and "latitude" in r.url.params]
        assert retried and "address" not in retried[-1].url.params
    finally:
        await src.aclose()


async def test_geocode_strips_trailing_postcode_on_retry():
    queries: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "nominatim.openstreetmap.org":
            q = request.url.params.get("q", "")
            queries.append(q)
            # first query (with postcode) misses; stripped query hits
            if q and q[-1].isdigit():
                return httpx.Response(200, json=[])
            return httpx.Response(200, json=[{"lat": "1.0", "lon": "2.0"}])
        if "address" in request.url.params:
            return httpx.Response(500, json={})
        return httpx.Response(200, json=_scores_payload(lat=1.0, lon=2.0))

    src = _make_source(handler, key_holder={"k": VENDOR_KEY})
    try:
        out = await src.get_scores(scenario="SSP245", period="2050", address="5 Main St, Town 90210")
        assert out["location"]["resolved_latitude"] == 1.0
        assert len(queries) == 2  # tried full, then postcode-stripped
    finally:
        await src.aclose()


async def test_upstream_error_is_leak_free():
    def handler(request: httpx.Request) -> httpx.Response:
        # 4xx with a body that echoes the address — must never reach the caller
        return httpx.Response(404, json={"detail": f"no data for {SECRET_ADDRESS}"})

    src = _make_source(handler, key_holder={"k": VENDOR_KEY})
    try:
        with pytest.raises(AgentError) as ei:
            # lat/lon path so no geocode; 404 maps straight through
            await src.get_scores(scenario="SSP245", period="2050", latitude=40.0, longitude=-74.0)
        exc = ei.value
        blob = f"{exc.message} {exc.detail} {exc.category}"
        assert SECRET_ADDRESS not in blob
        assert VENDOR_KEY not in blob
        assert "app.alphageo.ai" not in blob
        assert exc.category in (ErrorCategory.UPSTREAM, ErrorCategory.NOT_FOUND)
    finally:
        await src.aclose()


async def test_auth_failure_maps_to_auth_category():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"detail": "bad key"})

    src = _make_source(handler, key_holder={"k": VENDOR_KEY})
    try:
        with pytest.raises(AgentError) as ei:
            await src.get_analytics(scenario="SSP245", latitude=40.0, longitude=-74.0)
        assert ei.value.category == ErrorCategory.AUTH
        assert VENDOR_KEY not in ei.value.message
    finally:
        await src.aclose()


@pytest.mark.parametrize(
    "kwargs, needle, forbidden",
    [
        (dict(scenario="NOPE", period="2050", address="x"), "SSP245", "NOPE"),
        (dict(scenario="SSP245", period="1999", address="x"), "2025", "1999"),
        (dict(scenario="SSP245", period="2050"), "address", None),
    ],
)
async def test_validation_lists_allowed_never_echoes_value(kwargs, needle, forbidden):
    src = _make_source(lambda r: httpx.Response(200, json={}), key_holder={"k": VENDOR_KEY})
    try:
        with pytest.raises(AgentError) as ei:
            await src.get_scores(**kwargs)
        assert ei.value.category == ErrorCategory.VALIDATION
        assert needle in ei.value.message
        if forbidden is not None:
            assert forbidden not in ei.value.message
    finally:
        await src.aclose()


async def test_missing_credential_raises_auth():
    src = _make_source(lambda r: httpx.Response(200, json=_scores_payload()), key_holder={})
    try:
        with pytest.raises(AgentError) as ei:
            await src.get_scores(scenario="SSP245", period="2050", latitude=40.0, longitude=-74.0)
        assert ei.value.category == ErrorCategory.AUTH
    finally:
        await src.aclose()


async def test_full_report_tolerates_partial_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/public/v1/scores/" and request.url.params.get("period") == "2100":
            return httpx.Response(503, json={})  # 2100 scores unavailable (retried once, still down)
        if path == "/api/public/v1/scores/":
            return httpx.Response(200, json=_scores_payload())
        if path == "/api/public/v1/analytics/":
            return httpx.Response(200, json={"identifiers": {"SCENARIO": "SSP245"}, "insurance": {"INS_RATE_ANNUAL": 1.2}})
        if path == "/api/public/v1/resilience_data/":
            return httpx.Response(200, json={"identifiers": {"SCENARIO": "SSP245"}, "societal_resilience": {"HDI": 0.9}})
        return httpx.Response(404, json={})

    src = _make_source(handler, key_holder={"k": VENDOR_KEY})
    try:
        report = await src.get_full_report(scenario="SSP245", latitude=40.0, longitude=-74.0)
        # 2025/2035/2050 present, 2100 redacted into section_errors
        assert set(report["scores_by_period"]) == {"2025", "2035", "2050"}
        assert "scores_2100" in report["section_errors"]
        assert report["section_errors"]["scores_2100"] in ("upstream error", "rate limited", "unavailable")
        assert "financial_impact" in report
        assert report["societal_resilience"]["societal_resilience"]["human_development_index"] == 0.9
        # nothing leaked into the redacted reason
        assert "app.alphageo.ai" not in str(report["section_errors"])
    finally:
        await src.aclose()
