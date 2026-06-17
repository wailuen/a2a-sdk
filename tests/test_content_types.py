"""Registry enforcement: component-name uniqueness, frozen-profile clean
registration, and re-registration idempotency (DESIGN.md §4.3)."""

from __future__ import annotations

from typing import ClassVar

import pytest

from pydantic import ValidationError

from agent_sdk.models.content_types import (
    PROFILE_TYPES,
    ContentModel,
    DocumentItem,
    DocumentList,
    KpiCard,
    MetricItem,
    _REGISTRY,
    register_content_type,
)


class _DomainCard(ContentModel):
    """Base for test domain cards — declares its own (non-Profile) catalog."""

    catalog_id: ClassVar[str] = "urn:test-catalog:v1"

    def to_plain_text(self) -> str:  # pragma: no cover - trivial fallback
        return ""


def test_duplicate_component_name_raises():
    """Two distinct classes claiming the same wire component name are rejected."""

    class CardA(_DomainCard):
        data_type: ClassVar[str] = "test_card_a"
        component: ClassVar[str] = "CollidingCard"

    class CardB(_DomainCard):
        data_type: ClassVar[str] = "test_card_b"   # distinct data_type
        component: ClassVar[str] = "CollidingCard"  # same wire name as CardA

    register_content_type(CardA)
    try:
        with pytest.raises(ValueError, match="CollidingCard"):
            register_content_type(CardB)
    finally:
        _REGISTRY.pop("test_card_a", None)
        _REGISTRY.pop("test_card_b", None)


def test_duplicate_component_across_catalogs_raises():
    """Global rule: a collision is rejected even across different catalog ids
    (A2UI resolves by bare componentType, not by catalogId)."""

    class CardC(_DomainCard):
        data_type: ClassVar[str] = "test_card_c"
        component: ClassVar[str] = "CrossCatalogCard"
        catalog_id: ClassVar[str] = "urn:catalog-one:v1"

    class CardD(_DomainCard):
        data_type: ClassVar[str] = "test_card_d"
        component: ClassVar[str] = "CrossCatalogCard"
        catalog_id: ClassVar[str] = "urn:catalog-two:v1"

    register_content_type(CardC)
    try:
        with pytest.raises(ValueError, match="CrossCatalogCard"):
            register_content_type(CardD)
    finally:
        _REGISTRY.pop("test_card_c", None)
        _REGISTRY.pop("test_card_d", None)


def test_domain_card_cannot_shadow_profile_component():
    """A domain card may not reuse a FROZEN Standard Profile component name."""

    class FakeKpi(_DomainCard):
        data_type: ClassVar[str] = "test_fake_kpi"   # unique data_type
        component: ClassVar[str] = "KpiCard"          # owned by the Profile

    try:
        with pytest.raises(ValueError, match="KpiCard"):
            register_content_type(FakeKpi)
    finally:
        _REGISTRY.pop("test_fake_kpi", None)


def test_frozen_profile_component_names_globally_unique():
    """The 14 FROZEN Profile types must have distinct wire component names —
    a regression here would mean the Profile itself is self-shadowing."""
    names = [cls.component for cls in PROFILE_TYPES]
    dupes = sorted({n for n in names if names.count(n) > 1})
    assert not dupes, f"duplicate component names in PROFILE_TYPES: {dupes}"


def test_same_class_reregistration_is_noop():
    """Re-registering the identical class must not raise (idempotency preserved
    for both the data_type and the new component check)."""
    assert _REGISTRY.get("kpi_card") is KpiCard
    assert register_content_type(KpiCard) is KpiCard   # frozen type: must not raise
    assert _REGISTRY.get("kpi_card") is KpiCard

    class ReCard(_DomainCard):
        data_type: ClassVar[str] = "test_recard"
        component: ClassVar[str] = "ReCard"

    register_content_type(ReCard)
    try:
        assert register_content_type(ReCard) is ReCard   # second call: no-op
        assert _REGISTRY["test_recard"] is ReCard
    finally:
        _REGISTRY.pop("test_recard", None)


# ── MetricItem scalar validation (issue #1) ──────────────────────────────────

def test_metric_item_rejects_bool():
    """bool must not silently coerce to 0/1 — raises ValidationError."""
    with pytest.raises((ValueError, ValidationError)):
        MetricItem(label="flag", value=True)
    with pytest.raises((ValueError, ValidationError)):
        MetricItem(label="flag", value=False)


def test_metric_item_rejects_dict():
    """Nested dict must raise rather than crash the whole task."""
    with pytest.raises((ValueError, ValidationError)):
        MetricItem(label="gni", value={"structured_value": 42000, "currency": "USD"})


def test_metric_item_rejects_list():
    with pytest.raises((ValueError, ValidationError)):
        MetricItem(label="tags", value=["a", "b"])


def test_metric_item_accepts_scalars():
    assert MetricItem(label="price", value=42.5).value == 42.5
    assert MetricItem(label="count", value=7).value == 7
    assert MetricItem(label="name", value="BTC").value == "BTC"


def test_metric_item_from_any_returns_none_for_non_scalar():
    assert MetricItem.from_any(label="gni", value={"nested": 1}) is None
    assert MetricItem.from_any(label="flag", value=True) is None
    assert MetricItem.from_any(label="tags", value=["a", "b"]) is None


def test_metric_item_from_any_returns_item_for_scalars():
    m = MetricItem.from_any(label="price", value=99.9, unit="USD")
    assert m is not None
    assert m.value == 99.9
    assert m.unit == "USD"


def test_kpi_card_from_mixed_upstream_dict():
    """Simulates a wire() that uses from_any to project a mixed upstream API response."""
    upstream = {"price": 42.5, "meta": {"source": "bloomberg"}, "active": True, "count": 3}
    metrics = [
        m for m in (MetricItem.from_any(label=k, value=v) for k, v in upstream.items())
        if m is not None
    ]
    assert len(metrics) == 2
    labels = {m.label for m in metrics}
    assert labels == {"price", "count"}


# ── DocumentList.to_plain_text type rendering (GH #42) ───────────────────────

def test_document_list_plain_text_includes_type_when_set():
    """DocumentItem.type is rendered as '(pdf)' suffix when present."""
    docs = DocumentList(
        documents=[
            DocumentItem(id="1", name="Q4 Report", type="pdf", last_modified="2026-03-31"),
        ]
    )
    text = docs.to_plain_text()
    assert "Q4 Report (pdf)" in text
    assert "2026-03-31" in text


def test_document_list_plain_text_omits_type_when_none():
    """When DocumentItem.type is None, no parenthetical type suffix appears."""
    docs = DocumentList(
        documents=[
            DocumentItem(id="2", name="Budget Overview", type=None, last_modified="2026-01-15"),
        ]
    )
    text = docs.to_plain_text()
    assert "Budget Overview" in text
    assert "(None)" not in text
    # No type parenthetical — the only parens should be the modified date
    assert "(pdf)" not in text
