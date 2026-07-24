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
    summary is truncated with ``...`` if it would exceed 250 characters.
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
        if len(summary) > 250:
            summary = summary[:247] + "..."
        return f"{{{summary}}}"
    except Exception:
        return "{...}"


_FEW_SHOT_EXAMPLES: dict[str, str] = {
    "KpiCard": (
        '{"component":"KpiCard","metrics":[{"label":"Revenue","value":1200000,'
        '"unit":"USD","trend":"up"}],"title":"Q1 Summary"}'
    ),
    "TimeSeriesChart": (
        '{"component":"TimeSeriesChart","chart_type":"line","title":"Price History",'
        '"x_key":"date","y_key":"value","total_count":2,'
        '"data":[{"date":"2026-01-01","value":100.0},{"date":"2026-02-01","value":105.0}]}'
    ),
    "ComparisonTable": (
        '{"component":"ComparisonTable","columns":[{"key":"name","label":"Name"},'
        '{"key":"value","label":"Value"}],"rows":[{"name":"Alpha","value":1.2}]}'
    ),
    # FundPerformance uses camelCase aliases on the wire (snake_case Python fields
    # must NOT appear in serialised output — always call wire() / by_alias=True).
    "FundPerformance": (
        '{"component":"FundPerformance","fundName":"Acme Fund III",'
        '"irr":0.182,"tvpi":1.74,"dpi":0.95,"rvpi":0.79,'
        '"netIrr":0.164,"grossIrr":0.211,"moic":1.74,'
        '"asOfDate":"2025-12-31","nav":{"amount":320000000,"currency":"USD"},'
        '"asOfQuarter":4,"asOfYear":2025}'
    ),
}

_COMPACT_SCHEMAS: dict[str, str] = {
    "KpiCard": '{"metrics":[{label,value,unit?,trend?}],"title?":str}',
    "TimeSeriesChart": '{"chart_type":"line|area|bar","title":str,"x_key":str,"y_key":str,"total_count":int,"data":[{date,value,label?}]}',
    "ComparisonTable": '{"columns":[{key,label,type?}],"rows":[{...}],"title?":str}',
    "BarChart": '{"bars":[{category:str,value:float}],"title?":str,"x_key?":str,"y_key?":str}',
    "EntityList": '{"entity_type":str,"items":[{id,name,summary?}],"total_count?":int,"has_more?":bool,"title?":str,"showing?":int}',
    # prose exception — see annotation in get_system_prompt_section()
    "MarketBriefing": "(prose exception) return MarketBriefing(title=..., as_of=..., prose='...markdown...') — the wire value is a markdown string, not a card",
    # WaterfallSegment sub-shape: {label,value,type,cumulative,tooltip?}
    # type is one of: initial|final|inflow|outflow|gain|loss|subtotal
    "WaterfallChart": '{"title":str,"segments":[{label:str,value:float,type:"initial|final|inflow|outflow|gain|loss|subtotal",cumulative:float,tooltip?:str}],"subtitle?":str,"currency?":str,"entity_name?":str,"as_of_date?":str,"date_range?":{"start":str,"end":str}}',
    # MultiCategoryPeriod sub-shape: {period,categories:{name:{value,count?,metadata?}},period_total?}
    # date_range uses first/last keys (NOT start/end — frozen divergence from WaterfallChart)
    "MultiCategoryChart": '{"title":str,"periods":[{period:str,categories:{name:{value:float,count?:int}},period_total?:float}],"summary":{"by_category":{name:{value,count?}},"grand_total?":float,"period_count":int},"date_range":{"first":str,"last":str},"subtitle?":str,"unit_label?":str,"currency?":str,"entity_name?":str,"item_count?":int}',
    # FundPerformance is the sole camelCase-wire type — ALL field names use camelCase aliases
    "FundPerformance": '{"fundName?":str,"pbId?":str,"irr?":float,"tvpi?":float,"dpi?":float,"rvpi?":float,"netIrr?":float,"grossIrr?":float,"moic?":float,"quartile?":int,"asOfDate?":str,"asOfQuarter?":int,"asOfYear?":int,"nav?":{"amount?":float,"currency?":str},"calledDownPct?":float,"dryPowder?":{"amount?":float,"currency?":str},"dryPowderPct?":float,"distributed?":{"amount?":float,"currency?":str},"remainingValue?":{"amount?":float,"currency?":str},"distributedPlusRemaining?":{"amount?":float,"currency?":str}}',
    # EmailMessage sub-shape: {id,conversation_id?,subject,preview,from:{name,email},to_recipients:[{name,email}],received_at,is_read,has_attachments,importance,flag_status?,web_link}
    "EmailList": '{"messages":[{id:str,subject:str,preview:str,from:{name,email},to_recipients:[{name,email}],received_at:str,is_read:bool,has_attachments:bool,importance:"low|normal|high",flag_status?:"notFlagged|flagged|complete",web_link:str}],"total_count":int,"has_more":bool,"folder?":str,"query?":str}',
    # CalendarEvent sub-shape: {id,subject,start,end,is_all_day,is_cancelled,is_recurring,organizer:{name,email},attendees_count,importance,show_as,location?,...}
    # date_range uses start/end keys (same as WaterfallChart, frozen)
    "CalendarEvents": '{"events":[{id:str,subject:str,start:str,end:str,is_all_day:bool,is_cancelled:bool,is_recurring:bool,organizer:{name,email},attendees_count:int,importance:"low|normal|high",show_as:"free|tentative|busy|oof|workingElsewhere|unknown",location?:{display_name?,is_online?,join_url?},response_status?:"accepted|tentative|declined|none",web_link:str}],"date_range":{"start":str,"end":str},"total_count":int,"has_more":bool}',
    # UserPresence sub-shape: {availability,activity,status_message?}
    # OutOfOfficeSettings sub-shape: {is_enabled,start_date?,end_date?,internal_message?,external_message?}
    "UserProfile": '{"id":str,"display_name":str,"email":str,"given_name?":str,"surname?":str,"job_title?":str,"department?":str,"office_location?":str,"mobile_phone?":str,"business_phones":list,"manager?":{"id":str,"display_name":str,"email":str,"job_title?":str},"presence?":{"availability":str,"activity":str},"photo_url?":str,"out_of_office?":{"is_enabled":bool}}',
    "UserList": '{"users":[{id:str,display_name:str,email:str,job_title?:str,department?:str,presence?:{availability,activity}}],"total_count":int,"has_more":bool,"query?":str}',
    # DocumentItem sub-shape: {id,name,type?,modified?,link?,size?,web_url?,last_modified?,modified_by?}
    "DocumentList": '{"documents":[{id:str,name:str,type?:str,modified?:str,link?:str,size?:float,web_url?:str,last_modified?:str,modified_by?:str}],"total_count?":int,"has_more?":bool}',
}


