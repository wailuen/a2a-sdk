"""GH-213: from_metadata() accepts upstream A2UI's `supportedCatalogIds`."""
from __future__ import annotations

from types import SimpleNamespace
from typing import ClassVar

import pytest

from agent_sdk.a2ui.translator import CATALOG_ID, A2uiCapabilities
from agent_sdk.models.content_types import A2UI_EXTENSION_URI, ContentModel
from agent_sdk.routes.a2a import _capabilities

DOMAIN = "urn:a2ui-catalog:acme:climate:v1"


class _Domain(ContentModel):
    data_type: ClassVar[str] = "gh213_domain"
    component: ClassVar[str] = "Gh213Card"
    catalog_id: ClassVar[str] = DOMAIN

    def to_plain_text(self) -> str:
        return ""


def test_supported_catalog_ids_allows_domain() -> None:
    caps = A2uiCapabilities.gated(True, {"supportedCatalogIds": [DOMAIN]})
    assert caps.allows(_Domain) is True


@pytest.mark.parametrize("bad", ["x", [], None, {}])
def test_catalogs_unusable_falls_back_to_supported_catalog_ids(bad: object) -> None:
    caps = A2uiCapabilities.from_metadata({"catalogs": bad, "supportedCatalogIds": [DOMAIN]})
    assert caps.catalogs == [DOMAIN]


@pytest.mark.parametrize("bad", ["x", [], None])
def test_unusable_supported_catalog_ids_falls_back_to_standard(bad: object) -> None:
    caps = A2uiCapabilities.from_metadata({"supportedCatalogIds": bad})
    assert caps.catalogs == [CATALOG_ID]
    assert caps.allows(_Domain) is False


def test_catalogs_wins_when_both_present() -> None:
    caps = A2uiCapabilities.from_metadata(
        {"catalogs": [CATALOG_ID], "supportedCatalogIds": [DOMAIN]}
    )
    assert caps.catalogs == [CATALOG_ID]
    assert caps.allows(_Domain) is False


def test_gated_without_opt_in_stays_none() -> None:
    caps = A2uiCapabilities.gated(False, {"supportedCatalogIds": [DOMAIN]})
    assert caps.tier == "none"
    assert caps.allows(_Domain) is False


def test_a2a_route_resolves_supported_catalog_ids() -> None:
    message = SimpleNamespace(metadata={"a2uiClientCapabilities": {"supportedCatalogIds": [DOMAIN]}})
    request = SimpleNamespace(headers={"x-a2a-extensions": A2UI_EXTENSION_URI})
    caps = _capabilities(message, request, a2ui_enabled=True)  # type: ignore[arg-type]
    assert caps.allows(_Domain) is True


def test_v09_nested_supported_catalog_ids_allows_domain() -> None:
    caps = A2uiCapabilities.gated(True, {"v0.9": {"supportedCatalogIds": [DOMAIN]}})
    assert caps.allows(_Domain) is True


def test_precedence_catalogs_then_nested_then_flat() -> None:
    other = "urn:other:v1"
    nested = {"v0.9": {"supportedCatalogIds": [DOMAIN]}, "supportedCatalogIds": [other]}
    assert A2uiCapabilities.from_metadata(nested).catalogs == [DOMAIN]
    assert A2uiCapabilities.from_metadata({**nested, "catalogs": [CATALOG_ID]}).catalogs == [
        CATALOG_ID
    ]
    bad = {"v0.9": {"supportedCatalogIds": []}, "supportedCatalogIds": [other]}
    assert A2uiCapabilities.from_metadata(bad).catalogs == [other]


@pytest.mark.parametrize("bad", ["x", [], None])
def test_unusable_nested_falls_back_to_standard(bad: object) -> None:
    assert A2uiCapabilities.from_metadata({"v0.9": {"supportedCatalogIds": bad}}).catalogs == [
        CATALOG_ID
    ]
    assert A2uiCapabilities.from_metadata({"v0.9": "x"}).catalogs == [CATALOG_ID]


def test_a2a_route_resolves_v09_nested_supported_catalog_ids() -> None:
    message = SimpleNamespace(
        metadata={"a2uiClientCapabilities": {"v0.9": {"supportedCatalogIds": [DOMAIN]}}}
    )
    request = SimpleNamespace(headers={"x-a2a-extensions": A2UI_EXTENSION_URI})
    caps = _capabilities(message, request, a2ui_enabled=True)  # type: ignore[arg-type]
    assert caps.allows(_Domain) is True
