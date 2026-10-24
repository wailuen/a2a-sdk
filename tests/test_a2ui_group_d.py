"""Group D A2UI conformance tests (SC-D1, SC-D2) — w009.

SC-D1: Pre-wire validation for domain card wire() output.
SC-D2: allowed_components filtering via BaseAgentSettings.a2ui_allowed_components.
"""

from __future__ import annotations

import gc
from typing import Any, ClassVar

import pytest

from agent_sdk.a2ui.translator import A2uiCapabilities
from agent_sdk.agent.events import ArtifactEvent
from agent_sdk.agent.registry import ToolSet
from agent_sdk.agent.runner import build_artifact, _validate_a2ui_wire
from agent_sdk.app import Agent
from agent_sdk.config import BaseAgentSettings
from agent_sdk.models.content_types import (
    ContentModel,
    KpiCard,
    MetricItem,
    TimeSeriesChart,
    TimeSeriesDataPoint,
    _REGISTRY,
    register_content_type,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_DOMAIN_CATALOG = "urn:test-d-catalog:v1"


class _DomainBase(ContentModel):
    """Base class for test domain cards (non-Standard-Profile catalog)."""

    catalog_id: ClassVar[str] = _DOMAIN_CATALOG

    def to_plain_text(self) -> str:
        return "domain card"


# ---------------------------------------------------------------------------
# Stub ContentModel for direct _validate_a2ui_wire tests
# ---------------------------------------------------------------------------


class _StubContentModel(ContentModel):
    """Minimal concrete ContentModel subclass for tests that need a payload
    instance without exercising any real domain card logic."""

    data_type: ClassVar[str] = "_stub"
    component: ClassVar[str] = "Stub"
    catalog_id: ClassVar[str] = _DOMAIN_CATALOG

    def to_plain_text(self) -> str:
        return "_stub"


# ---------------------------------------------------------------------------
# SC-D1: Pre-wire validation in build_artifact()
# ---------------------------------------------------------------------------


class _BadDomainCard(_DomainBase):
    """Domain card whose wire() returns {} (empty dict) — non-conformant."""

    data_type: ClassVar[str] = "_test_bad_domain_card_d1"
    component: ClassVar[str] = "TestBadDomainCardD1"

    def wire(self) -> dict[str, Any]:  # type: ignore[override]
        # Returns an empty dict — must trigger ValueError in _validate_a2ui_wire
        return {}


class _GoodDomainCard(_DomainBase):
    """Domain card whose wire() returns a valid non-empty dict."""

    data_type: ClassVar[str] = "_test_good_domain_card_d1"
    component: ClassVar[str] = "TestGoodDomainCardD1"
    value: str = "ok"

    def wire(self) -> dict[str, Any]:  # type: ignore[override]
        return {"value": self.value}


@pytest.fixture(autouse=False)
def _register_d1_cards():
    """Register and clean up test cards for SC-D1 tests."""
    register_content_type(_BadDomainCard)
    register_content_type(_GoodDomainCard)
    yield
    _REGISTRY.pop("_test_bad_domain_card_d1", None)
    _REGISTRY.pop("_test_good_domain_card_d1", None)


def _make_event(model: ContentModel) -> ArtifactEvent:
    return ArtifactEvent(
        data_type=model.data_type,
        tool_name="test_tool",
        model=model,
    )


# Capabilities that allow our domain catalog so translate() is called
_CAPS_DOMAIN_ON = A2uiCapabilities(tier="core", catalogs=[_DOMAIN_CATALOG])
# tier="none" → translate() returns None for ALL types (including domain)
_CAPS_DOMAIN_OFF = A2uiCapabilities(tier="none")


def test_d1_bad_domain_card_wire_empty_raises_value_error(_register_d1_cards):
    """SC-D1 AC: A domain card whose wire() returns {} triggers ValueError
    at artifact-build time with a message identifying the content type."""
    bad_card = _BadDomainCard()
    event = _make_event(bad_card)

    with pytest.raises(ValueError, match="_BadDomainCard"):
        build_artifact(event, _CAPS_DOMAIN_ON)


def test_d1_bad_domain_card_error_message_contains_data_type(_register_d1_cards):
    """SC-D1: The error message must identify the content type (data_type)."""
    bad_card = _BadDomainCard()
    event = _make_event(bad_card)

    with pytest.raises(ValueError) as exc_info:
        build_artifact(event, _CAPS_DOMAIN_ON)

    msg = str(exc_info.value)
    # Must name either the class name or the data_type
    assert "_BadDomainCard" in msg or "_test_bad_domain_card_d1" in msg


def test_d1_good_domain_card_wire_nonempty_does_not_raise(_register_d1_cards):
    """SC-D1: A domain card with a well-formed wire() must NOT raise."""
    good_card = _GoodDomainCard(value="hello")
    event = _make_event(good_card)
    # Should succeed without raising
    artifact = build_artifact(event, _CAPS_DOMAIN_ON)
    assert artifact is not None
    # TextPart + A2UI DataPart(open); no close DataPart (GH-214 ruling
    # https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762).
    assert len(artifact.parts) == 2


def test_d1_bad_domain_card_gated_off_does_not_raise(_register_d1_cards):
    """SC-D1: When A2UI is gated off via tier="none" (translate() returns None),
    wire() is not called by _validate_a2ui_wire and no error is raised for the
    bad card — the DataPart fallback path uses model_dump, not wire()."""
    bad_card = _BadDomainCard()
    event = _make_event(bad_card)
    # tier="none" → translate() returns None → _validate_a2ui_wire not called
    artifact = build_artifact(event, _CAPS_DOMAIN_OFF)
    assert artifact is not None
    assert len(artifact.parts) == 2  # TextPart + model_dump DataPart


def test_d1_validate_a2ui_wire_direct_empty_list():
    """_validate_a2ui_wire raises when given an empty list."""
    stub_payload = _StubContentModel()

    with pytest.raises(ValueError, match="non-empty list"):
        _validate_a2ui_wire(stub_payload, [])


def test_d1_validate_a2ui_wire_direct_non_list():
    """_validate_a2ui_wire raises when given a plain dict instead of list."""
    stub_payload = _StubContentModel()

    with pytest.raises(ValueError, match="non-empty list"):
        _validate_a2ui_wire(stub_payload, {"type": "bad"})  # type: ignore[arg-type]


def test_d1_standard_profile_type_wire_not_double_validated():
    """SC-D1: Standard Profile types (KpiCard etc.) must NOT be re-validated
    via wire() — they're Pydantic-validated already. build_artifact must succeed."""
    kpi = KpiCard(metrics=[MetricItem(label="A", value=1)])
    event = _make_event(kpi)
    # Standard catalog capabilities (KpiCard is always allowed)
    caps = A2uiCapabilities(tier="core", catalogs=["urn:a2ui-profile:standard:v1"])
    artifact = build_artifact(event, caps)
    assert artifact is not None
    # TextPart + A2UI DataPart(open) (GH-214: no close DataPart)
    assert len(artifact.parts) == 2


# ---------------------------------------------------------------------------
# RT-004: SI-2 — _validate_a2ui_wire must never interpolate exception text or
# payload reprs into the ValueError it raises. On the A2A path that error is
# swallowed into a fixed wire message, but AG-UI's stream handler logs the
# full exception (routes/ag_ui.py logger.exception), so any payload content
# embedded in the message text would reach the process log.
#
# The actual reachable call site for a wire()-raises domain card is
# translator.py::translate()'s own (previously unguarded) payload.wire()
# call, not _validate_a2ui_wire's redundant re-check: build_artifact() and
# ag_ui.py's map() both call translate() BEFORE validate_a2ui_delivery
# (which is what invokes _validate_a2ui_wire), so a raise from wire() was
# already propagating — as the raw, unwrapped exception, str(exc) intact —
# out of translate() before _validate_a2ui_wire's own try/except ever ran.
# Fixed in both places; see agent_sdk/a2ui/translator.py::translate().
# ---------------------------------------------------------------------------

_SENSITIVE_SUBSTRING = "sk-live-secret-token-should-never-leak-4f9c2b"


class _WireRaisesDomainCard(_DomainBase):
    """Domain card whose wire() raises, with sensitive content in the
    exception's own message (standing in for upstream/tool payload content
    that ended up embedded in the exception by the domain card author)."""

    data_type: ClassVar[str] = "_test_wire_raises_d1"
    component: ClassVar[str] = "TestWireRaisesD1"

    def wire(self) -> dict[str, Any]:  # type: ignore[override]
        raise RuntimeError(f"upstream payload dump: {_SENSITIVE_SUBSTRING}")


class _WireNonDictDomainCard(_DomainBase):
    """Domain card whose wire() returns a truthy non-dict value carrying
    sensitive payload content — reaches the ``not isinstance(..., dict)``
    branch rather than the ``not wire_val`` (falsy) branch."""

    data_type: ClassVar[str] = "_test_wire_nondict_d1"
    component: ClassVar[str] = "TestWireNonDictD1"

    def wire(self) -> dict[str, Any]:  # type: ignore[override]
        return [_SENSITIVE_SUBSTRING]  # type: ignore[return-value]


@pytest.fixture(autouse=False)
def _register_rt004_si2_cards():
    register_content_type(_WireRaisesDomainCard)
    register_content_type(_WireNonDictDomainCard)
    yield
    _REGISTRY.pop("_test_wire_raises_d1", None)
    _REGISTRY.pop("_test_wire_nondict_d1", None)


def test_rt004_wire_exception_message_omits_exception_text():
    """SI-2: a wire() raise must surface only the exception's type name, never
    str(exc) — which may carry upstream/tool payload content."""
    card = _WireRaisesDomainCard()

    with pytest.raises(ValueError) as exc_info:
        _validate_a2ui_wire(card, [{"version": "1.0"}])

    msg = str(exc_info.value)
    assert _SENSITIVE_SUBSTRING not in msg
    assert "RuntimeError" in msg


def test_rt004_wire_nondict_message_omits_payload_repr():
    """SI-2: a wire() returning a non-dict must surface only the returned
    value's type name, never its repr."""
    card = _WireNonDictDomainCard()

    with pytest.raises(ValueError) as exc_info:
        _validate_a2ui_wire(card, [{"version": "1.0"}])

    msg = str(exc_info.value)
    assert _SENSITIVE_SUBSTRING not in msg
    assert "list" in msg


def test_rt004_build_artifact_wire_exception_omits_payload(_register_rt004_si2_cards):
    """End-to-end via build_artifact: the raised ValueError must not leak the
    domain card's wire() exception text into what a transport might log."""
    card = _WireRaisesDomainCard()
    event = _make_event(card)

    with pytest.raises(ValueError) as exc_info:
        build_artifact(event, _CAPS_DOMAIN_ON)

    assert _SENSITIVE_SUBSTRING not in str(exc_info.value)


def test_rt004_build_artifact_wire_nondict_omits_payload(_register_rt004_si2_cards):
    """End-to-end via build_artifact: the raised ValueError must not leak the
    domain card's non-dict wire() return value into what a transport might
    log."""
    card = _WireNonDictDomainCard()
    event = _make_event(card)

    with pytest.raises(ValueError) as exc_info:
        build_artifact(event, _CAPS_DOMAIN_ON)

    assert _SENSITIVE_SUBSTRING not in str(exc_info.value)


def test_rt004_translate_wire_exception_omits_payload(_register_rt004_si2_cards):
    """translate() itself (not just _validate_a2ui_wire) must guard the
    wire()/to_markdown() call — this is the call site build_artifact and
    ag_ui.py's map() actually reach first."""
    from agent_sdk.a2ui.translator import translate

    card = _WireRaisesDomainCard()

    with pytest.raises(ValueError) as exc_info:
        translate(card, capabilities=_CAPS_DOMAIN_ON)

    msg = str(exc_info.value)
    assert _SENSITIVE_SUBSTRING not in msg
    assert "RuntimeError" in msg


def test_rt004_wire_exception_does_not_leak_via_logger_exception(_register_rt004_si2_cards):
    """SI-2, end to end: simulate exactly what AG-UI's stream handler does
    (``logger.exception(...)`` on the caught exception) and assert the
    sensitive substring is absent from the FULL formatted log record —
    traceback included. A ``raise ValueError(...) from exc`` would pass the
    narrower message-only assertions above yet still leak here, because
    logger.exception() walks the chained __cause__ and reprints exc's own
    message; only `from None` closes that."""
    import io
    import logging

    card = _WireRaisesDomainCard()
    event = _make_event(card)

    logger = logging.getLogger("test_rt004_logger_leak")
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    logger.addHandler(handler)
    logger.propagate = False
    try:
        try:
            build_artifact(event, _CAPS_DOMAIN_ON)
        except Exception:
            logger.exception("ag-ui stream failed")
    finally:
        logger.removeHandler(handler)

    logged = stream.getvalue()
    assert logged, "build_artifact did not raise — assertion below would be vacuous"
    assert _SENSITIVE_SUBSTRING not in logged


# ---------------------------------------------------------------------------
# SC-D2: allowed_components filtering
# ---------------------------------------------------------------------------

def _make_settings(tmp_path, allowed_components=None) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        AGENT_SDK_A2UI_ALLOWED_COMPONENTS=allowed_components,
    )


