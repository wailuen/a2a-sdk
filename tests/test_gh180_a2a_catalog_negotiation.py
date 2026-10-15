"""GH-180: A2A catalog negotiation. allows() must check declared catalogs for
domain models; AG-UI CUSTOM emission (for_custom_emit) is unchanged (LRN-049)."""
from __future__ import annotations

from typing import ClassVar

import pytest

from agent_sdk.a2ui.translator import CATALOG_ID, A2uiCapabilities
from agent_sdk.models.content_types import ContentModel, WaterfallChart

DOMAIN = "urn:a2ui-catalog:acme:climate:v1"


class _Domain(ContentModel):
    data_type: ClassVar[str] = "gh180_domain"
    component: ClassVar[str] = "Gh180Card"
    catalog_id: ClassVar[str] = DOMAIN

    def to_plain_text(self) -> str:
        return ""


@pytest.mark.parametrize("raw", [{}, {"catalogs": "x"}, {"catalogs": []}, {"tier": "core"}])
def test_no_usable_catalogs_gates_domain_off(raw: dict) -> None:
    caps = A2uiCapabilities.gated(True, raw)
    assert caps.catalogs == [CATALOG_ID]
    assert caps.allows(_Domain) is False


def test_declared_standard_only_gates_domain_off() -> None:
    caps = A2uiCapabilities(tier="core", catalogs=[CATALOG_ID])
    assert caps.allows(_Domain) is False


def test_declared_domain_catalog_allows_domain() -> None:
    caps = A2uiCapabilities.gated(True, {"tier": "core", "catalogs": [CATALOG_ID, DOMAIN]})
    assert caps.allows(_Domain) is True


def test_tier_none_still_blocks_domain() -> None:
    assert A2uiCapabilities(tier="none", catalogs=[DOMAIN]).allows(_Domain) is False


def test_standard_extended_still_needs_extended_tier() -> None:
    assert A2uiCapabilities(tier="core").allows(WaterfallChart) is False
    assert A2uiCapabilities(tier="core+extended").allows(WaterfallChart) is True


def test_custom_emit_ignores_declared_catalogs() -> None:
    caps = A2uiCapabilities(tier="core", catalogs=[CATALOG_ID])
    assert caps.for_custom_emit().allows(_Domain) is True
    assert caps.for_custom_emit().allows(WaterfallChart) is True


def test_custom_emit_none_tier_stays_blocked() -> None:
    assert A2uiCapabilities(tier="none", catalogs=[]).for_custom_emit().allows(_Domain) is False
