"""A2UI Standard Profile v1.1 content models (FROZEN — DESIGN.md §5.4).

Wire-isomorphic Pydantic models for the 14 FROZEN Profile types plus the
registry that the translator, catalog and console all read (Standard Profile
v1.1 = 14 FROZEN + 4 RESERVED names at RESERVED_COMPONENTS — 18 total). Field
contracts
are frozen at catalog ``urn:a2ui-profile:standard:v1`` — do not "fix"
inconsistencies (e.g. the two different date_range key pair shapes); they are
intentional and locked.

Reserved names (TradeActivity, CompanyInfo, DealList, InvestorProfile) have
no field contract in v1: no model exists and ``register_content_type``
refuses the component names.

``metadata`` is an SDK-wide field, not a per-type Profile field
----------------------------------------------------------------
``ContentModel`` declares ``metadata: dict[str, Any] | None = None`` once,
on the base class (RT-006) — every subclass inherits it rather than
redeclaring it. It is an SDK-WIDE out-of-band envelope (GH-63) for disclosure
annotations such as ``metadata={"coverage_note": "Partial: 5 of 20 funds"}`` —
NOT a per-type Profile v1.1 field.

Because the field is declared once on the base class, every rule about it is
enforced once on the base class too (RT-003/RT-006, round 4) — none of the
three below is a per-subclass obligation, so a domain card gets all three for
free and cannot silently opt out of them:

1. ``wire()`` emits it when set. (``MarketBriefing`` is the one carve-out:
   its ``wire()`` is the bare markdown string and cannot carry it; the AG-UI
   ``AGENT_ARTIFACT`` frame sends ``{"markdown", "metadata"?}`` instead and
   the A2A/MCP text fallback carries the ``to_plain_text()`` suffix.)
2. ``to_plain_text()`` appends it as a trailing ``key=value`` suffix. That
   method is CONCRETE on ``ContentModel`` (``self._body_text() +
   self._metadata_suffix()``); subclasses implement ``_body_text()``. Before
   this release, ``metadata`` reached ``wire()`` but no type — built-in or
   domain — ever appended it to its text fallback; this release starts
   emitting it for all of them, in one place on the base class, rather than
   as a convention each subclass would otherwise have to implement by hand.
   ``to_markdown()`` still never carries the suffix — ``MarketBriefing``'s
   prose exception keeps ``to_markdown()`` clean and picks the suffix up
   through the same base-class ``to_plain_text()`` as every other card.
3. A ``field_validator`` rejects non-finite floats anywhere in it
   (``_assert_finite``), so ``wire()``'s JSON ``null`` and the text
   fallback's ``inf`` can never disagree about the same value.

Since ``metadata`` is caller-/tool-supplied and reaches the mandatory A2A/MCP
text fallback (RT-A06), ``_metadata_suffix()`` routes each rendered key and
value through ``agent_sdk.common.redact.sanitize_text`` (control-char strip +
per-field length cap, SI-2) and bounds the assembled suffix to
``_METADATA_SUFFIX_MAX_LEN`` characters overall.

RT-004 (REVIEWS.md Round 10): a same-wave edit to the a2ui-advisor's frozen
field-contract tables (``.claude/agents/a2ui-advisor.md``,
``harness/agents/a2ui-advisor.md``, ``template/.claude/agents/a2ui-advisor.md``)
that dropped ``TimeSeriesChart``'s per-type typed ``metadata`` row to match
this base-class hoist was reverted pending maintainer ratification — a
frozen A2UI Standard Profile field contract (DESIGN.md stable core) may
not be edited inside a wave to conform to its own code. The maintainer then
ratified the removal as Profile v1.1 (REVIEWS.md Round 11, SIGNED OFF
2026-10-09, GitHub issue #153): the row is gone from all three advisor
copies, since this base-class field never implemented its typed sub-shape,
and ``metadata`` is a cross-cutting free-form field on every FROZEN type.
The catalog URN and ``CATALOG_ID`` are unchanged.

Domain extension: agents register their own card types with
``register_content_type`` — subclass ``ContentModel``, declare ``data_type``
/ ``component``, implement ``_body_text()`` (the card's own text rendering).
Do NOT override ``to_plain_text()``: it is concrete on the base class and is
what appends the ``metadata`` suffix. A card written against the older API
that overrides ``to_plain_text()`` still works — ``ContentModel.__init_subclass__``
adopts that override as the class's ``_body_text()`` — but new code should
implement ``_body_text()`` directly. Exception (RT-005, migration required):
a pre-split card that ALSO already declares its own ``_body_text`` (e.g. an
unrelated private helper of that name — a legal name before this release)
fails at import time instead of being silently adopted; see
``__init_subclass__`` below and CHANGELOG.md's RT-005 entry for the required
rename.
"""

from __future__ import annotations

import abc
import contextvars
import functools
import math
import re
import typing
import weakref
from typing import Annotated, Any, ClassVar, Literal, Union

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SerializationInfo,
    SerializerFunctionWrapHandler,
    field_serializer,
    field_validator,
    model_serializer,
    model_validator,
)

from ..common.redact import (
    LINE_TEXT_MAX_LEN,
    TITLE_TEXT_MAX_LEN,
    safe_block_text,
    safe_cell_text,
    safe_id_text,
    safe_joined_id_text,
    safe_label_text,
    safe_line_text,
    sanitize_text,
)

# Punctuation a renderer template may legitimately emit around a sanitized
# value without it being a structural delimiter — "+"/"%" in a numeric
# rendering, "." in a version/decimal, "-" as a literal hyphen, "/" as a
# renderer template, so a future renderer that introduces a genuinely new
# separator fails the build instead of shipping. Stays here, not in
# redact.py: it describes THIS module's renderer templates, not the shared
# alphabet.
_NON_SEPARATOR_GLYPHS = frozenset("-+%./")


def _sanitize_cell(value: str) -> str:
    """Thin alias for :func:`agent_sdk.common.redact.safe_cell_text` (GH-130,
    RT-002/RT-009 C-007 reconciliation). The delimiter-safety helper was
    promoted out of this module into ``common/redact.py`` so third-party
    ``ContentModel`` subclasses can import the SAME implementation instead of
    hand-rebuilding the separator alphabet per card module — do not
    reimplement it here; a second copy is the exact drift this promotion
    exists to prevent."""
    return safe_cell_text(value)


def _sanitize_line(value: str, *, max_len: int | None = LINE_TEXT_MAX_LEN) -> str:
    """Alias for :func:`agent_sdk.common.redact.safe_line_text` — for a value
    that sits ALONE on its line (GH-167). Joined values keep
    :func:`_sanitize_cell`. The result always starts at column 0, so a
    renderer keeps it out of a delimited row grammar by indenting the rows."""
    return safe_line_text(value, max_len=max_len)


def _safe_id(value: str) -> str:
    """Identifier alone on its ``id:`` line (GH-156, GH-212, SI-2): byte-exact
    for real id alphabets (``=``, ``:``, ``( )``), but unable to add a line,
    a column or flood the text block (``safe_id_text``)."""
    return safe_id_text(value, max_len=_METADATA_SUFFIX_FIELD_MAX_LEN)


def _safe_joined_id(value: str) -> str:
    """Identifier JOINED into a row with other fields (EmailList
    ``(id: ..., conversation: ...)``, FundPerformance ``source <pb_id>``):
    keeps the GH-156 rendering so it cannot forge a sibling field (GH-212)."""
    return safe_joined_id_text(value, max_len=_METADATA_SUFFIX_FIELD_MAX_LEN)


def _sanitize_block(value: str) -> str:
    """Thin alias for :func:`agent_sdk.common.redact.safe_block_text` — the
    counterpart to :func:`_sanitize_cell` for a field whose declared contract
    is a MULTI-LINE MARKDOWN DOCUMENT (``MarketBriefing.prose``), where a
    newline is the payload's own structure, not a delimiter."""
    return safe_block_text(value)


CATALOG_ID = "urn:a2ui-profile:standard:v1"
A2UI_VERSION = "v0.9.1"
A2UI_EXTENSION_URI = "https://a2ui.org/a2a-extension/a2ui/v0.9.1"
A2UI_MIME_TYPE = "application/a2ui+json"