def test_d2_allowed_components_field_defaults_none(tmp_path):
    """SC-D2: a2ui_allowed_components field defaults to None (no filter)."""
    settings = _make_settings(tmp_path)
    assert settings.a2ui_allowed_components is None


def test_d2_allowed_components_field_accepts_list(tmp_path):
    """SC-D2: a2ui_allowed_components can be set to a list of component names."""
    settings = _make_settings(tmp_path, allowed_components=["KpiCard"])
    assert settings.a2ui_allowed_components == ["KpiCard"]


def test_d2_agent_with_allowed_kpicard_rejects_timeseries_emits(tmp_path):
    """SC-D2 AC: Agent with a2ui_allowed_components=["KpiCard"] → attempting to
    register a TimeSeriesChart emits tool raises ValueError at build_app() time."""
    from agent_sdk.testing import FakeModelClient

    settings = _make_settings(tmp_path, allowed_components=["KpiCard"])
    ts_tools = ToolSet()

    @ts_tools.tool(tier=1, emits=TimeSeriesChart)
    async def bad_ts_tool(inp: KpiCard) -> TimeSeriesChart:  # type: ignore[misc]
        """A tool that emits TimeSeriesChart, which is not in the allowed list."""
        return TimeSeriesChart(
            chart_type="line",
            title="x",
            data=[TimeSeriesDataPoint(date="2026-01-01", value=1.0)],
        )

    agent = Agent(
        settings=settings,
        persona="test agent",
        toolsets=[ts_tools],
        model_client=FakeModelClient(),
    )

    with pytest.raises(ValueError, match="a2ui_allowed_components"):
        agent.build_app()


