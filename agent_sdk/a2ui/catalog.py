"""A2UI catalog declarations for the agent card (DESIGN.md §4.5, §5.4)."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Iterable

from pydantic import BaseModel

from ..models.a2a import AgentExtension
from ..models.content_types import (
    A2UI_EXTENSION_URI,
    CATALOG_ID,
    ContentModel,
    registered_content_types,
)

logger = logging.getLogger(__name__)

# Field types that need no description suffix (common scalars)
_SCALAR_NAMES = {"str", "int", "float", "bool"}

try:  # Python 3.14+ (PEP 649)
    from annotationlib import Format

    _ANNOTATION_FORWARDREF: object | None = Format.FORWARDREF
except ImportError:  # Python 3.12 / 3.13 — inspect.get_annotations has no format=
    _ANNOTATION_FORWARDREF = None


def _own_annotation_names(klass: type) -> frozenset[str]:
    """Names *klass itself* annotates — never an inherited annotation.

    RT-001: do NOT read ``vars(klass)["__annotations__"]`` here. Under PEP 649
    (Python 3.14+) a class body's annotations are compiled into a lazy
    ``__annotate__`` function and ``__annotations__`` is absent from the class
    ``__dict__`` until something forces it, so the raw ``vars()`` read returns
    ``{}`` for every class defined in a module without ``from __future__ import
    annotations`` — silently making any "did this class declare it?" test always
    False on 3.14 while still working on 3.12/3.13. ``inspect.get_annotations``
    is non-inheriting AND PEP-649-aware, so it answers the same question across
    the whole declared ``requires-python = ">=3.12"`` range.

    ``FORWARDREF`` (3.14+) is requested because only the annotation NAMES are
    needed: it yields unresolvable forward references as placeholder objects
    instead of raising ``NameError``, so a domain card annotated with a
    not-yet-defined type never degrades this summary.
    """
    try:
        if _ANNOTATION_FORWARDREF is not None:
            return frozenset(
                inspect.get_annotations(klass, format=_ANNOTATION_FORWARDREF)  # type: ignore[call-overload]
            )
        return frozenset(inspect.get_annotations(klass))
    except (NameError, TypeError, AttributeError):
        # Last-resort: an exotic __annotate__ that raises under every format.
        logger.warning(
            "a2ui catalog: inspect.get_annotations failed for %s; falling "
            "back to raw __annotations__ (field summary may be incomplete)",
            getattr(klass, "__qualname__", klass),
        )
        return frozenset(vars(klass).get("__annotations__", {}))


def _annotation_str(ann: object, required: bool, depth: int = 0) -> tuple[str, bool]:
    """Return a (short_type_name, is_required) pair for a Pydantic field annotation.

    ``required`` is passed through unchanged: whether a field is required comes
    from ``FieldInfo.is_required()`` only, never from the annotation. A union
    containing ``None`` makes the type read ``X|null`` instead. With *depth* > 0
    a nested model is expanded to its own field list (GH-249).
    """
    import types as _types
    import typing as _typing

    origin = getattr(ann, "__origin__", None)
    if isinstance(ann, _types.UnionType) or origin is _typing.Union:
        args = ann.__args__  # type: ignore[attr-defined]
        non_none = [a for a in args if a is not type(None)]
        if not non_none:
            return "null", required
        name = "|".join(_annotation_str(a, required, depth)[0] for a in non_none)
        if len(non_none) < len(args):
            name += "|null"
        return name, required

    if origin is list:
        targs = getattr(ann, "__args__", ())
        if targs:
            return f"[{_annotation_str(targs[0], required, depth)[0]}]", required
        return "list", required

    if origin is _typing.Literal:
        return '"' + "|".join(str(v) for v in ann.__args__) + '"', required  # type: ignore[attr-defined]

    cls_name = getattr(ann, "__name__", None)
    if cls_name:
        if depth > 0 and isinstance(ann, type) and issubclass(ann, BaseModel):
            return f"{cls_name}{_nested_fields(ann, depth - 1)}", required
        return cls_name, required

    raw = str(ann)
    if raw.startswith("Optional[") and raw.endswith("]"):
        return raw[9:-1] + "|null", required
    return raw, required


def _serialization_required(model: type[BaseModel]) -> frozenset[str]:
    try:
        return frozenset(model.model_json_schema(mode="serialization").get("required", []))
    except Exception:
        return frozenset()


def _nested_fields(model: type[BaseModel], depth: int) -> str:
    wire_required = _serialization_required(model)
    parts: list[str] = []
    for name, info in model.model_fields.items():
        if info.exclude:
            continue
        wire_name = info.serialization_alias or info.alias or name
        required = info.is_required() or wire_name in wire_required
        ann = info.annotation
        type_str = "any" if ann is None else _annotation_str(ann, required, depth)[0]
        parts.append(f"{wire_name}{'' if required else '?'}: {type_str}")
    return "{" + ", ".join(parts) + "}"


def _field_summary(cls: type[ContentModel]) -> str:
    """Return a compact one-liner describing the required/notable fields of *cls*.

    Reads the Pydantic model's ``model_fields`` to enumerate field names and
    their annotation strings.  Optional fields (``not is_required()``) are suffixed
    with ``?``; nullable types read ``X|null``.  Over 250 characters, whole
    optional fields are dropped (never a required one) and ``...`` is appended.
    """
    try:
        parts: list[tuple[str, bool]] = []
        wire_required = _serialization_required(cls)
        for name, info in cls.model_fields.items():
            if name.startswith("_"):
                continue
            # RT-003/RT-005: `metadata` lives on `ContentModel` itself (the
            # SDK-wide GH-63 out-of-band disclosure envelope) and is
            # deliberately absent from every per-type frozen field table —
            # see that class's docstring and the content_types.py module
            # docstring. Because base-class fields come first in pydantic's
            # `model_fields`, leaving it in would put a cross-cutting,
            # non-domain field ahead of a type's real required fields in
            # this budget-truncated (250 char) teaching string for every
            # single registered content type, and would teach the model a
            # field its own catalog explicitly does not want it prompted
            # with per-type. The skip is keyed on WHO DECLARED the field,
            # not its name: a base-class field the subclass did not itself
            # declare is skipped (covers `metadata` today and any future
            # `ContentModel` field automatically), but a domain card that
            # deliberately redeclares `metadata` with its own semantics
            # keeps it in its own summary.
            # RT-008: "declared" must walk the full MRO, not just `cls`'s own
            # annotations — a two-level (or deeper) subclass of a card that
            # redeclares `metadata` inherits that domain declaration and must
            # keep it in its summary even without redeclaring it again.
            # RT-001: the per-class read goes through _own_annotation_names(),
            # NOT `vars(klass)["__annotations__"]` — see that helper's
            # docstring for why the raw read is silently always-empty on 3.14.
            declared_here = any(
                name in _own_annotation_names(klass)
                for klass in cls.__mro__
                if klass is not ContentModel and issubclass(klass, ContentModel)
            )
            if not declared_here and name in ContentModel.model_fields:
                continue
            wire_name = info.serialization_alias or info.alias or name
            required = info.is_required() or wire_name in wire_required
            ann = info.annotation
            if ann is None:
                type_str = "any"
            else:
                type_str, required = _annotation_str(ann, required, 1)
            suffix = "" if required else "?"
            parts.append((f"{wire_name}{suffix}: {type_str}", required))

        # Keep system-prompt tokens manageable: drop whole optional fields from
        # the end first; a required field is never dropped or cut.
        kept = list(parts)
        dropped = False
        while len(", ".join(p for p, _ in kept)) > 250:
            for i in range(len(kept) - 1, -1, -1):
                if not kept[i][1]:
                    del kept[i]
                    dropped = True
                    break
            else:
                break
        texts = [p for p, _ in kept]
        if dropped:
            texts.append("...")
        return f"{{{', '.join(texts)}}}"
    except Exception:
        logger.warning(
            "a2ui catalog: field summary generation failed for %s; using "
            "fallback summary",
            getattr(cls, "__qualname__", cls),
        )
        return "{...}"


_FEW_SHOT_EXAMPLES: dict[str, str] = {
    "KpiCard": (
        '{"metrics":[{"label":"Revenue","value":1200000,'
        '"unit":"USD","trend":"up"}],"title":"Q1 Summary"}'
    ),
    "TimeSeriesChart": (
        '{"chart_type":"line","title":"Price History",'
        '"x_key":"date","y_key":"value","total_count":2,'
        '"data":[{"date":"2026-01-01","value":100.0},{"date":"2026-02-01","value":105.0}]}'
    ),
    "ComparisonTable": (
        '{"columns":[{"key":"name","label":"Name"},'
        '{"key":"value","label":"Value"}],"rows":[{"name":"Alpha","value":1.2}]}'
    ),
    # FundPerformance uses camelCase aliases on the wire (snake_case Python fields
    # must NOT appear in serialised output — always call wire() / by_alias=True).
    # RT-004: this example deliberately omits pbId — it is the upstream
    # source-system id (provenance the model has no legitimate way to know)
    # and must never be fabricated; see the pbId note appended to the
    # FundPerformance line in get_system_prompt_section().
    "FundPerformance": (
        '{'
        '"irr":0.182,"tvpi":1.74,"dpi":0.95,"rvpi":0.79,'
        '"netIrr":0.164,"grossIrr":0.211,"moic":1.74,'
        '"asOfDate":"2025-12-31","nav":{"amount":320000000,"currency":"USD"},'
        '"asOfQuarter":4,"asOfYear":2025}'
    ),
}

_COMPACT_SCHEMAS: dict[str, str] = {
    "KpiCard": '{"metrics":[{label,value,unit?,trend?,change_pct?}],"title?":str}',
    "TimeSeriesChart": '{"chart_type":"line|area|bar","title":str,"subtitle?":str,"x_key":str,"y_key":str,"total_count":int,"data":[{date:str,value:num|null,label?:str}]}',
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
    "FundPerformance": '{"pbId?":str,"irr?":float,"tvpi?":float,"dpi?":float,"rvpi?":float,"netIrr?":float,"grossIrr?":float,"moic?":float,"quartile?":int,"asOfDate?":str,"asOfQuarter?":int,"asOfYear?":int,"nav?":{"amount?":float,"currency?":str},"calledDownPct?":float,"dryPowder?":{"amount?":float,"currency?":str},"dryPowderPct?":float,"distributed?":{"amount?":float,"currency?":str},"remainingValue?":{"amount?":float,"currency?":str},"distributedPlusRemaining?":{"amount?":float,"currency?":str}}',
    # EmailMessage sub-shape: {id,conversation_id?,subject,preview,from:{name,email},to_recipients:[{name,email}],received_at,is_read,has_attachments,importance,flag_status?,web_link}
    "EmailList": '{"messages":[{id:str,subject:str,preview:str,from:{name,email},to_recipients:[{name,email}],received_at:str,is_read:bool,has_attachments:bool,importance:"low|normal|high",flag_status?:"notFlagged|flagged|complete",web_link:str}],"total_count":int,"has_more":bool,"folder?":str,"query?":str}',
    # CalendarEvent sub-shape: {id,subject,start,end,is_all_day,is_cancelled,is_recurring,organizer:{name,email},attendees_count,importance,show_as,location?,...}
    # date_range uses start/end keys (same as WaterfallChart, frozen)
    "CalendarEvents": '{"events":[{id:str,subject:str,start:str,end:str,is_all_day:bool,is_cancelled:bool,is_recurring:bool,organizer:{name,email},attendees_count:int,importance:"low|normal|high",show_as:"free|tentative|busy|oof|workingElsewhere|unknown",location?:{display_name:str,is_online:bool,join_url?:str},response_status?:"accepted|tentative|declined|none",web_link:str}],"date_range":{"start":str,"end":str},"total_count":int,"has_more":bool}',
    # UserPresence sub-shape: {availability,activity,status_message?}
    # OutOfOfficeSettings sub-shape: {is_enabled,start_date?,end_date?,internal_message?,external_message?}
    "UserProfile": '{"id":str,"display_name":str,"email":str,"given_name?":str,"surname?":str,"job_title?":str,"department?":str,"office_location?":str,"mobile_phone?":str,"business_phones":list,"manager?":{"id":str,"display_name":str,"email":str,"job_title?":str},"presence?":{"availability":str,"activity":str},"photo_url?":str,"out_of_office?":{"is_enabled":bool}}',
    "UserList": '{"users":[{id:str,display_name:str,email:str,job_title?:str,department?:str,presence?:{availability,activity}}],"total_count":int,"has_more":bool,"query?":str}',
    # DocumentItem sub-shape: {id,name,type?,modified?,link?,size?}
    "DocumentList": '{"documents":[{id:str,name:str,type?:str,modified?:str,link?:str,size?:float}],"total_count?":int,"has_more?":bool}',
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
        "Tools deliver these A2UI cards to the user automatically when they"
        " return structured data.",
        "Do not write component JSON in your reply. Summarise tool results for"
        " the user in the format your instructions ask for, using only values"
        " the tools returned.",
        "",
        "Components tools can emit (required fields and common optional fields shown, ? = optional,"
        " |null = the value may be null):",
    ]
    for cls in sorted(types.values(), key=lambda c: c.component):
        tier = " [extended]" if cls.extended else ""
        schema = _COMPACT_SCHEMAS.get(cls.component) or _field_summary(cls)
        if cls.component == "MarketBriefing":
            schema += (
                " [prose card — a tool emits title, as_of and markdown prose;"
                " rendered as plain markdown, not a structured card]"
            )
        if cls.component == "FundPerformance":
            schema += (
                " [pbId is an upstream source-system id — emit it only when a"
                " tool result supplied one; never invent a value]"
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
        lines += [
            "",
            "Reference shapes of tool output (the resolved data object only,"
            " no `component` key; not for you to write):",
        ]
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


def supported_catalogs(
    allowed_components: list[str] | None = None,
    emits: Iterable[type] | None = None,
) -> list[str]:
    """Catalog IDs to advertise (SC-D2, GH-188).

    With *emits* (the registered tools' ``emits`` types) only catalogs of the
    types a tool can actually emit are listed, after the
    *allowed_components* filter; the Standard Profile comes first when
    present.  Without *emits*, falls back to the Standard Profile plus every
    registered catalog.
    """
    if emits is None:
        catalogs = [CATALOG_ID]
        for cls in _filtered_types(allowed_components).values():
            if cls.catalog_id not in catalogs:
                catalogs.append(cls.catalog_id)
        return catalogs
    allowed = None if allowed_components is None else set(allowed_components)
    found: list[str] = []
    for cls in emits:
        if not (isinstance(cls, type) and issubclass(cls, ContentModel)):
            continue
        if cls.catalog_id is None or (allowed is not None and cls.component not in allowed):
            continue
        if cls.catalog_id not in found:
            found.append(cls.catalog_id)
    if CATALOG_ID in found:
        found.remove(CATALOG_ID)
        found.insert(0, CATALOG_ID)
    return found


def data_types_for_catalog(
    catalog_id: str, allowed_components: list[str] | None = None
) -> list[str]:
    return sorted(
        cls.data_type
        for cls in _filtered_types(allowed_components).values()
        if cls.catalog_id == catalog_id
    )


def a2ui_extension(
    allowed_components: list[str] | None = None,
    emits: Iterable[type] | None = None,
) -> AgentExtension:
    """The card's A2UI extension declaration (activated via
    X-A2A-Extensions echo, §5.1).

    When *allowed_components* is set (SC-D2) only the matching catalog IDs
    are advertised in ``supportedCatalogIds``.

    The SDK emits no ``deleteSurface`` for the surface it creates, so the
    former ``deleteSurfaceSemantics`` param is removed (GH-214 ruling
    https://github.com/wailuen/a2a-sdk/issues/214#issuecomment-6359828762):
    clients manage surface lifetime themselves.

    ``dataEncoding`` is a NON-NORMATIVE, SDK-specific hint (LRN-134
    follow-up to GH-128/GH-113). A2UI v0.9.1's own A2A binding mandates a
    bare array at the DataPart's ``data`` field; this SDK instead wraps the
    array as ``{"messages": [...]}`` (``agent_sdk/agent/runner.py::
    build_artifact()``) because A2A v0.3.0's ``DataPart.data`` typing
    requires an object, not an array — a genuine conflict between the base
    protocol and the extension's own literal binding, resolved in favor of
    A2A-base conformance. The hint value ``"data.messages"`` documents where
    the message array actually lives so a strictly spec-conformant
    third-party A2UI Path-A renderer, which would otherwise look for the
    array directly at ``data`` and render nothing, has a wire-discoverable
    way to find it. This SDK's own first-party consumers already unwrap
    ``data.messages`` unconditionally and do not read this hint.
    """
    return AgentExtension(
        uri=A2UI_EXTENSION_URI,
        description="A2UI v0.9.1 over A2A DataParts",
        required=False,
        params={
            "supportedCatalogIds": supported_catalogs(allowed_components, emits),
            "acceptsInlineCatalogs": False,
            "dataEncoding": "data.messages",
        },
    )


def emits_data_type(model_cls: type[ContentModel]) -> str:
    return model_cls.data_type
