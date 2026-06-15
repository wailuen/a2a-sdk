"""A2UI catalog declarations for the agent card (DESIGN.md §4.5, §5.4)."""

from __future__ import annotations

from ..models.a2a import AgentExtension
from ..models.content_types import (
    A2UI_EXTENSION_URI,
    CATALOG_ID,
    ContentModel,
    registered_content_types,
)

# Field types that need no description suffix (common scalars)
_SCALAR_NAMES = {"str", "int", "float", "bool"}


def _annotation_str(ann: object, required: bool) -> tuple[str, bool]:
    """Return a (short_type_name, is_required) pair for a Pydantic field annotation.

    Handles the ``X | None`` / ``Optional[X]`` patterns that Pydantic uses for
    optional fields and strips module-path noise so the result is a readable
    one-word type name.
    """
    import types as _types
    import typing as _typing

    # UnionType covers the native `X | Y` syntax (Python 3.10+)
    if isinstance(ann, _types.UnionType):
        args = ann.__args__
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) < len(args):
            required = False  # None is one of the union members
        if len(non_none) == 1:
            return _annotation_str(non_none[0], required)
        # Multiple non-None: return the first arg name
        return getattr(non_none[0], "__name__", str(non_none[0])), required

    # typing.Union / typing.Optional
    origin = getattr(ann, "__origin__", None)
    if origin is _typing.Union:
        args = ann.__args__  # type: ignore[attr-defined]
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) < len(args):
            required = False
        if len(non_none) == 1:
            return _annotation_str(non_none[0], required)
        return getattr(non_none[0], "__name__", str(non_none[0])), required

    # list[X] → "list"
    if origin is list:
        return "list", required

    # typing.Literal → keep as "Literal"
    if origin is _typing.Literal:
        return "Literal", required

    # Plain class
    name = getattr(ann, "__name__", None)
    if name:
        return name, required

    # Fallback: use str() and strip obvious noise
    raw = str(ann)
    if raw.startswith("Optional[") and raw.endswith("]"):
        return raw[9:-1], False
    return raw, required


def _field_summary(cls: type[ContentModel]) -> str:
    """Return a compact one-liner describing the required/notable fields of *cls*.

    Reads the Pydantic model's ``model_fields`` to enumerate field names and
    their annotation strings.  Optional fields are suffixed with ``?``.  The
    summary is truncated with ``...`` if it would exceed 120 characters.
    """
    try:
        parts: list[str] = []
        for name, info in cls.model_fields.items():
            if name.startswith("_"):
                continue
            required = info.is_required()
            ann = info.annotation
            if ann is None:
                type_str = "any"
            else:
                type_str, required = _annotation_str(ann, required)
            suffix = "" if required else "?"
            parts.append(f"{name}: {type_str}{suffix}")

        summary = ", ".join(parts)
        # Truncate to keep system-prompt tokens manageable
        if len(summary) > 120:
            summary = summary[:117] + "..."
        return f"{{{summary}}}"
    except Exception:
        return "{...}"


def get_system_prompt_section() -> str:
    """Return A2UI wire-contract guidance for LLM system prompts.

    Returns an empty string when no A2UI content types are registered (e.g.
    in a bare test environment that imports nothing from content_types).

    When types ARE registered the returned block lists every registered
    component on a single line with its PascalCase name and required/optional
    fields so the LLM can pick the right schema when calling a tool.
    """
    types = registered_content_types()
    if not types:
        return ""

    lines = [
        "## A2UI Output Format",
        "",
        "When a tool returns structured data, wrap it as an A2UI Standard Profile"
        " component.",
        "Use PascalCase component names exactly as specified."
        " Required fields must be present.",
        "",
        "Registered components:",
    ]
    for cls in sorted(types.values(), key=lambda c: c.component):
        tier = " [extended]" if cls.extended else ""
        lines.append(f"- {cls.component}{tier}: {_field_summary(cls)}")

    return "\n".join(lines)


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