def test_d2_agent_with_allowed_kpicard_accepts_kpicard_emits(tmp_path):
    """SC-D2 AC: Agent with a2ui_allowed_components=["KpiCard"] → KpiCard emits
    tool is accepted without error."""
    from agent_sdk.testing import FakeModelClient

    settings = _make_settings(tmp_path, allowed_components=["KpiCard"])
    kpi_tools = ToolSet()

    @kpi_tools.tool(tier=1, emits=KpiCard, read_only=True)
    async def good_kpi_tool(inp: KpiCard) -> KpiCard:  # type: ignore[misc]
        """A tool that emits KpiCard — allowed."""
        return KpiCard(metrics=[MetricItem(label="A", value=1)])

    agent = Agent(
        settings=settings,
        persona="test agent",
        toolsets=[kpi_tools],
        model_client=FakeModelClient(),
    )

    # Should build without error
    app = agent.build_app()
    try:
        app.state.credential_store.close()
    except Exception:
        pass
    gc.collect()


def test_d2_none_allowed_components_permits_all_types(tmp_path):
    """SC-D2: When a2ui_allowed_components=None (default), any registered
    emits type is accepted (backward-compatible behavior)."""
    from agent_sdk.testing import FakeModelClient

    settings = _make_settings(tmp_path, allowed_components=None)
    mixed_tools = ToolSet()

    @mixed_tools.tool(tier=1, emits=KpiCard, read_only=True)
    async def kpi_tool(inp: KpiCard) -> KpiCard:
        return KpiCard(metrics=[MetricItem(label="A", value=1)])

    @mixed_tools.tool(tier=1, emits=TimeSeriesChart, read_only=True)
    async def ts_tool(inp: KpiCard) -> TimeSeriesChart:
        return TimeSeriesChart(
            chart_type="line",
            title="x",
            data=[TimeSeriesDataPoint(date="2026-01-01", value=1.0)],
        )

    agent = Agent(
        settings=settings,
        persona="test agent",
        toolsets=[mixed_tools],
        model_client=FakeModelClient(),
    )

    # Should build without error
    app = agent.build_app()
    try:
        app.state.credential_store.close()
    except Exception:
        pass
    gc.collect()


