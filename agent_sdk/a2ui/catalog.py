"""A2UI catalog declarations for the agent card (DESIGN.md §4.5, §5.4)."""

from __future__ import annotations

from ..models.a2a import AgentExtension
from ..models.content_types import (
    A2UI_EXTENSION_URI,
    CATALOG_ID,
    ContentModel,
    registered_content_types,
)


def _filtered_types(
    allowed_components: list[str] | None,
) -> dict[str, type[ContentModel]]:
    """Return the registered content-type map, optionally filtered to those
    whose component name is in ``allowed_components``.  None = all types."""
    all_types = registered_content_types()
    if allowed_components is None:
        return all_types
    allowed_set = set(allowed_components)
    return {dt: cls for dt, cls in all_types.items() if cls.component in allowed_set}


def supported_catalogs(allowed_components: list[str] | None = None) -> list[str]:
    """Standard catalog first, then any registered domain catalogs.

    When *allowed_components* is provided only the catalog IDs of the allowed
    component types are included (SC-D2).
    """
    catalogs = [CATALOG_ID]
    for cls in _filtered_types(allowed_components).values():
        if cls.catalog_id not in catalogs:
            catalogs.append(cls.catalog_id)
    return catalogs


def data_types_for_catalog(
    catalog_id: str, allowed_components: list[str] | None = None
) -> list[str]:
    return sorted(
        cls.data_type
        for cls in _filtered_types(allowed_components).values()
        if cls.catalog_id == catalog_id
    )


def a2ui_extension(allowed_components: list[str] | None = None) -> AgentExtension:
    """The card's A2UI extension declaration (activated via
    X-A2A-Extensions echo, §5.1).

    When *allowed_components* is set (SC-D2) only the matching catalog IDs
    are advertised in ``supportedCatalogIds``.
    """
    return AgentExtension(
        uri=A2UI_EXTENSION_URI,
        description="A2UI v0.9.1 over A2A DataParts",
        required=False,
        params={
            "supportedCatalogIds": supported_catalogs(allowed_components),
            "acceptsInlineCatalogs": False,
        },
    )


def emits_data_type(model_cls: type[ContentModel]) -> str:
    return model_cls.data_type