RESERVED_COMPONENTS = ("TradeActivity", "CompanyInfo", "DealList", "InvestorProfile")

BASIC_CATALOG_COMPONENTS = (
    "Text", "Card", "Column", "Row", "List", "Tabs", "Button", "Image", "Icon",
    "Video", "AudioPlayer", "Divider", "Modal", "CheckBox", "TextField",
    "DateTimeInput", "ChoicePicker", "Slider",
)

_ARROWS = {"up": "▲", "down": "▼", "flat": "→"}

# RT-A06: metadata is a caller-supplied dict[str, Any] (GH-63 disclosure
# annotations) that reaches to_plain_text() — the mandatory text fallback on
# the A2A TextPart (agent/runner.py) and MCP tools/call text (routes/mcp.py)
# — via _metadata_suffix() below. Each key/value goes through the SAME shared
# helper as every other untrusted string reaching the wire from this SDK —
# common.redact.sanitize_text, component C-007, also called by agent/loop.py
# for model-supplied skill/tool names — and the rendered suffix as a whole is
# capped so an unbounded metadata dict cannot inflate the text fallback
# without limit.
_METADATA_SUFFIX_FIELD_MAX_LEN = 256
_METADATA_SUFFIX_MAX_LEN = 4096


_ASSERT_FINITE_MAX_DEPTH = 100

# RT-003 (round 2): re-entrancy plumbing for a ``super().to_plain_text()``
# call made from inside a card's own rendering -- see
# ContentModel.__init_subclass__ and .to_plain_text below. Keyed by the
# declaring class (not by instance) because the resolution target -- "the next
# ancestor's _body_text after this class in the MRO" -- is fixed at
# class-definition time and identical for every instance of that class.
# DBG-7: a WeakKeyDictionary, not a plain dict. Keyed by class and written
# once per subclass in __init_subclass__, a strong-keyed dict pins EVERY
# ContentModel subclass ever defined for the life of the process — including
# ones built dynamically by a card factory or created per-test — so neither the
# class nor anything it closes over is ever collectable. Weak keys make an
# entry vanish with its class; nothing outlives the class it describes, and a
# live class always still holds its own entry.
_NEXT_BODY_TEXT: "weakref.WeakKeyDictionary[type, Any]" = weakref.WeakKeyDictionary()
# Stack of (declaring_class, instance) whose _body_text is currently
# executing, most-recent last. ContextVar rather than a plain module global so
# concurrent asyncio tasks never observe each other's frames.
_BODY_TEXT_STACK: contextvars.ContextVar[tuple[tuple[type, Any], ...]] = (
    contextvars.ContextVar("_BODY_TEXT_STACK", default=())
)
# Pre-split name, kept as an alias: the stack held adopted-legacy frames only
# until DBG-5 generalised it to every _body_text implementation.
_ADOPTED_OVERRIDE_STACK = _BODY_TEXT_STACK


def _next_body_text_impl(cls: type) -> Any:
    """The ``_body_text`` implementation ``cls``'s own rendering must reach
    when it calls ``super().to_plain_text()`` -- the first ancestor (walking
    the MRO past ``cls`` itself) that declares ``_body_text`` in its OWN
    ``__dict__``. ``ContentModel`` always qualifies (its abstract stub is
    declared there), so this never fails to find one."""
    for base in cls.__mro__[1:]:
        impl = base.__dict__.get("_body_text")
        if impl is not None:
            return impl
    raise AssertionError(f"{cls.__name__}: no ancestor _body_text (unreachable)")


def _framed_body_text(impl: Any, owner: type) -> Any:
    """Wrap one ``_body_text`` implementation so the class that DECLARED it is
    on ``_BODY_TEXT_STACK`` for the duration of the call.

    That frame is the only thing that tells ``ContentModel.to_plain_text``
    where in the MRO a re-entrant ``super().to_plain_text()`` call came from —
    ``super()`` itself carries no such information across the concrete
    wrapper. Every implementation in the chain announces itself, so a
    ``super().to_plain_text()`` from any level resolves exactly one step up
    (``_NEXT_BODY_TEXT[owner]``, itself a wrapped implementation if that
    ancestor declared one) instead of re-dispatching through
    ``type(self)._body_text`` and landing back on the same function.

    DBG-5: applied to a NEW-style ``_body_text()`` override as well as to an
    adopted legacy ``to_plain_text()`` one. Wrapping only the adopted half
    made the guard asymmetric — a new override calling
    ``super().to_plain_text()`` pushed no frame, so the re-entrancy check
    never fired and the call recursed until ``RecursionError``, failing every
    artifact emission for that card type (``runner.py``'s dual-part
    ``TextPart``, ``routes/mcp.py``'s ``tools/call`` text) as an internal
    error — while the migration docs and the ``__init_subclass__`` TypeError
    below steered authors straight into that shape.
    """

    @functools.wraps(impl)
    def _framed(self: Any, *, _impl: Any = impl, _cls: type = owner) -> str:
        frame = (_cls, self)
        token = _BODY_TEXT_STACK.set(_BODY_TEXT_STACK.get() + (frame,))
        try:
            return _impl(self)  # type: ignore[no-any-return]
        finally:
            _BODY_TEXT_STACK.reset(token)

    return _framed


def _assert_finite(value: Any, _depth: int = 0) -> None:
    """Reject inf/-inf/nan anywhere in ``value``, recursing into dict/list/tuple
    and nested pydantic ``BaseModel`` instances. ``model_dump_json()`` serializes
    non-finite floats as JSON ``null`` while ``to_markdown()``/``to_plain_text()``
    render ``"inf"``/``"nan"`` literally — allowing them through would silently
    split a dual-part artifact into two different values.

    Scope (GH-95, MarketBriefing family — see that issue's AC): the field
    validators on ``BriefingKpiItem.value`` and
    ``ChartSection.data``/``TableSection.data``. Plus ONE cross-cutting caller
    added when ``metadata`` was hoisted onto ``ContentModel`` (RT-006, round 4):
    ``ContentModel._metadata_finite``. ``metadata`` earns it on GH-95's own
    stated criterion — it is the only free-form dict on every card that reaches
    BOTH ``wire()`` and the text fallback, so it is exactly the divergence this
    guard exists for. Float-typed fields elsewhere are handled by ``_Wire._finite_floats``
    (GH-173): nullable ones coerce to None, non-nullable ones reject.
    ``BriefingKpiItem.delta`` is nullable, so it coerces to None like every other nullable field (GH-173 ruling).

    ``_depth`` bounds worst-case recursion (RT-003): a cyclic or pathologically
    deep dict/list/tuple/BaseModel structure surfaces as a clean ValueError
    (pydantic wraps it into a ValidationError) instead of an uncaught
    RecursionError, which is a RuntimeError pydantic does not convert."""
    if _depth > _ASSERT_FINITE_MAX_DEPTH:
        raise ValueError("value nesting too deep to validate (possible cyclic structure)")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite float not allowed")
    if isinstance(value, BaseModel):
        for v in value.__dict__.values():
            _assert_finite(v, _depth + 1)
    elif isinstance(value, dict):
        for v in value.values():
            _assert_finite(v, _depth + 1)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _assert_finite(v, _depth + 1)


# GH-179: weak-keyed like _NEXT_BODY_TEXT. A class-keyed ``functools.cache``
# would pin every model subclass (including dynamically built ones) forever.
# The cached values are plain tuples of str, so they never reference the class.
_NULLABLE_NUMERIC_KEYS: "weakref.WeakKeyDictionary[type, tuple[str, ...]]" = (
    weakref.WeakKeyDictionary()
)
_FLOAT_FIELD_PLAN: "weakref.WeakKeyDictionary[type, tuple[tuple[str, bool], ...]]" = (
    weakref.WeakKeyDictionary()
)


def _nullable_numeric_keys(cls: type[BaseModel]) -> tuple[str, ...]:
    cached = _NULLABLE_NUMERIC_KEYS.get(cls)
    if cached is not None:
        return cached
    keys: list[str] = []
    for name, info in cls.model_fields.items():
        parts: list[Any] = []
        stack = [info.annotation]
        while stack:
            tp = stack.pop()
            parts.append(tp)
            stack.extend(typing.get_args(tp))
        if type(None) in parts and (int in parts or float in parts):
            keys.append(name)
            if info.alias:
                keys.append(info.alias)
    result = tuple(keys)
    _NULLABLE_NUMERIC_KEYS[cls] = result
    return result


