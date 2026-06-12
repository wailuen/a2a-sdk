"""A2UI catalog declarations for the agent card (DESIGN.md §4.5, §5.4)."""

from __future__ import annotations

from ..models.a2a import AgentExtension
from ..models.content_types import (
    A2UI_EXTENSION_URI,
    CATALOG_ID,
    ContentModel,
    registered_content_types,
)


def supported_catalogs() -> list[str]:
    """Standard catalog first, then any registered domain catalogs."""
    catalogs = [CATALOG_ID]
    for cls in registered_content_types().values():
        if cls.catalog_id not in catalogs:
            catalogs.append(cls.catalog_id)
    return catalogs


def data_types_for_catalog(catalog_id: str) -> list[str]:
    return sorted(
        cls.data_type
        for cls in registered_content_types().values()
        if cls.catalog_id == catalog_id
    )


def a2ui_extension() -> AgentExtension:
    """The card's A2UI extension declaration (activated via
    X-A2A-Extensions echo, §5.1)."""
    return AgentExtension(
        uri=A2UI_EXTENSION_URI,
        description="A2UI v0.9.1 over A2A DataParts",
        required=False,
        params={
            "supportedCatalogIds": supported_catalogs(),
            "acceptsInlineCatalogs": False,
        },
    )


def emits_data_type(model_cls: type[ContentModel]) -> str:
    return model_cls.data_type