def get_system_prompt_section(allowed_components: list[str] | None = None) -> str:
    """Return A2UI wire-contract guidance for LLM system prompts.

    Returns an empty string when no A2UI content types are registered (e.g.
    in a bare test environment that imports nothing from content_types).

    When types ARE registered the returned block lists every registered
    component with its compact schema shape and a few-shot example for the
    most common types.

    When *allowed_components* is set (SC-D2) only the matching component
    types are described — schemas and few-shot examples for disallowed
    types are omitted so the LLM is never taught output shapes it isn't
    permitted to produce.
    """
    types = _filtered_types(allowed_components)
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
        "Registered components (required fields shown, ? = optional):",
    ]
    for cls in sorted(types.values(), key=lambda c: c.component):
        tier = " [extended]" if cls.extended else ""
        schema = _COMPACT_SCHEMAS.get(cls.component) or _field_summary(cls)
        if cls.component == "MarketBriefing":
            schema += (
                " [prose — return MarketBriefing(title=..., as_of=..., prose='...markdown...')"
                " — rendered as plain markdown, not a structured card]"
            )
        lines.append(f"- {cls.component}{tier}: {schema}")

    # Few-shot examples for the most common types (only emit if registered)
    registered_names = {cls.component for cls in types.values()}
    examples = [
        (name, ex)
        for name, ex in _FEW_SHOT_EXAMPLES.items()
        if name in registered_names
    ]
    if examples:
        lines += ["", "Examples:"]
        for name, ex in examples:
            lines.append(f"  {name}: {ex}")

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

    ``deleteSurfaceSemantics`` is a NON-NORMATIVE, SDK-specific hint (NOT a
    field defined by A2UI v0.9.1 / Standard Profile v1). It carries the
    show-then-close convention (DESIGN.md §5.4/§7.1) on the card:
    ``deleteSurface`` for a surface is always delivered as its own,
    independently-folded message array — a separate A2A DataPart (or a
    separate AG-UI ``A2UI_UPDATE`` CUSTOM event) from that surface's
    create/populate messages, never bundled into the same array (critical
    fix: a strictly spec-conformant Path-A renderer folds ONE delivered
    array atomically and paints once after the fold, so a bundled
    ``deleteSurface`` would unmount the surface before it ever painted). This
    means NO special-casing is required to render this SDK's A2UI output
    correctly — ordinary per-array fold-then-paint handling, exactly what
    A2UI v0.9.1 already specifies, is sufficient. The hint value
    ``"split-delivery"`` documents this on the card as a courtesy so a
    consumer need not reverse-engineer the delivery shape, but it is not a
    spec-defined discovery mechanism and correct rendering never depends on
    reading it.
    """
    return AgentExtension(
        uri=A2UI_EXTENSION_URI,
        description="A2UI v0.9.1 over A2A DataParts",
        required=False,
        params={
            "supportedCatalogIds": supported_catalogs(allowed_components),
            "acceptsInlineCatalogs": False,
            "deleteSurfaceSemantics": "split-delivery",
        },
    )


def emits_data_type(model_cls: type[ContentModel]) -> str:
    return model_cls.data_type