def _float_field_plan(cls: type[BaseModel]) -> tuple[tuple[str, bool], ...]:
    cached = _FLOAT_FIELD_PLAN.get(cls)
    if cached is not None:
        return cached
    plan = []
    for name, info in cls.model_fields.items():
        parts: list[Any] = []
        stack = [info.annotation]
        while stack:
            tp = stack.pop()
            parts.append(tp)
            stack.extend(typing.get_args(tp))
        if float in parts:
            plan.append((name, type(None) in parts))
    result = tuple(plan)
    _FLOAT_FIELD_PLAN[cls] = result
    return result


class _Wire(BaseModel):
    # hide_input_in_errors: a rejected non-finite value must never be echoed
    # back in the error text (GH-173).
    model_config = ConfigDict(populate_by_name=True, hide_input_in_errors=True)

    @model_validator(mode="before")
    @classmethod
    def _nullable_non_finite_to_none(cls, data: Any) -> Any:
        """GH-173: pydantic rejects a non-finite float for an ``int | None``
        field before any after-validator runs, so coerce it first."""
        if not isinstance(data, dict):
            return data
        bad = [
            k
            for k in _nullable_numeric_keys(cls)
            if isinstance(data.get(k), float) and not math.isfinite(data[k])
        ]
        if not bad:
            return data
        return {**data, **dict.fromkeys(bad)}

    @model_validator(mode="after")
    def _finite_floats(self) -> Any:
        """GH-173: nullable float fields coerce nan/inf/-inf to None;
        non-nullable ones reject. Both stop ``wire()`` (json.dumps ->
        invalid ``NaN``) disagreeing with ``model_dump_json()`` (null)."""
        for name, nullable in _float_field_plan(type(self)):
            value = self.__dict__.get(name)
            if isinstance(value, float) and not math.isfinite(value):
                if not nullable:
                    raise ValueError(f"{type(self).__name__}.{name} must be a finite number")
                self.__dict__[name] = None
        return self

    def wire(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


class ContentModel(_Wire, abc.ABC):
    """Base for renderable card payloads. ``wire()`` is the surface data
    model value; ``to_plain_text()`` is the mandatory text fallback sent to
    clients without A2UI capability — the A2A dual-part artifact's
    ``TextPart`` (``agent/runner.py::build_artifact``) and the MCP
    ``tools/call`` text block (``routes/mcp.py::_tool_text``), its only two
    consumers. RT-005 (debug round 5): NOT tool-result folding, which this
    line used to claim — ``agent/loop.py::fold_result_content`` folds a
    ``BaseModel`` through ``model_dump(mode="json", ...)`` and never calls
    ``to_plain_text()``. That matters now that ``to_plain_text()`` appends
    caller-supplied ``metadata``: the suffix reaches those two client-facing
    surfaces, never the model's own tool-result content.

    Subclasses implement ``_body_text()`` — the card's own rendering — NOT
    ``to_plain_text()``. ``to_plain_text()`` is concrete here and is defined
    as ``self._body_text() + self._metadata_suffix()``.

    RT-003: that split is the enforcement mechanism for the ``metadata``
    contract. ``metadata`` lives on THIS class (RT-006); before this release
    every ``ContentModel`` — the 14 built-ins and every domain card alike —
    emitted it in ``wire()`` but never in ``to_plain_text()``, since nothing
    in this module called ``_metadata_suffix()`` from a subclass's text
    rendering. Making each subclass append the suffix by hand, at its own
    call site, would invite exactly the silent drift a base-class field
    cannot survive as a per-subclass obligation: one card, built-in or
    (especially) a domain type registered through ``register_content_type``,
    forgets the call, and its disclosure annotation reaches the A2UI
    ``wire()`` card but vanishes from the text fallback the
    no-A2UI-capability clients see. This release makes ``to_plain_text()``
    concrete instead, so the base class renders the suffix once, for every
    subclass that will ever exist, rather than asking each one to remember
    to.

    Delimiter safety (GH-130, GH-167): every untrusted ``str`` rendered into
    the text fallback goes through one of two helpers, chosen by where the
    value sits. A value JOINED with other text on its line (a ``" | "``
    column, a ``"label: value"`` pair, ``name <email>``, ``(type)``,
    ``k=v``) uses ``safe_cell_text``, which swaps the separator alphabet for
    look-alikes. A value that sits ALONE on its own line, with nothing joined
    after it (a title, a name, a summary), uses ``safe_line_text``, which
    only collapses line breaks and control characters and caps the length,
    so ``Toshiba (Tokyo)`` and ``Smith, John`` stay ASCII. Identifiers go on
    their own labelled line (``id: ...``) via ``safe_id_text``.
    """

    data_type: ClassVar[str]
    component: ClassVar[str]
    extended: ClassVar[bool] = False
    # Domain cards override with their own catalog id; surfaces never mix
    # catalogs (§5.4). The standard catalog is closed to new types.
    catalog_id: ClassVar[str] = CATALOG_ID
    # GH-63 escape hatch (RT-006): declared once here so every subclass —
    # including future domain cards — inherits it instead of redeclaring it.
    metadata: dict[str, Any] | None = None

    @field_validator("metadata")
    @classmethod
    def _metadata_finite(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        """RT-006: reject inf/-inf/nan anywhere in ``metadata``.

        ``metadata`` is the only free-form ``dict[str, Any]`` present on EVERY
        card, and it is the one field that reaches both halves of a dual-part
        artifact. Unguarded, ``metadata={"x": float("inf")}`` serialises to
        ``{"x": None}`` in ``wire()`` (pydantic's ``ser_json_inf_nan`` null
        default) while ``_metadata_suffix()`` renders ``x=inf`` into the text
        fallback — the DataPart and the mandatory TextPart then disagree about
        the same value. That is the identical split ``_assert_finite`` already
        guards on ``ChartSection.data`` / ``TableSection.data`` /
        ``BriefingKpiItem.value``; hoisting ``metadata`` to the base class made
        it universal, so the guard is hoisted with it.
        """
        _assert_finite(v)
        return v

    def __init_subclass__(cls, **kwargs: Any) -> None:
        """Frame every ``_body_text()`` implementation; adopt a legacy
        ``to_plain_text()`` override as one.

        Back-compat for domain cards written against the pre-split API, where
        ``to_plain_text()`` was the concrete (or, for a direct ``ContentModel``
        subclass, abstract) method to implement. Such an override would
        otherwise shadow the concrete base method and lose the metadata
        suffix — silently reintroducing the RT-003 bug for exactly the
        extension path this exists to fix. Instead the override becomes the
        class's ``_body_text()`` and ``to_plain_text()`` is rebound to the
        base implementation, so the card renders identically PLUS the suffix.

        The original function stays reachable as ``cls._body_text`` (it is
        rebound, not discarded), wrapped by ``_framed_body_text`` so that a
        ``super().to_plain_text()`` call from inside it (legal, common code
        against the previous API — e.g. a card subclassing a CONCRETE
        built-in that extends its rendering) resolves to the next ancestor's
        ``_body_text()`` directly instead of re-dispatching through
        ``type(self)._body_text()``, which would land right back on this same
        override and recurse. See ``to_plain_text()`` for the other half of
        this mechanism.

        DBG-5 (debug round 5): a NEW-style ``_body_text()`` override gets the
        SAME wrapper. Only the adopted-legacy half used to be framed, so the
        re-entrancy guard fired for exactly the shape this SDK asks authors to
        stop writing and never for the shape it asks them to write instead: a
        new ``_body_text()`` calling ``super().to_plain_text()`` recursed to
        ``RecursionError``, taking down every artifact emission for that card
        type, while ``docs/content-types.md`` and the TypeError below both
        pointed authors at that call. Framing every implementation makes the
        chain uniform — ``super()._body_text()`` (still the recommended call)
        and ``super().to_plain_text()`` now resolve to the same ancestor
        rendering, the latter simply without a second metadata suffix, since
        only the outermost call appends one.

        RT-005: a class declaring BOTH ``_body_text()`` and ``to_plain_text()``
        is not "new code" or "adopted legacy code" — it is a stale override
        left behind on a card mid-migration to the current API. Adoption must
        skip such a class (its own ``_body_text()`` is authoritative, not the
        adopted-override machinery), but silently returning here would leave
        the class's own ``to_plain_text()`` in place, shadowing the concrete
        base method and dropping the metadata suffix — exactly the drift
        this whole mechanism exists to make impossible. Raise instead, so the
        author deletes the dead override at class-definition time rather than
        discovering the drift at render time.
        """
        super().__init_subclass__(**kwargs)
        own = cls.__dict__
        override = own.get("to_plain_text")
        if not callable(override) or getattr(override, "__isabstractmethod__", False):
            override = None
        body = own.get("_body_text")
        if not callable(body) or getattr(body, "__isabstractmethod__", False):
            body = None
        if override is not None and body is not None:
            raise TypeError(
                f"{cls.__name__} declares both _body_text() and to_plain_text() — "
                "to_plain_text() is concrete on ContentModel and appends the "
                "metadata suffix; delete this stale to_plain_text() override "
                "and let _body_text() alone define the card's rendering. "
                "If _body_text() here is a PRIVATE helper predating this SDK "
                "version, that name is now the rendering hook reserved on "
                "ContentModel: rename the helper (e.g. _render_body()) and "
                "move the body of to_plain_text() into _body_text(). Note that "
                "a super().to_plain_text() call inside that body keeps working "
                "and resolves to the parent's rendering, without a second "
                "metadata suffix."
            )
        if override is None and body is None:
            return
        _NEXT_BODY_TEXT[cls] = _next_body_text_impl(cls)
        setattr(cls, "_body_text", _framed_body_text(override or body, cls))
        if override is not None:
            setattr(cls, "to_plain_text", ContentModel.to_plain_text)

    def _metadata_suffix(self) -> str:
        if not self.metadata:
            return ""
        parts = [
            f"\n{sanitize_text(str(k), max_len=_METADATA_SUFFIX_FIELD_MAX_LEN)}"
            f"={sanitize_text(str(v), max_len=_METADATA_SUFFIX_FIELD_MAX_LEN)}"
            for k, v in self.metadata.items()
        ]
        return "".join(parts)[:_METADATA_SUFFIX_MAX_LEN]

    def to_plain_text(self) -> str:
        """The mandatory text fallback. Concrete — override ``_body_text()``.

        RT-003 (round 2), generalised by DBG-5 (round 5): re-entrancy check
        first. EVERY ``_body_text()`` implementation — a new-style override
        and an adopted legacy ``to_plain_text()`` alike — runs inside
        ``_framed_body_text``, which pushes ``(declaring_cls, self)`` onto
        ``_BODY_TEXT_STACK`` for the duration of that call. If that
        implementation itself calls ``super().to_plain_text()`` (or
        ``self.to_plain_text()``), we land back here — but as a RE-ENTRANT
        call for the SAME instance, not a fresh top-level one. In that case
        resolve straight to the next ancestor's ``_body_text()``
        (``_NEXT_BODY_TEXT[cls]``), bypassing ``self._body_text()`` — which
        would dispatch on ``type(self)`` and land right back on the same
        implementation — and skip the metadata suffix, which the outermost
        call already appends exactly once.

        The frame carries the instance, not just the class, so a card whose
        rendering calls ``to_plain_text()`` on a DIFFERENT card is an ordinary
        top-level call and still gets that card's own suffix.
        """
        stack = _BODY_TEXT_STACK.get()
        if stack and stack[-1][1] is self:
            resuming_cls, _ = stack[-1]
            return _NEXT_BODY_TEXT[resuming_cls](self)
        return self._body_text() + self._metadata_suffix()

    @abc.abstractmethod
    def _body_text(self) -> str:
        """The card's own text rendering, WITHOUT the metadata suffix.

        DBG-7: the body is ``return ""``, not ``...``. This stub is abstract
        but it is NOT unreachable — it is the base case of the rendering chain,
        and a DIRECT ``ContentModel`` subclass reaches it by both documented
        routes:

        * ``super()._body_text()`` — the call this SDK recommends (see
          ``docs/content-types.md``) — resolves here through ordinary MRO
          lookup.
        * ``super().to_plain_text()`` — the documented-legal legacy call —
          resolves here too, via ``_NEXT_BODY_TEXT[cls]``, which
          ``_next_body_text_impl`` fills with this very function whenever
          ``cls``'s only ancestor declaring ``_body_text`` is ``ContentModel``.

        With a ``...`` body both routes returned ``None`` out of a method
        declared ``-> str``, so a direct subclass extending its ancestors'
        rendering raised ``TypeError`` on the concatenation, and one returning
        the call verbatim produced ``TextPart(text=None)`` and a
        ``ValidationError`` from ``build_artifact``. ``@abc.abstractmethod``
        still forces every concrete subclass to implement it; the return value
        only ever matters for the ``super()`` chain, and ``ContentModel``
        contributes no rendering of its own, so the empty string is the honest
        answer and keeps both documented calls working as written.
        """
        return ""


# ── shared fragments ──


class NameEmail(_Wire):
    name: str
    email: str


class DateRange(_Wire):
    """start/end keys — used by WaterfallChart and CalendarEvents.
    MultiCategoryChart uses first/last (FirstLastRange); frozen divergence."""

    start: str
    end: str


class FirstLastRange(_Wire):
    first: str
    last: str


# ── Core tier ──


class KpiTrend(_Wire):
    direction: Literal["up", "down", "flat"]
    delta: float | None = None
    delta_pct: float | None = None
    period: str | None = None


class MetricItem(_Wire):
    label: str
    value: float | int | str
    unit: str | None = None
    trend: Literal["up", "down", "flat"] | KpiTrend | None = None
    change_pct: float | None = None

    @field_serializer("trend")
    def _serialize_trend(
        self, trend: "Literal['up', 'down', 'flat'] | KpiTrend | None"
    ) -> "str | None":
        """Wire contract: trend is always a direction string or absent — never a
        KpiTrend object dict. KpiTrend instances are collapsed to their direction
        field here so that third-party renderers following Standard Profile v1
        receive the frozen contract shape."""
        if isinstance(trend, KpiTrend):
            return trend.direction
        return trend

    @field_validator("value", mode="before")
    @classmethod
    def _reject_non_scalar(cls, v: Any) -> Any:
        if isinstance(v, bool):
            raise ValueError(
                "MetricItem.value does not accept bool (would silently coerce to 0/1). "
                "Use from_any() to skip non-scalar values gracefully."
            )
        if not isinstance(v, (int, float, str)):
            raise ValueError(
                f"MetricItem.value must be int, float, or str; got {type(v).__name__}. "
                "Use from_any() to skip non-scalar values gracefully."
            )
        return v

    @classmethod
    def from_any(
        cls,
        label: str,
        value: Any,
        *,
        unit: str | None = None,
        trend: Any = None,
        change_pct: float | None = None,
    ) -> "MetricItem | None":
        """Return None instead of raising when value is non-scalar or bool.

        Replaces the repetitive ``isinstance(v, (int, float, str)) and not
        isinstance(v, bool)`` guard that domain ``wire()`` methods would otherwise
        need at every projection site.
        """
        try:
            return cls(label=label, value=value, unit=unit, trend=trend, change_pct=change_pct)
        except (ValueError, TypeError):
            return None


class KpiCard(ContentModel):
    data_type: ClassVar[str] = "kpi_card"
    component: ClassVar[str] = "KpiCard"  # never "KPICard"

    metrics: list[MetricItem] = Field(min_length=1)
    title: str | None = None

    def _body_text(self) -> str:
        # GH-167: the title stands alone and keeps ASCII (ruling: only the
        # line-break/control-char collapse applies). It cannot imitate a
        # metric row by layout: rows are indented, the title is at column 0.
        lines = [_sanitize_line(self.title, max_len=TITLE_TEXT_MAX_LEN)] if self.title else []
        for m in self.metrics:
            unit = f" {_sanitize_cell(m.unit)}" if m.unit else ""
            lines.append(f"  {safe_label_text(m.label, neutralise=':')}: {_sanitize_cell(str(m.value))}{unit}")
            if isinstance(m.trend, KpiTrend):
                arrow = _ARROWS[m.trend.direction]
                bits = [arrow]
                if m.trend.delta_pct is not None:
                    bits.append(f"{m.trend.delta_pct:+.1f}%")
                elif m.trend.delta is not None:
                    bits.append(f"{m.trend.delta:+g}")
                if m.trend.period:
                    bits.append(_sanitize_cell(m.trend.period))
                lines.append(f"    trend: {' '.join(bits)}")
            elif isinstance(m.trend, str):
                lines.append(f"    trend: {_ARROWS[m.trend]}")
        return "\n".join(lines)


class TimeSeriesDataPoint(_Wire):
    date: str
    value: float | None
    label: str | None = None
    # series is intentionally NOT on the wire: Standard Profile v1 data points
    # are {date, value, label?} only. Store it for Python-side grouping only.
    series: str | None = Field(default=None, exclude=True)

    @model_serializer(mode="wrap")
    def _wire_value(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """``value`` is required-but-nullable on the frozen time_series contract
        (a data gap is a real point, not an absent one) — unlike ``label``, which
        is genuinely optional. ``_Wire.wire()``'s blanket ``exclude_none=True``
        can't distinguish the two, so re-insert ``value: null`` here when the
        field was actually ``None`` (LRN-110)."""
        data = handler(self)
        if self.value is None:
            data["value"] = None
        return data


class TimeSeriesSummary(_Wire):
    min: float | None = None
    max: float | None = None
    first: float | None = None
    last: float | None = None
    change_percent: float | None = None
    average: float | None = None


class SeriesMeta(_Wire):
    name: str
    points: list[dict[str, Any]] = Field(default_factory=list)


class TimeSeriesChart(ContentModel):
    data_type: ClassVar[str] = "time_series"
    component: ClassVar[str] = "TimeSeriesChart"

    chart_type: Literal["line", "area", "bar"]
    title: str
    subtitle: str | None = None
    x_key: str = "date"
    y_key: str = "value"
    x_label: str | None = None
    y_label: str | None = None
    data: list[TimeSeriesDataPoint]
    total_count: int = 0  # set by model_validator below
    summary: TimeSeriesSummary | None = None
    # series is NOT on the wire: Profile v1 time_series has no top-level series
    # field. Store it for Python-side multi-series grouping only.
    series: list[SeriesMeta] | None = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _fill_total_count(cls, values: Any) -> Any:
        if isinstance(values, dict) and "total_count" not in values and "data" in values:
            data = values.get("data") or []
            values = dict(values)
            values["total_count"] = len(data) if isinstance(data, list) else 0
        return values

    def _body_text(self) -> str:
        lines = [_sanitize_line(self.title, max_len=TITLE_TEXT_MAX_LEN)]
        if self.data:
            first, last = self.data[0], self.data[-1]
            fv = first.value if first.value is not None else "N/A"
            lv = last.value if last.value is not None else "N/A"
            first_date = _sanitize_cell(first.date)
            last_date = _sanitize_cell(last.date)
            lines.append(
                f"  {fv} @ {first_date} → {lv} @ {last_date} "
                f"({len(self.data)} points)"
            )
        return "\n".join(lines)


class ColumnDef(_Wire):
    """Column descriptor. ``unit`` and ``highlight`` are SDK extensions: they
    are not in the Standard Profile v1 ``ComparisonTable`` column contract
    (``key``, ``label``, ``type``) but stay on the wire (GH-179)."""

    key: str
    label: str
    type: str | None = None
    unit: str | None = None
    highlight: str | None = None
    is_id: bool = False

    @model_serializer(mode="wrap")
    def _omit_is_id_when_false(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data = handler(self)
        if not self.is_id:
            data.pop("is_id", None)
        return data


class ComparisonTable(ContentModel):
    """``sort_by`` and ``sort_order`` are SDK extensions: not in the Standard
    Profile v1 contract, kept on the wire (GH-179). ``ColumnDef.unit`` and
    ``ColumnDef.highlight`` are SDK extensions too. ``ColumnDef.is_id=True``
    marks a column of machine ids: its cells render through ``safe_id_text``
    (``( )`` and spaces byte-exact, GH-212) instead of ``safe_cell_text``; it is
    omitted from the wire when false.

    ``rows`` values must be finite: a ``nan``/``inf`` cell is rejected at
    construction (GH-173 rule) so ``wire()`` and ``to_plain_text()`` agree."""

    data_type: ClassVar[str] = "comparison_table"
    component: ClassVar[str] = "ComparisonTable"

    title: str | None = None
    columns: list[ColumnDef]
    rows: list[dict[str, Any]]
    sort_by: str | None = None
    sort_order: Literal["asc", "desc"] | None = None

    @field_validator("rows")
    @classmethod
    def _rows_finite(cls, v: list[dict[str, Any]]) -> list[dict[str, Any]]:
        _assert_finite(v)
        return v

    def _body_text(self) -> str:
        header = " | ".join(safe_label_text(c.label, neutralise="|") for c in self.columns)
        # GH-167: the title stands alone and keeps ASCII (ruling: only the
        # line-break/control-char collapse applies). It cannot imitate a
        # table row by layout: header, rule and rows are indented, the title
        # is at column 0.
        lines = [_sanitize_line(self.title, max_len=TITLE_TEXT_MAX_LEN)] if self.title else []
        lines += [f"  {header}", "  " + "-" * len(header)]
        for row in self.rows:
            cells = [
                _safe_id(str(row.get(c.key, "")))
                if c.is_id
                else _sanitize_cell(str(row.get(c.key, "")))
                for c in self.columns
            ]
            lines.append("  " + " | ".join(cells))
        return "\n".join(lines)


class BarItem(_Wire):
    category: str
    value: float


class BarChart(ContentModel):
    data_type: ClassVar[str] = "bar_chart"
    component: ClassVar[str] = "BarChart"

    bars: list[BarItem]
    title: str | None = None
    x_key: str | None = None
    y_key: str | None = None

    def _body_text(self) -> str:
        lines = [_sanitize_line(self.title, max_len=TITLE_TEXT_MAX_LEN)] if self.title else []
        lines += [f"  {_sanitize_cell(b.category)}: {b.value:g}" for b in self.bars]
        return "\n".join(lines)


class EntityItem(_Wire):
    id: str
    name: str
    summary: str | None = None


class EntityList(ContentModel):
    """``title`` and ``showing`` are SDK extensions: not in the Standard
    Profile v1 ``EntityList`` contract, kept on the wire (GH-179)."""

    data_type: ClassVar[str] = "entity_list"
    component: ClassVar[str] = "EntityList"

    entity_type: str
    items: list[EntityItem]
    total_count: int | None = None
    has_more: bool | None = None
    title: str | None = None
    showing: int | None = None

    @model_validator(mode="after")
    def _fill_total_count(self) -> "EntityList":
        if self.total_count is None:
            self.total_count = len(self.items)
        return self

    def _body_text(self) -> str:
        title = (
            _sanitize_line(self.title, max_len=TITLE_TEXT_MAX_LEN) if self.title else _sanitize_cell(f"{self.entity_type} list")
        )
        lines = [title]
        lines.append(f"  showing {self.showing or len(self.items)} of {self.total_count}")
        for item in self.items:
            lines.append(f"  - {_sanitize_line(item.name)}")
            lines.append(f"    id: {_safe_id(item.id)}")
            if item.summary:
                lines.append(f"      {_sanitize_line(item.summary, max_len=None)}")
        return "\n".join(lines)


class BriefingKpiItem(_Wire):
    title: str
    value: float | int | str
    unit: str | None = None
    trend: Literal["up", "down", "flat"] | None = None
    delta: float | None = None

    @field_validator("value")
    @classmethod
    def _reject_non_finite(cls, v: Any) -> Any:
        _assert_finite(v)
        return v


class KpiRowSection(_Wire):
    type: Literal["kpi_row"] = "kpi_row"
    items: list[BriefingKpiItem]


class ChartSection(_Wire):
    type: Literal["chart"] = "chart"
    chart_type: Literal["time_series", "bar_chart"]
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def _reject_non_finite_data(cls, v: dict[str, Any]) -> dict[str, Any]:
        _assert_finite(v)
        return v


class TableSection(_Wire):
    type: Literal["table"] = "table"
    data: dict[str, Any] = Field(default_factory=dict)

    @field_validator("data")
    @classmethod
    def _reject_non_finite_data(cls, v: dict[str, Any]) -> dict[str, Any]:
        _assert_finite(v)
        return v


class TextSection(_Wire):
    type: Literal["text"] = "text"
    content: str


BriefingSection = Annotated[
    Union[KpiRowSection, ChartSection, TableSection, TextSection],
    Field(discriminator="type"),
]


class MarketBriefing(ContentModel):
    """Sole prose-exception type: the wire value is ``to_markdown()`` output
    (a markdown string), not this model's field dump. Renders without card
    chrome."""

    data_type: ClassVar[str] = "market_briefing"
    component: ClassVar[str] = "MarketBriefing"

    title: str
    as_of: str
    prose: str = ""
    sections: list[BriefingSection] = Field(default_factory=list)

    def to_markdown(self) -> str:
        # GH-167: the title and the as-of header each sit alone on their own line.
        lines = [_sanitize_line(self.title, max_len=TITLE_TEXT_MAX_LEN), f"as of: {_sanitize_line(self.as_of)}"]
        if self.prose:
            lines.append(_sanitize_block(self.prose))
        for section in self.sections:
            if isinstance(section, KpiRowSection):
                for item in section.items:
                    bits = [f"  KPI {_sanitize_cell(item.title)}: {_sanitize_cell(str(item.value))}"]
                    if item.unit:
                        bits.append(_sanitize_cell(item.unit))
                    if item.trend:
                        bits.append(_ARROWS[item.trend])
                    if item.delta is not None:
                        bits.append(f"{item.delta:+g}")
                    lines.append(" ".join(bits))
            elif isinstance(section, TextSection):
                lines.append(f"  {_sanitize_block(section.content)}")
            elif isinstance(section, ChartSection):
                chart_title = _sanitize_cell(str(section.data.get("title", "")))
                lines.append(f"  CHART ({section.chart_type}): {chart_title}")
            elif isinstance(section, TableSection):
                table_title = _sanitize_cell(str(section.data.get("title", "")))
                lines.append(f"  TABLE: {table_title}")
        return "\n".join(lines)

    def wire(self) -> str:  # type: ignore[override]
        """The prose exception: the wire value is the markdown string, not a
        field dump (GH-179). ``mcp.py`` and the translator special-case it too."""
        return self.to_markdown()

    def _body_text(self) -> str:
        return self.to_markdown()


# ── Extended tier ──


class WaterfallSegment(_Wire):
    label: str
    value: float
    type: Literal["initial", "final", "inflow", "outflow", "gain", "loss", "subtotal"]
    cumulative: float
    tooltip: str | None = None


class WaterfallChart(ContentModel):
    data_type: ClassVar[str] = "waterfall_chart"
    component: ClassVar[str] = "WaterfallChart"
    extended: ClassVar[bool] = True

    title: str
    segments: list[WaterfallSegment]
    subtitle: str | None = None
    currency: str | None = None
    entity_name: str | None = None
    as_of_date: str | None = None
    date_range: DateRange | None = None  # start/end — frozen; not first/last

    def _body_text(self) -> str:
        lines = [_sanitize_line(self.title, max_len=TITLE_TEXT_MAX_LEN)]
        lines += [
            f"  {_sanitize_cell(s.label)}: {s.value:+g} → {s.cumulative:g} ({s.type})"
            for s in self.segments
        ]
        return "\n".join(lines)


class CategoryValue(_Wire):
    value: float
    count: int | None = None
    metadata: dict[str, Any] | None = None

    @field_validator("metadata")
    @classmethod
    def _metadata_finite(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        _assert_finite(v)
        return v


class MultiCategoryPeriod(_Wire):
    period: str
    categories: dict[str, CategoryValue]
    period_total: float | None = None


class MultiCategorySummary(_Wire):
    by_category: dict[str, CategoryValue]
    grand_total: float | None = None
    period_count: int


class MultiCategoryChartConfig(_Wire):
    show_total_line: bool | None = None
    stack_bars: bool | None = None
    show_cumulative: bool | None = None
    category_colors: dict[str, str] | None = None


class MultiCategoryChart(ContentModel):
    data_type: ClassVar[str] = "multi_category_chart"
    component: ClassVar[str] = "MultiCategoryChart"
    extended: ClassVar[bool] = True

    title: str
    periods: list[MultiCategoryPeriod]
    summary: MultiCategorySummary
    date_range: FirstLastRange  # first/last — frozen; not start/end
    subtitle: str | None = None
    unit_label: str | None = None
    currency: str | None = None
    entity_name: str | None = None
    item_count: int | None = None
    chart_config: MultiCategoryChartConfig | None = None

    def _body_text(self) -> str:
        lines = [_sanitize_line(self.title, max_len=TITLE_TEXT_MAX_LEN)]
        for p in self.periods:
            cats = ", ".join(
                f"{_sanitize_cell(k)}={v.value:g}" for k, v in p.categories.items()
            )
            lines.append(f"  {_sanitize_cell(p.period)}: {cats}")
        return "\n".join(lines)


class Money(_Wire):
    amount: float | None = None
    currency: str | None = None  # renderer defaults to USD when absent


class FundPerformance(ContentModel):
    """Sole camelCase-wire type. Attributes are snake_case with camelCase
    aliases; ``wire()`` (by_alias + exclude_none) is the only conformant
    serialization — snake_case keys must never reach the wire."""

    data_type: ClassVar[str] = "fund_performance"
    component: ClassVar[str] = "FundPerformance"
    extended: ClassVar[bool] = True

    pb_id: str | None = Field(default=None, alias="pbId")
    as_of_date: str | None = Field(default=None, alias="asOfDate")
    irr: float | None = None
    tvpi: float | None = None
    dpi: float | None = None
    rvpi: float | None = None
    net_irr: float | None = Field(default=None, alias="netIrr")
    gross_irr: float | None = Field(default=None, alias="grossIrr")
    moic: float | None = None
    quartile: int | None = None
    nav: Money | None = None
    as_of_quarter: int | None = Field(default=None, alias="asOfQuarter")
    as_of_year: int | None = Field(default=None, alias="asOfYear")
    called_down_pct: float | None = Field(default=None, alias="calledDownPct")
    dry_powder: Money | None = Field(default=None, alias="dryPowder")
    dry_powder_pct: float | None = Field(default=None, alias="dryPowderPct")
    distributed: Money | None = None
    remaining_value: Money | None = Field(default=None, alias="remainingValue")
    distributed_plus_remaining: Money | None = Field(
        default=None, alias="distributedPlusRemaining"
    )

    def _body_text(self) -> str:
        # RT-004 (GH-149 follow-up): keep pace with every field the wire
        # (`wire()`) can carry — a text-only client (DESIGN.md §5.1/§5.4
        # dual-part TextPart) sees ONLY this string, so a field present on
        # the card but absent here silently vanishes for that client even
        # though the A2UI-capable client renders it.
        bits: list[str] = []
        if self.irr is not None:
            bits.append(f"IRR={self.irr:.1%}")
        if self.net_irr is not None:
            bits.append(f"Net IRR={self.net_irr:.1%}")
        if self.gross_irr is not None:
            bits.append(f"Gross IRR={self.gross_irr:.1%}")
        if self.tvpi is not None:
            bits.append(f"TVPI={self.tvpi:.2f}x")
        if self.dpi is not None:
            bits.append(f"DPI={self.dpi:.2f}x")
        if self.rvpi is not None:
            bits.append(f"RVPI={self.rvpi:.2f}x")
        if self.moic is not None:
            bits.append(f"MOIC={self.moic:.2f}x")
        if self.quartile is not None:
            bits.append(f"Quartile=Q{self.quartile}")
        if self.nav and self.nav.amount is not None:
            bits.append(f"NAV={self.nav.amount:,.0f} {self.nav.currency or 'USD'}")
        if self.dry_powder and self.dry_powder.amount is not None:
            bits.append(
                f"Dry powder={self.dry_powder.amount:,.0f} "
                f"{self.dry_powder.currency or 'USD'}"
            )
        if self.dry_powder_pct is not None:
            bits.append(f"Dry powder pct={self.dry_powder_pct:.1%}")
        if self.distributed and self.distributed.amount is not None:
            bits.append(
                f"Distributed={self.distributed.amount:,.0f} "
                f"{self.distributed.currency or 'USD'}"
            )
        if self.remaining_value and self.remaining_value.amount is not None:
            bits.append(
                f"Remaining value={self.remaining_value.amount:,.0f} "
                f"{self.remaining_value.currency or 'USD'}"
            )
        if (
            self.distributed_plus_remaining
            and self.distributed_plus_remaining.amount is not None
        ):
            bits.append(
                f"Distributed+remaining={self.distributed_plus_remaining.amount:,.0f} "
                f"{self.distributed_plus_remaining.currency or 'USD'}"
            )
        if self.called_down_pct is not None:
            bits.append(f"Called down={self.called_down_pct:.1%}")
        period_bits = []
        if self.as_of_quarter is not None:
            period_bits.append(f"Q{self.as_of_quarter}")
        if self.as_of_year is not None:
            period_bits.append(str(self.as_of_year))
        if period_bits:
            bits.append(" ".join(period_bits))
        if self.as_of_date:
            bits.append(f"as of {_sanitize_cell(self.as_of_date)}")
        # RT-004: provenance suffix, mirroring the admin console card's
        # subtitle (console/static/a2ui.js::renderFundPerformance, "source
        # <pbId>") rather than a bare identifier.
        # RT-006 (debug round 5) / RT-001 (redteam, 2026-09-03): pb_id is a
        # tool-supplied upstream identifier reaching the identical two
        # client-facing surfaces (the mandatory A2A TextPart and the MCP
        # tools/call text) every other bit in this join reaches, so it needs
        # BOTH guards every other field in this module gets: the 256-char
        # length cap this field alone carries (matching the metadata-suffix
        # contract, sanitize_text's max_len), AND the structural-delimiter
        # neutralisation (_sanitize_cell/GH-130) every value joined on " | "
        # needs — sanitize_text alone does not strip "|", so an unguarded
        # pb_id could fabricate a fake bit in this join exactly like the
        # GH-130 table-row case. Cap first (sanitize_text), THEN strip
        # separators (_sanitize_cell) — reversing the order would let a
        # fullwidth substitution's byte growth outrun the cap.
        if self.pb_id:
            safe_pb_id = _safe_joined_id(self.pb_id)
            bits.append(f"source {safe_pb_id}")
        return (" | ".join(bits) or "fund performance (no data)")


class EmailMessage(_Wire):
    id: str
    conversation_id: str | None = None
    subject: str
    preview: str
    from_: NameEmail = Field(alias="from")
    to_recipients: list[NameEmail]
    received_at: str  # ISO 8601 UTC, trailing Z
    is_read: bool
    has_attachments: bool = False
    importance: Literal["low", "normal", "high"] = "normal"
    flag_status: Literal["notFlagged", "flagged", "complete"] | None = None
    web_link: str


class EmailList(ContentModel):
    data_type: ClassVar[str] = "email_list"
    component: ClassVar[str] = "EmailList"
    extended: ClassVar[bool] = True

    messages: list[EmailMessage]
    total_count: int
    has_more: bool
    folder: str | None = None
    query: str | None = None

    def _body_text(self) -> str:
        lines = [f"{self.total_count} message(s)"]
        for m in self.messages:
            unread = "[unread] " if not m.is_read else ""
            received_at = _sanitize_cell(m.received_at)
            from_email = _sanitize_cell(m.from_.email)
            subject = _sanitize_cell(m.subject)
            ids = f"id: {_safe_joined_id(m.id)}"
            if m.conversation_id:
                ids += f", conversation: {_safe_joined_id(m.conversation_id)}"
            lines.append(f"  {unread}{received_at} | {from_email} | {subject} ({ids})")
            if m.preview:
                lines.append(f"    {_sanitize_cell(m.preview)}")
        return "\n".join(lines)


class EventLocation(_Wire):
    display_name: str = ""
    is_online: bool = False
    join_url: str | None = None

    @field_validator("display_name", "is_online", mode="before")
    @classmethod
    def _none_means_default(cls, v: Any, info: Any) -> Any:
        if v is None:
            return cls.model_fields[info.field_name].default
        return v


class CalendarEvent(_Wire):
    """The event-level ``is_online`` is an SDK extension: the Standard Profile
    carries it on ``location`` only. It stays on the wire (GH-179)."""

    id: str
    subject: str
    start: str  # UTC ISO 8601, trailing Z; renderer owns locale
    end: str
    is_all_day: bool = False
    is_cancelled: bool = False
    is_recurring: bool = False
    organizer: NameEmail
    location: EventLocation | None = None
    attendees_count: int = 0
    response_status: Literal["accepted", "tentative", "declined", "none"] | None = None
    importance: Literal["low", "normal", "high"] = "normal"
    show_as: Literal[
        "free", "tentative", "busy", "oof", "workingElsewhere", "unknown"
    ] = "unknown"
    web_link: str
    is_online: bool | None = None


class CalendarEvents(ContentModel):
    data_type: ClassVar[str] = "calendar_events"
    component: ClassVar[str] = "CalendarEvents"
    extended: ClassVar[bool] = True

    events: list[CalendarEvent]
    date_range: DateRange  # start/end — frozen
    total_count: int
    has_more: bool

    def _body_text(self) -> str:
        start = _sanitize_cell(self.date_range.start)
        end = _sanitize_cell(self.date_range.end)
        lines = [f"{self.total_count} event(s) {start} – {end}"]
        for e in self.events:
            loc = ""
            if e.location and e.location.display_name:
                loc = f" @ {_sanitize_cell(e.location.display_name)}"
            online = " [online]" if (e.is_online or (e.location and e.location.is_online)) else ""
            e_start = _sanitize_cell(e.start)
            e_end = _sanitize_cell(e.end)
            # GH-167: the subject stands alone; time/place and id get their own lines.
            lines.append(f"  - {_sanitize_line(e.subject)}")
            lines.append(f"    {e_start} – {e_end}{loc}{online}")
            lines.append(f"    id: {_safe_id(e.id)}")
        return "\n".join(lines)


_AVAILABILITY = Literal[
    "available", "busy", "doNotDisturb", "beRightBack", "away", "offline",
    "presenceunknown", "outofoffice", "inacall", "inapresentationoracall",
    "presenting", "focusing", "urgentinterruptionsonly",
]


class UserPresence(_Wire):
    availability: _AVAILABILITY
    activity: str
    status_message: str | None = None


class OutOfOfficeSettings(_Wire):
    is_enabled: bool
    start_date: str | None = None
    end_date: str | None = None
    internal_message: str | None = None
    external_message: str | None = None


class ManagerRef(_Wire):
    id: str
    display_name: str
    email: str
    job_title: str | None = None


class UserProfile(ContentModel):
    data_type: ClassVar[str] = "user_profile"
    component: ClassVar[str] = "UserProfile"
    extended: ClassVar[bool] = True

    id: str
    display_name: str
    email: str
    given_name: str | None = None
    surname: str | None = None
    job_title: str | None = None
    department: str | None = None
    office_location: str | None = None
    mobile_phone: str | None = None
    business_phones: list[str] = Field(default_factory=list)
    manager: ManagerRef | None = None
    presence: UserPresence | None = None
    photo_url: str | None = None
    out_of_office: OutOfOfficeSettings | None = None

    def _body_text(self) -> str:
        # GH-167: the name stands alone; email and id get their own labelled lines.
        lines = [
            _sanitize_line(self.display_name),
            f"  email: {_sanitize_cell(self.email)}",
            f"  id: {_safe_id(self.id)}",
        ]
        if self.job_title:
            dept = f", {_sanitize_cell(self.department)}" if self.department else ""
            lines.append(f"  {_sanitize_cell(self.job_title)}{dept}")
        if self.presence:
            lines.append(f"  presence: {self.presence.availability}")
        if self.manager:
            lines.append(f"  manager: {_sanitize_line(self.manager.display_name)}")
            lines.append(f"    email: {_sanitize_cell(self.manager.email)}")
            lines.append(f"    id: {_safe_id(self.manager.id)}")
        return "\n".join(lines)


class UserSummary(_Wire):
    id: str
    display_name: str
    email: str
    job_title: str | None = None
    department: str | None = None
    presence: UserPresence | None = None


class UserList(ContentModel):
    data_type: ClassVar[str] = "user_list"
    component: ClassVar[str] = "UserList"
    extended: ClassVar[bool] = True

    users: list[UserSummary]
    total_count: int
    has_more: bool
    query: str | None = None

    def _body_text(self) -> str:
        lines = [f"{self.total_count} user(s)"]
        for u in self.users:
            # GH-167: the name stands alone; email, job title and id get their own lines.
            lines.append(f"  - {_sanitize_line(u.display_name)}")
            lines.append(f"    email: {_sanitize_cell(u.email)}")
            if u.job_title:
                lines.append(f"    title: {_sanitize_cell(u.job_title)}")
            lines.append(f"    id: {_safe_id(u.id)}")
        return "\n".join(lines)


# Serialization-context key for the model's own transcript copy of a tool
# result. Wire-only reshaping (DocumentItem's contract keys) is skipped there.
TRANSCRIPT_DUMP_CONTEXT = "agent_sdk.transcript"


class DocumentItem(_Wire):
    id: str
    name: str
    type: str | None = None
    modified: str | None = None
    link: str | None = None
    size: float | None = None
    web_url: str | None = None
    last_modified: str | None = None
    modified_by: str | None = None

    @model_serializer(mode="wrap")
    def _wire_contract_keys(
        self, handler: SerializerFunctionWrapHandler, info: SerializationInfo
    ) -> dict[str, Any]:
        """GH-177: the frozen DocumentItem contract is id/name/type/modified/
        link/size. ``web_url`` and ``last_modified`` stay model-side aliases:
        they fill an empty ``link``/``modified`` and are never emitted.

        Exception: a dump with ``context={TRANSCRIPT_DUMP_CONTEXT: True}``
        (``agent/loop.py::fold_result_content``, the model's own copy of a
        tool result) keeps both keys, so the agent's model still sees a
        ``last_modified`` that differs from ``modified`` (w050 RT-001 r8)."""
        data = handler(self)
        if isinstance(info.context, dict) and info.context.get(TRANSCRIPT_DUMP_CONTEXT):
            return data
        if self.web_url and not data.get("link"):
            data["link"] = self.web_url
        if self.last_modified and not data.get("modified"):
            data["modified"] = self.last_modified
        data.pop("web_url", None)
        data.pop("last_modified", None)
        return data


class DocumentList(ContentModel):
    data_type: ClassVar[str] = "document_list"
    component: ClassVar[str] = "DocumentList"
    extended: ClassVar[bool] = True

    documents: list[DocumentItem]
    total_count: int | None = None
    has_more: bool | None = None

    @model_validator(mode="after")
    def _fill_total_count(self) -> "DocumentList":
        if self.total_count is None:
            self.total_count = len(self.documents)
        return self

    def _body_text(self) -> str:
        lines = [f"{self.total_count} document(s)"]
        for d in self.documents:
            # GH-167: the name stands alone; type, date and id get their own lines.
            lines.append(f"  - {_sanitize_line(d.name)}")
            if d.type:
                lines.append(f"    type: {_sanitize_cell(d.type)}")
            # GH-177: ``modified`` matches the wire (``last_modified`` only
            # fills it when empty). When both are set and differ, the wire
            # drops ``last_modified``, so this text is the one place its
            # value still shows (e.g. an upload date next to a period end).
            when = d.modified or d.last_modified
            if when:
                lines.append(f"    modified: {_sanitize_cell(when)}")
            if d.modified and d.last_modified and d.last_modified != d.modified:
                lines.append(f"    last modified: {_sanitize_cell(d.last_modified)}")
            if d.modified_by:
                lines.append(f"    modified by: {_sanitize_cell(d.modified_by)}")
            lines.append(f"    id: {_safe_id(d.id)}")
        return "\n".join(lines)


# ── registry ──

_REGISTRY: dict[str, type[ContentModel]] = {}
_PROFILE_SEALED = False
_COMPONENT_NAME_RE = re.compile(r"[A-Z][A-Za-z0-9]*")


def _case_clash_hint(cls: type[ContentModel], component: object) -> str:
    if not isinstance(component, str):
        return ""
    folded = component.casefold()
    for kind, names in (
        ("RESERVED name", RESERVED_COMPONENTS),
        ("Basic Catalog primitive", BASIC_CATALOG_COMPONENTS),
        ("registered name", [o.component for o in _REGISTRY.values() if o is not cls]),
    ):
        for name in names:
            if isinstance(name, str) and name.casefold() == folded:
                return f"; it also collides with {kind} {name!r} ignoring case"
    return ""


def register_content_type(cls: type[ContentModel]) -> type[ContentModel]:
    """Register a card type (SDK profile types at import; agents for domain
    cards). Validates the frozen-name and uniqueness rules."""
    if not (isinstance(cls, type) and issubclass(cls, ContentModel)):
        raise TypeError("content type must subclass ContentModel")
    data_type = getattr(cls, "data_type", None)
    component = getattr(cls, "component", None)
    if not data_type or not component:
        raise TypeError(f"{cls.__name__} must declare data_type and component")
    if not isinstance(component, str) or not _COMPONENT_NAME_RE.fullmatch(component):
        raise ValueError(
            f"component name {component!r} is invalid — A2UI wire names must be "
            f"PascalCase (^[A-Z][A-Za-z0-9]*$); rename the card"
            f"{_case_clash_hint(cls, component)}"
        )
    if component in RESERVED_COMPONENTS:
        raise ValueError(
            f"component name {component!r} is RESERVED in Standard Profile v1 "
            f"(no field contract exists; do not emit a presumed shape)"
        )
    if cls.catalog_id == CATALOG_ID and _PROFILE_SEALED and cls not in PROFILE_TYPES:
        raise ValueError(
            "the standard catalog is FROZEN — domain cards must declare their "
            "own catalog_id (see the extension docs)"
        )
    # Wire component names must be GLOBALLY unique: A2UI resolves a component by
    # its bare PascalCase name with no catalog qualifier, so two types sharing a
    # name would silently shadow on the wire. Same-class re-registration is a
    # no-op (identity check), matching the data_type rule below.
    component_owner = next(
        (owner for owner in _REGISTRY.values() if owner.component == component),
        None,
    )
    if component_owner is not None and component_owner is not cls:
        raise ValueError(
            f"component name {component!r} already registered by "
            f"{component_owner.__name__} — wire component names must be globally "
            f"unique (A2UI resolves by bare componentType, not by catalogId)"
        )
    folded = component.casefold()
    for reserved in RESERVED_COMPONENTS:
        if reserved.casefold() == folded:
            raise ValueError(
                f"component name {component!r} differs only in case from the "
                f"RESERVED name {reserved!r}; pick a distinct name"
            )
    for primitive in BASIC_CATALOG_COMPONENTS:
        if primitive.casefold() == folded:
            raise ValueError(
                f"component name {component!r} equals the Basic Catalog "
                f"primitive {primitive!r} ignoring case; a client would "
                f"shadow or drop one of them — pick a distinct name"
            )
    for owner in _REGISTRY.values():
        if owner is not cls and owner.component.casefold() == folded:
            raise ValueError(
                f"component name {component!r} differs only in case from the "
                f"existing name {owner.component!r} ({owner.__name__}); "
                f"a case-sensitive client would drop one of them"
            )
    existing = _REGISTRY.get(data_type)
    if existing is not None and existing is not cls:
        raise ValueError(f"data_type {data_type!r} already registered by {existing.__name__}")
    _REGISTRY[data_type] = cls
    return cls


def content_type_for(data_type: str) -> type[ContentModel] | None:
    return _REGISTRY.get(data_type)


def registered_content_types() -> dict[str, type[ContentModel]]:
    return dict(_REGISTRY)


PROFILE_TYPES: tuple[type[ContentModel], ...] = (
    KpiCard,
    TimeSeriesChart,
    ComparisonTable,
    BarChart,
    EntityList,
    MarketBriefing,
    WaterfallChart,
    MultiCategoryChart,
    FundPerformance,
    EmailList,
    CalendarEvents,
    UserProfile,
    UserList,
    DocumentList,
)

for _cls in PROFILE_TYPES:
    register_content_type(_cls)
_PROFILE_SEALED = True