def test_d2_get_system_prompt_section_filters_disallowed_types():
    """GH-116: get_system_prompt_section(allowed_components=[...]) must omit
    schema entries and few-shot examples for component types that are not in
    the allowlist, matching the filtering behaviour of its 3 siblings
    (supported_catalogs, data_types_for_catalog, a2ui_extension)."""
    from agent_sdk.a2ui.catalog import get_system_prompt_section

    section = get_system_prompt_section(allowed_components=["KpiCard"])
    assert "KpiCard" in section
    assert "TimeSeriesChart" not in section, (
        f"disallowed type TimeSeriesChart must not appear in a filtered "
        f"system prompt section; got:\n{section}"
    )


def test_d2_get_system_prompt_section_none_includes_all_types():
    """GH-116: allowed_components=None (default) must retain full-catalog
    behaviour — backward compatible with no filtering."""
    from agent_sdk.a2ui.catalog import get_system_prompt_section

    section = get_system_prompt_section()
    assert "KpiCard" in section
    assert "TimeSeriesChart" in section


def test_d2_agent_build_app_system_prompt_omits_disallowed_schemas(tmp_path):
    """GH-116 AC: app.py's build_app() must thread settings.a2ui_allowed_components
    through to get_system_prompt_section(), so an agent restricted to KpiCard
    does not get taught the TimeSeriesChart schema/few-shot JSON in its system
    prompt, even though _validate_emits() only gates tool-declared emits=
    targets, not the LLM's free-form JSON output."""
    from agent_sdk.testing import FakeModelClient

    settings = _make_settings(tmp_path, allowed_components=["KpiCard"])
    kpi_tools = ToolSet()

    @kpi_tools.tool(tier=1, emits=KpiCard, read_only=True)
    async def good_kpi_tool(inp: KpiCard) -> KpiCard:  # type: ignore[misc]
        """A tool that emits KpiCard — allowed."""
        return KpiCard(metrics=[MetricItem(label="A", value=1)])

    agent = Agent(
        settings=settings,
        persona="test agent",
        toolsets=[kpi_tools],
        model_client=FakeModelClient(),
    )

    app = agent.build_app()
    try:
        system_prompt = app.state.system_prompt
        assert "KpiCard" in system_prompt
        assert "TimeSeriesChart" not in system_prompt, (
            f"restricted agent's system prompt must not teach the disallowed "
            f"TimeSeriesChart schema; got:\n{system_prompt}"
        )
    finally:
        try:
            app.state.credential_store.close()
        except Exception:
            pass
        gc.collect()


