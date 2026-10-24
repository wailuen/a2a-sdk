"""GH-188: supportedCatalogIds is built from the tools' emits types."""

from __future__ import annotations

from typing import ClassVar

from agent_sdk.a2ui.catalog import CATALOG_ID, a2ui_extension, supported_catalogs
from agent_sdk.agent.registry import ToolRegistry
from agent_sdk.models.content_types import ContentModel, KpiCard
from agent_sdk.routes.agent_card import build_agent_card


class _Gh188Card(ContentModel):
    catalog_id: ClassVar[str] = "urn:test-gh188:v1"
    data_type: ClassVar[str] = "gh188_card"
    component: ClassVar[str] = "Gh188Card"

    def to_plain_text(self) -> str:
        return ""


def _domain():
    return _Gh188Card


def test_domain_only_emitter_has_no_standard_profile():
    d = _domain()
    assert supported_catalogs(None, [d]) == [d.catalog_id]


def test_profile_emitter_lists_standard_first():
    d = _domain()
    assert supported_catalogs(None, [d, KpiCard])[0] == CATALOG_ID
    assert supported_catalogs(None, [d, KpiCard])[1:] == [d.catalog_id]


def test_unemitted_domain_catalog_not_advertised():
    assert _domain().catalog_id not in supported_catalogs(None, [KpiCard])


def test_allowlist_applies_after_emits():
    d = _domain()
    assert supported_catalogs([KpiCard.component], [d, KpiCard]) == [CATALOG_ID]


def test_no_emitting_tools_gives_empty_and_extension_absent():
    assert supported_catalogs(None, []) == []
    assert supported_catalogs(None, [None, str]) == []
    ext = a2ui_extension(None, [])
    assert ext.params["supportedCatalogIds"] == []
    registry = ToolRegistry([], {})
    settings = _settings()
    card = build_agent_card(settings, registry)
    uris = [e["uri"] for e in card["capabilities"]["extensions"]]
    assert "https://a2ui.org/a2a-extension/a2ui/v0.9.1" not in uris  # GH-249


def _settings():
    from agent_sdk.config import BaseAgentSettings

    return BaseAgentSettings(DEV_MODE=True, AGENT_NAME="t")