def test_d2_agent_card_supportedcatalogids_reflects_allowlist(tmp_path):
    """SC-D2: When allowed_components is set, the agent card's A2UI extension
    supportedCatalogIds should reflect only the catalogs of allowed types.
    KpiCard belongs to the standard catalog."""
    from agent_sdk.a2ui.catalog import supported_catalogs

    # Only KpiCard allowed → standard catalog only
    catalogs = supported_catalogs(allowed_components=["KpiCard"])
    assert "urn:a2ui-profile:standard:v1" in catalogs

    # All allowed → standard catalog present
    catalogs_all = supported_catalogs(allowed_components=None)
    assert "urn:a2ui-profile:standard:v1" in catalogs_all


# ---------------------------------------------------------------------------
# GH-56: Domain catalog gating fix — allows() must emit domain types freely
# when tier is active; only tier="none" suppresses them.
# ---------------------------------------------------------------------------


class _GH56DomainCard(_DomainBase):
    """Domain card used for GH-56 AC1/AC2 tests."""

    data_type: ClassVar[str] = "_test_gh56_domain_card"
    component: ClassVar[str] = "TestGH56DomainCard"
    label: str = "gh56"

    def wire(self) -> dict[str, Any]:  # type: ignore[override]
        return {"label": self.label}


@pytest.fixture()
def _register_gh56_card():
    register_content_type(_GH56DomainCard)
    yield
    _REGISTRY.pop("_test_gh56_domain_card", None)


def test_gh56_ac1_domain_type_allowed_when_tier_core_catalog_standard(_register_gh56_card):
    """GH-56 AC1 as narrowed by GH-180: a domain type is not emitted on the A2A
    path when the declared catalogs omit its catalog; the AG-UI CUSTOM path
    (for_custom_emit) still emits it."""
    from agent_sdk.a2ui.translator import translate

    payload = _GH56DomainCard(label="test-ac1")
    caps = A2uiCapabilities(tier="core", catalogs=["urn:a2ui-profile:standard:v1"])
    assert translate(payload, capabilities=caps) is None
    result = translate(payload, capabilities=caps.for_custom_emit())
    assert result is not None
    assert isinstance(result, list)
    assert len(result) == 3


def test_gh56_ac2_domain_type_suppressed_when_tier_none(_register_gh56_card):
    """GH-56 AC2: A2uiCapabilities(tier="none") → translate() returns None
    for domain ContentModel subclasses."""
    from agent_sdk.a2ui.translator import translate

    payload = _GH56DomainCard(label="test-ac2")
    caps = A2uiCapabilities(tier="none")
    result = translate(payload, capabilities=caps)
    assert result is None, (
        "translate() must return None for domain types when tier='none'"
    )


def test_gh56_allows_domain_type_core_plus_extended_catalog_omitted(_register_gh56_card):
    """GH-56 as narrowed by GH-180: tier='core+extended' with a catalog list that
    omits the domain catalog suppresses the A2A emit; AG-UI CUSTOM still emits."""
    from agent_sdk.a2ui.translator import translate

    payload = _GH56DomainCard(label="test-extended")
    caps = A2uiCapabilities(tier="core+extended", catalogs=["urn:a2ui-profile:standard:v1"])
    assert translate(payload, capabilities=caps) is None
    assert translate(payload, capabilities=caps.for_custom_emit()) is not None


def test_gh56_standard_core_tier_gating_unaffected(_register_gh56_card):
    """GH-56 AC3: Standard-catalog tier gating (core vs extended) is unaffected.
    Extended-profile types still require tier='core+extended'."""
    from agent_sdk.a2ui.translator import translate
    from agent_sdk.models.content_types import WaterfallChart, WaterfallSegment

    payload = WaterfallChart(
        title="Test",
        segments=[WaterfallSegment(label="A", value=100.0, type="initial", cumulative=100.0)],
    )
    # core-only caps → extended standard type must still be gated off
    caps_core = A2uiCapabilities(tier="core", catalogs=["urn:a2ui-profile:standard:v1"])
    result = translate(payload, capabilities=caps_core)
    assert result is None, "Extended standard-profile type must be gated off for tier='core'"

    # core+extended → allowed
    caps_ext = A2uiCapabilities(tier="core+extended", catalogs=["urn:a2ui-profile:standard:v1"])
    result_ext = translate(payload, capabilities=caps_ext)
    assert result_ext is not None, "Extended standard-profile type must be allowed for tier='core+extended'"
