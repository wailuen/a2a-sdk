"""ToolSet (declaration) and ToolRegistry (resolved at build_app).

ToolSet is a stateless declaration list — explicit collection, no import
side effects (DESIGN.md §4.1). Adapter dependencies are declared solely by
keyword-only parameter annotations (exact-class match); there is no
``source=`` kwarg. All wiring errors raise at ``build_app()``, never at
call time.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from dataclasses import dataclass, field
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Union,
    cast,
)

from pydantic import AliasChoices, AliasPath, BaseModel, ValidationError
from pydantic_core import InitErrorDetails, PydanticCustomError

from ..models.errors import AgentError, ErrorCategory
from ..sources import SourceAdapter
from .deferred import DeferredResult
from .reuse import (
    _accepts_field_name_alias,
    RAW_PREFIX,
    REF_PREFIX,
    Reusable,
    reuse_field_types_for_model,
    reuse_fields_for_model,
    reuse_raw_override_for_model,
    reuse_strict_for_model,
)

if TYPE_CHECKING:
    from .loop import LoopPolicies

logger = logging.getLogger(__name__)


# ── GH-88 sentinel types ──

# Unique object used as "no item buffered yet" placeholder in invoke_gen.
_SENTINEL = object()


# GH-120: total DeferredResult handles invoke_any() will await before giving
# up — the original handle plus at most one nested resolution. A handle
# resolving to a THIRD DeferredResult raises rather than looping forever /
# leaking the object.
_MAX_DEFERRED_RESOLUTIONS = 2


# ── GH-148 / RT-B-004: reuse-token schema widening ──

# JSON Schema keywords that ANNOTATE a property rather than constrain its
# value. When a non-string ReuseKind field's schema is widened below, these
# stay at the top level of the rewritten property (so `title`/`description`
# keep describing the field as a whole) while every constraining keyword
# moves into the original branch of the `anyOf`.
_SCHEMA_ANNOTATION_KEYS = frozenset(
    {"title", "description", "default", "examples", "deprecated", "readOnly", "writeOnly", "$comment"}
)

# RT-004: JSON Schema keywords that narrow a STRING's value space rather than
# merely annotate it. A `{"type": "string", ...}` (or bare `const`, which
# needs no sibling `type`) schema carrying any of these must be treated the
# same as `enum` below — excluding the reuse token — since the model cannot
# emit `$ref:<kind>`/`$raw:<value>` on a field whose schema also demands it
# match a `pattern`, an exact `format`, a fixed `const`, or a length bound
# the token is not guaranteed to satisfy.
_STRING_VALUE_CONSTRAINT_KEYS = frozenset(
    {"pattern", "const", "format", "minLength", "maxLength"}
)

# The widened string branch. Deliberately the bare sentinel prefix rather
# than `^\$ref:`: a field whose operator opted into `allow_raw_override`
# must be able to carry the `$raw:<value>` token too, and RT-002 forbids
# naming that token anywhere the model can read it — including in a schema
# pattern. Any other `$`-prefixed string is treated as an ordinary raw value
# by resolve_reuse_fields and runs through the normal mismatch check, exactly
# as it would on a str-typed field (where every string is representable
# already).
_REUSE_TOKEN_PATTERN = r"^\$"


def _resolve_schema_ref(ref: str, defs: dict[str, Any]) -> dict[str, Any] | None:
    """Resolve a local ``#/$defs/<Name>`` ref against ``defs`` (RT-006).

    Returns ``None`` for a ref shape pydantic's own ``model_json_schema()``
    never produces (so it cannot be misresolved into the wrong entry) or a
    name absent from ``defs``, so the caller can fall back to "unprovable"
    rather than guess.
    """
    prefix = "#/$defs/"
    if not ref.startswith(prefix):
        return None
    resolved = defs.get(ref[len(prefix) :])
    return resolved if isinstance(resolved, dict) else None


def _schema_permits_string(schema: dict[str, Any], defs: dict[str, Any] | None = None) -> bool:
    """True when ``schema`` already allows the literal ``$ref:<kind>``/
    ``$raw:<value>`` reuse token — an arbitrary JSON string.

    RT-B-004: the reuse token is a STRING sentinel, so on a field whose
    advertised schema excludes strings (``Annotated[int, ReuseKind(...)]``
    renders as ``{"type": "integer"}``) a provider that constrains tool
    arguments to the declared schema — Bedrock Converse and every other
    schema-enforcing provider — will not let the model emit the token at
    all, making the whole mechanism unreachable there.

    RT-006: a ``$ref`` into the schema's own ``$defs`` — an Enum-typed
    ``ReuseKind`` field renders as ``{"$ref": "#/$defs/MyEnum"}`` — and an
    ``allOf`` composition are now RESOLVED (against ``defs``, the caller's
    top-level ``schema.get("$defs")``) before deciding, rather than assumed
    to permit a string. An earlier revision returned ``True`` ("no widening
    needed") for both shapes unconditionally, which silently no-opped the
    widening on exactly the ReuseKind field shape most likely to need it: a
    ``ReuseKind`` field typed as an ``Enum`` (accepted by
    ``reuse_fields_for_model`` — it is neither a container nor a
    ``BaseModel``) would advertise only its enum members, with no way for a
    schema-enforcing provider to emit the token, and the annotation shipped
    as a silent no-op.

    Also treats ANY schema carrying an ``enum`` key — resolved or inline
    (``Literal[...]`` renders inline as ``{"enum": [...], "type": "string"}``
    with no ``$ref``) — as excluding the token, even when every member is
    itself a string: an enum restricts values to its fixed member list, and
    the reuse token is never one of them, so the naive ``type == "string"``
    check alone is not enough to prove the token is representable.

    RT-004: the same reasoning extends to any of ``_STRING_VALUE_CONSTRAINT_
    KEYS`` (``pattern``, ``const``, ``format``, ``minLength``, ``maxLength``)
    on an otherwise ``type: "string"`` schema — a single-value ``Literal``
    (``const``, no ``type`` key required), a regex-validated id
    (``pattern``), a UUID field (``format``), or a length-bounded field
    (``minLength``/``maxLength``) all narrow the value space in a way that
    does not provably admit the sentinel. An earlier revision returned
    ``True`` for all of these — the exact shapes a canonical ``entity_id``
    field is likely to take — leaving the hint a silent no-op on a
    schema-enforcing provider exactly like the unresolved-``enum``/``$ref``
    gap RT-006 closed for non-string scalars.

    Returns ``True`` (i.e. "no widening needed") only for what this function
    can positively resolve to a plain, unconstrained string-permitting
    shape; an unresolvable ``$ref`` (a name absent from ``defs``, or
    ``defs`` itself not supplied) is left as "unprovable" — ``True`` — since
    this function cannot tell excludes-string from could-not-check, and
    widening based on a guess risks corrupting a schema shape it doesn't
    understand.
    """
    ref = schema.get("$ref")
    if isinstance(ref, str):
        resolved = _resolve_schema_ref(ref, defs) if defs else None
        if resolved is not None:
            return _schema_permits_string(resolved, defs)
        return True
    all_of = schema.get("allOf")
    if isinstance(all_of, list) and all_of:
        # A value must satisfy every branch of an allOf simultaneously, so
        # the composition permits the token only when every branch does.
        return all(isinstance(b, dict) and _schema_permits_string(b, defs) for b in all_of)
    if "enum" in schema:
        return False
    if _STRING_VALUE_CONSTRAINT_KEYS.intersection(schema):
        return False
    declared = schema.get("type")
    if declared == "string":
        return True
    if isinstance(declared, list):
        return "string" in declared
    branches = schema.get("anyOf") or schema.get("oneOf")
    if isinstance(branches, list) and branches:
        return any(isinstance(b, dict) and _schema_permits_string(b, defs) for b in branches)
    # A concrete non-string `type` with no union branch is the one shape that
    # provably excludes a string; everything else stays untouched.
    return not isinstance(declared, str)


def _widen_for_reuse_token(prop: dict[str, Any]) -> dict[str, Any]:
    """Rewrite a non-string property so the ``$ref:<kind>`` token is
    representable: ``{"anyOf": [<original constraints>, {"type": "string",
    ...}]}``, with annotation keywords kept at the top level (RT-B-004).

    Returns a new dict — the caller replaces the entry in ``properties``
    rather than mutating the schema pydantic handed back.
    """
    constraints = {k: v for k, v in prop.items() if k not in _SCHEMA_ANNOTATION_KEYS}
    widened = {k: v for k, v in prop.items() if k in _SCHEMA_ANNOTATION_KEYS}
    token_branch = {"type": "string", "pattern": _REUSE_TOKEN_PATTERN}
    existing = constraints.get("anyOf")
    if list(constraints) == ["anyOf"] and isinstance(existing, list):
        # Already a union (``int | None`` renders as an ``anyOf`` pair) —
        # append rather than nest, so the emitted schema stays a single flat
        # union a strict provider will accept.
        widened["anyOf"] = [*existing, token_branch]
    else:
        widened["anyOf"] = [constraints, token_branch]
    return widened


async def resolve_deferred_result(
    result: Any,
    *,
    tool_name: str,
    handle_timeout: Callable[[], float],
) -> Any:
    """Resolve ``result`` down to a terminal value, following a chain of
    nested ``DeferredResult`` up to ``_MAX_DEFERRED_RESOLUTIONS`` deep
    (GH-120/GH-121, RT-001).

    ``result`` need not itself be a ``DeferredResult`` — a plain value passes
    through unchanged. ``handle_timeout`` is called fresh before each await;
    what it RETURNS is entirely the caller's choice (RT-002). A caller
    enforcing one overall deadline (RT-003) — ``invoke_any`` called with an
    explicit ``timeout``, and ``runner._run_deferred_background`` — closes
    over a single ``deadline`` computed once, so the returned budget shrinks
    as time elapses across nested awaits. ``invoke_any`` called with
    ``timeout=None`` (the commitments executor's call shape, which has no
    per-call deadline of its own) instead closes over ``resolve_tool_timeout``
    and returns a FULL fresh budget before every nested await. This function
    does not normalize that choice — it only bounds each individual await by
    whatever ``handle_timeout()`` returns.

    Every surface that awaits a returned ``DeferredResult`` — ``invoke_any``
    (MCP ``tools/call``, admin try-tool, commitments executor) and the A2A/
    AG-UI background awaiter (``runner._run_deferred_background``) — routes
    through this so a ``long_running`` tool's nested-``DeferredResult``
    contract cannot drift by transport in the two respects this function
    itself controls (RT-001): a nesting DEPTH that succeeds on one surface
    must succeed identically on every other, and the same holds for the
    point at which nesting is declared too deep and rejected. The TIMEOUT
    BUDGET spent resolving a chain is deliberately NOT part of that parity
    guarantee (RT-002) — see above: a slow nested chain can succeed on the
    deadline-free commitments surface while timing out on MCP/A2A for the
    identical tool contract, because only the timeout-bearing surfaces share
    one shrinking deadline.

    Registered as C-012 in workspace/components/README.md — imported
    directly by both ``ToolEntry.invoke_any`` (C-010, this module) and
    ``runner._run_deferred_background``. Any future tool-dispatch surface
    that awaits a ``DeferredResult`` must call this rather than
    re-deriving ``_MAX_DEFERRED_RESOLUTIONS`` (RT-001).

    RT-010: a ``Reusable`` wrapping a still-pending ``DeferredResult`` — the
    nesting ORDER left unhandled by GH-148's original support for the
    opposite order (a ``DeferredResult`` resolving TO a ``Reusable``, which
    each caller unwraps itself, below, so its ``__resolved__`` marker can be
    folded where a transcript exists) — is peeled here too, at every depth
    of the chain, not just the outermost ``result``. Without this, the
    ``while`` condition below never observes the nested ``DeferredResult``
    and the chain returns a raw, unawaited handle wrapped in ``Reusable``,
    which both callers' post-loop ``isinstance(result, Reusable)`` unwrap
    then hands back verbatim under a false success. The peeled wrapper's
    ``kind``/``label`` describe a value that does not exist yet, so they are
    discarded — unlike a ``Reusable`` wrapping an already-resolved terminal
    value, which is deliberately left untouched here for the caller to
    unwrap (and, on the runner surface, fold a marker for).
    """
    resolutions = 0
    while True:
        if isinstance(result, Reusable) and isinstance(result.value, DeferredResult):
            result = result.value
            continue
        if not isinstance(result, DeferredResult):
            return result
        if resolutions >= _MAX_DEFERRED_RESOLUTIONS:
            close = getattr(result.handle, "close", None)
            if callable(close):
                close()
            cancel = getattr(result.handle, "cancel", None)
            if callable(cancel):
                cancel()
            raise AgentError(
                ErrorCategory.INTERNAL,
                "tool returned a DeferredResult nested beyond the supported depth",
                source=tool_name,
            )
        resolutions += 1
        result = await asyncio.wait_for(result.handle, timeout=handle_timeout())


class ToolInputValidationError(Exception):
    """GH-135: raised ONLY when ``input_model.model_validate(arguments)``
    rejects the caller-supplied tool_call arguments — never when the tool
    body itself raises ``ValidationError`` (e.g. constructing a ContentModel
    with bad data downstream).

    Discriminator type so ``agent/loop.py`` (and any other dispatch surface)
    can tell "the MODEL's tool_call arguments failed schema coercion" apart
    from "the tool body raised ValidationError for an unrelated reason".
    Only the former is caller-correctable input; conflating the two (a bare
    ``except ValidationError`` around both the coercion step and the tool
    body call) reports the latter to the model as if its arguments were bad,
    which triggers an unresolvable retry loop — the model has no way to fix
    arguments that were never the problem.

    Wraps the original ``pydantic.ValidationError`` (``.validation_error``)
    so callers can still build a loc+type-only diagnostic via
    ``safe_validation_message`` (SI-2: never echo the raw rejected value).

    RT-003 (SI-2): this exception's OWN message is a fixed, non-interpolating
    string — never ``str(validation_error)``. Pydantic renders a
    ``ValidationError`` with each error's ``msg``/``input`` baked in (e.g. a
    custom ``@field_validator`` that raises ``ValueError(f"bad token
    {v!r}")`` puts the raw rejected value straight into that rendering), so
    interpolating it here would arm a leak for any downstream ``except
    Exception as e: str(e)`` handler. The raw ``ValidationError`` stays
    reachable ONLY via ``.validation_error``.
    """

    def __init__(self, validation_error: ValidationError, *, tool_name: str) -> None:
        self.validation_error = validation_error
        self.tool_name = tool_name
        super().__init__(f"tool {tool_name!r} input validation failed")


UNKNOWN_ARGUMENT_ERROR_TYPE = "unknown_argument"


def _declared_argument_keys(model: type[BaseModel]) -> frozenset[str]:
    keys: set[str] = set()
    by_name = _accepts_field_name_alias(model)
    for fname, finfo in model.model_fields.items():
        va = finfo.validation_alias
        if by_name or (finfo.alias is None and va is None):
            keys.add(fname)
        if isinstance(finfo.alias, str):
            keys.add(finfo.alias)
        choices = va.choices if isinstance(va, AliasChoices) else [va]
        for choice in choices:
            if isinstance(choice, str):
                keys.add(choice)
            elif isinstance(choice, AliasPath) and choice.path and isinstance(choice.path[0], str):
                keys.add(choice.path[0])
    return frozenset(keys)


def _unknown_argument_error(keys: list[str], *, tool_name: str) -> "ToolInputValidationError":
    """GH-196: build a ToolInputValidationError naming each unknown key and
    never its value (SI-2)."""
    details = [
        InitErrorDetails(
            type=PydanticCustomError(UNKNOWN_ARGUMENT_ERROR_TYPE, "unknown argument"),
            loc=(key,),
            input=None,
        )
        for key in keys
    ]
    exc = ValidationError.from_exception_data(tool_name, details)
    return ToolInputValidationError(exc, tool_name=tool_name)


def _check_unknown_arguments(decl: "ToolDecl", arguments: dict[str, Any]) -> None:
    if decl.allow_extra_args or not arguments:
        return
    model = decl.input_model
    if model is None:
        allowed: frozenset[str] = frozenset()
    elif model.model_config.get("extra") in ("allow", "forbid"):
        return
    else:
        allowed = _declared_argument_keys(model)
    unknown = [k for k in arguments if k not in allowed]
    if unknown:
        raise _unknown_argument_error([str(k) for k in unknown], tool_name=decl.name)


@dataclass(slots=True)
class ToolTerminalResult:
    """Sentinel yielded by ``ToolEntry.invoke_gen()`` as the last item.

    Wraps the terminal result from an async-generator tool so the drain loop
    in ``loop.py`` can distinguish it from interim ``LoopEvent`` items without
    type-checking every yielded value.
    """

    value: Any


@dataclass(slots=True)
class ToolDecl:
    fn: Union[Callable[..., Awaitable[Any]], Callable[..., AsyncGenerator[Any, None]]]
    name: str
    description: str
    tier: int
    emits: type | None
    sample: dict[str, Any] | None
    input_model: type[BaseModel] | None
    adapter_params: dict[str, type[SourceAdapter]]  # param name -> adapter class
    title: str | None = None
    # MCP ToolAnnotations (2025-06-18). destructiveHint defaults to TRUE when
    # absent, so a read-only query must opt out explicitly or Claude.ai's
    # consent UI flags it as destructive.
    annotations: dict[str, Any] | None = None
    # Consumer-facing discoverability tags (A2A §1). Tier is in x-sdk, not here.
    tags: list[str] = field(default_factory=list)
    # GH-88: True when the tool function is an async generator (yields interim
    # LoopEvent items before returning its terminal result via StopAsyncIteration).
    is_generator: bool = False
    # GH-87: long-running / deferred-task support.
    # long_running=True marks the tool as capable of returning DeferredResult;
    # the loop skips the per-tier hard timeout for these tools and delegates
    # deadline enforcement to the runner's background awaiter.
    long_running: bool = False
    # Per-tool timeout override (seconds).  Applies to both the synchronous
    # invocation path and the background deferred-job awaiter in the runner.
    # None → use the tier default from LoopPolicies.tool_timeouts.
    tool_timeout_override: float | None = None
    # GH-148: wire field name (RT-019: the field's alias when one is
    # declared, else the python attribute name — see reuse.py's
    # _wire_field_name) -> ReuseKind kind for every input_model field
    # annotated Annotated[<type>, ReuseKind("<kind>")]. Empty for a tool
    # with no such fields — the loop's fast path for an unaffected tool.
    reuse_fields: dict[str, str] = field(default_factory=dict)
    # RT-008: wire field name -> ReuseKind.strict for the same fields. Absent
    # entries (and an empty dict for a tool with no reuse fields) mean
    # strict=True — resolve_reuse_fields' default when a field isn't in the
    # map at all.
    reuse_strict: dict[str, bool] = field(default_factory=dict)
    # RT-002: wire field name -> ReuseKind.allow_raw_override for the same
    # fields. Absent entries (and an empty dict) mean False — the opposite
    # default from reuse_strict, since $raw: bypassing the mismatch check is
    # an operator opt-in per field, never a caller-discoverable default.
    reuse_raw_override: dict[str, bool] = field(default_factory=dict)
    # RT-020: wire field name -> declared (Optional-stripped) scalar type for
    # the same fields. resolve_reuse_fields coerces a raw argument through
    # this type before the match check, so a value pydantic's own later
    # model_validate would accept as identical (e.g. the string "5831"
    # against an int field already resolved to 5831) is not rejected here as
    # a type mismatch before the tool is ever reached.
    reuse_field_types: dict[str, type] = field(default_factory=dict)
    # GH-196: True → unknown argument keys are not rejected (and the schema
    # advertises additionalProperties: true).
    allow_extra_args: bool = False


class ToolSet:
    """Declaration collector. Reusable across Agent instances (stateless)."""

    def __init__(self) -> None:
        self.decls: list[ToolDecl] = []

    def tool(
        self,
        *,
        tier: int = 1,
        emits: type | None = None,
        sample: dict[str, Any] | None = None,
        name: str | None = None,
        title: str | None = None,
        read_only: bool = False,
        annotations: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        long_running: bool = False,
        tool_timeout_override: float | None = None,
        allow_extra_args: bool = False,
    ) -> Callable:
        if tier not in (1, 2):
            raise ValueError("tier must be 1 (query: A2A+MCP) or 2 (composite: A2A only)")
        # ``read_only=True`` seeds the safe hints for a pure query; an explicit
        # ``annotations`` dict overrides field-by-field. ``openWorldHint`` is
        # NOT seeded here — GH-134: it must reflect whether the tool talks to
        # an external system (i.e. has a SourceAdapter-backed parameter), not
        # tier or read_only, so it is derived in decorator() below once
        # adapter_params is known from the function signature.
        base_annotations: dict[str, Any] = {}
        if read_only:
            base_annotations["readOnlyHint"] = True
            base_annotations["destructiveHint"] = False

        def decorator(
            fn: Union[Callable[..., Awaitable[Any]], Callable[..., AsyncGenerator[Any, None]]],
        ) -> Union[Callable[..., Awaitable[Any]], Callable[..., AsyncGenerator[Any, None]]]:
            _is_generator = inspect.isasyncgenfunction(fn)
            if not _is_generator and not inspect.iscoroutinefunction(fn):
                raise TypeError(f"tool {fn.__name__!r} must be async")
            _tool_name = name or fn.__name__
            # Gate on the same falsiness the resolution above uses: any falsy
            # override (None or "") falls through to fn.__name__, so a "_tool"
            # suffix would silently register verbatim. `is None` alone would
            # miss name="".
            if not name and fn.__name__.endswith("_tool"):
                _suggested_name = fn.__name__[: -len("_tool")]
                if _suggested_name:
                    logger.warning(
                        "tool function %r has no explicit name= override, so it "
                        "registered as tool %r — including the literal '_tool' "
                        "suffix. If that's unintentional (e.g. a skill/persona "
                        "expects to call %r without the suffix), pass "
                        "name=%r to @tools.tool(...) to fix it.",
                        fn.__name__,
                        _tool_name,
                        _suggested_name,
                        _suggested_name,
                    )
                else:
                    logger.warning(
                        "tool function %r has no explicit name= override, so it "
                        "registered as tool %r — including the literal '_tool' "
                        "suffix. If that's unintentional, pass an explicit "
                        "name= to @tools.tool(...) to fix it.",
                        fn.__name__,
                        _tool_name,
                    )
            if len(_tool_name) > 64:
                raise ValueError(
                    f"Tool name {_tool_name!r} exceeds 64 characters (MCP spec recommends ≤ 64)"
                )
            # eval_str: tools commonly live in modules with
            # `from __future__ import annotations`, which turns annotations
            # into strings — they must be resolved to real classes here.
            sig = inspect.signature(fn, eval_str=True)
            input_model: type[BaseModel] | None = None
            adapter_params: dict[str, type[SourceAdapter]] = {}
            for pname, param in sig.parameters.items():
                ann = param.annotation
                if param.kind == inspect.Parameter.KEYWORD_ONLY:
                    if isinstance(ann, type) and issubclass(ann, SourceAdapter):
                        adapter_params[pname] = ann
                    elif param.default is inspect.Parameter.empty:
                        raise TypeError(
                            f"tool {fn.__name__!r}: required keyword-only parameter "
                            f"{pname!r} must be annotated as a SourceAdapter"
                        )
                elif param.kind in (
                    inspect.Parameter.POSITIONAL_ONLY,
                    inspect.Parameter.POSITIONAL_OR_KEYWORD,
                ):
                    if isinstance(ann, type) and issubclass(ann, BaseModel):
                        if input_model is not None:
                            raise TypeError(
                                f"tool {fn.__name__!r}: only one positional input model allowed"
                            )
                        input_model = ann
                    elif isinstance(ann, type) and issubclass(ann, SourceAdapter):
                        raise TypeError(
                            f"tool {fn.__name__!r}: adapter params must be keyword-only "
                            f"(put {pname!r} after '*')"
                        )
                    elif param.default is inspect.Parameter.empty:
                        raise TypeError(
                            f"tool {fn.__name__!r}: required positional parameter "
                            f"{pname!r} must be a pydantic BaseModel"
                        )
                elif param.kind in (
                    inspect.Parameter.VAR_POSITIONAL,
                    inspect.Parameter.VAR_KEYWORD,
                ):
                    raise TypeError(
                        f"tool {fn.__name__!r}: *args and **kwargs are not supported"
                    )
            # GH-134: openWorldHint reflects whether this tool actually talks
            # to an external system — true iff it has at least one
            # SourceAdapter-backed parameter — not tier or read_only.
            #
            # Why `bool(adapter_params)` is a COMPLETE derivation and not a
            # heuristic (the objection every review pass raises about the False
            # case, answered here so it stays answered): the SDK's dependency-
            # injection contract is that a tool receives external capability
            # ONLY as an SDK-instantiated SourceAdapter passed by typed
            # keyword-only parameter. There is no ambient handle to hand a tool
            # reach by any other route — which is precisely why
            # CommitmentsSource is modelled as a SourceAdapter rather than a
            # module-level singleton (see agent_sdk/contrib/commitments/
            # source.py's module docstring, which states the rule outright).
            # The loop above enforces the injection side of it: every
            # keyword-only parameter must be a SourceAdapter subclass or carry
            # a default, and *args/**kwargs are rejected. So `adapter_params`
            # is the complete record of this tool's declared reach, and False
            # is a claim the SDK can stand behind, not an unknown.
            #
            # A tool body can of course still smuggle I/O in (Python enforces
            # no capabilities) — but that is a violation of the contract above,
            # not a supported pattern the annotation should hedge for, and the
            # author's escape hatch is one keyword away: an explicit
            # annotations={"openWorldHint": True} wins via the update() below.
            resolved_annotations = dict(base_annotations)
            resolved_annotations["openWorldHint"] = bool(adapter_params)
            # RT-008: the derivation above is correct and complete under the
            # SDK's DI contract (see the comment block above and LRN-043) —
            # this warning does not change it. It only flags the one shape
            # most likely to reach an external system by a route other than
            # a declared adapter parameter (a tier-2 composite tool nesting
            # a call into another tool's function, a contrib source that
            # doesn't itself follow the SourceAdapter contract): tier=2, no
            # adapter_params, and no explicit openWorldHint override. The
            # author's fix is the same escape hatch as always —
            # annotations={"openWorldHint": True} — just surfaced instead of
            # silent.
            if (
                tier == 2
                and not adapter_params
                and "openWorldHint" not in (annotations or {})
            ):
                logger.warning(
                    "tool %r is tier=2 with no SourceAdapter-backed parameter, "
                    "so it is registered with openWorldHint=False (closed-world). "
                    "If %r reaches an external system by any route other than a "
                    "SourceAdapter keyword parameter (e.g. a nested call into "
                    "another tool's function, a contrib source), pass "
                    "annotations={'openWorldHint': True} explicitly to "
                    "@tools.tool(...) — see docs/tools.md.",
                    _tool_name,
                    _tool_name,
                )
            resolved_annotations.update(annotations or {})
            # RT-015: openWorldHint is now seeded unconditionally above, so
            # resolved_annotations always contains at least that key and can
            # never be empty — `or None` was dead code. annotations is
            # therefore always a populated dict from here on (see CHANGELOG
            # GH-134 entry for the resulting decl.annotations shape change).
            description = inspect.getdoc(fn) or fn.__name__.replace("_", " ")
            resolved_title = title if title is not None else " ".join(
                word.capitalize() for word in _tool_name.split("_")
            )
            self.decls.append(
                ToolDecl(
                    fn=fn,
                    name=_tool_name,
                    description=description.strip(),
                    tier=tier,
                    emits=emits,
                    sample=sample,
                    input_model=input_model,
                    adapter_params=adapter_params,
                    title=resolved_title,
                    annotations=resolved_annotations,
                    tags=list(tags or []),
                    is_generator=_is_generator,
                    long_running=long_running,
                    tool_timeout_override=tool_timeout_override,
                    reuse_fields=reuse_fields_for_model(input_model),
                    reuse_strict=reuse_strict_for_model(input_model),
                    reuse_raw_override=reuse_raw_override_for_model(input_model),
                    reuse_field_types=reuse_field_types_for_model(input_model),
                    allow_extra_args=allow_extra_args,
                )
            )
            return fn

        return decorator


@dataclass(slots=True)
class ToolEntry:
    decl: ToolDecl

    @property
    def name(self) -> str:
        return self.decl.name

    @property
    def tier(self) -> int:
        return self.decl.tier

    @property
    def description(self) -> str:
        return self.decl.description

    @property
    def title(self) -> str | None:
        return self.decl.title

    @property
    def annotations(self) -> dict[str, Any] | None:
        return self.decl.annotations

    def input_schema(self, *, include_reuse_hint: bool = False) -> dict[str, Any]:
        """JSON Schema for this tool's input.

        RT-005: ``include_reuse_hint`` must stay ``False`` on every surface
        except ``loop.py`` — the ``$ref:<kind>`` substitution/validation gate
        (agent/reuse.py) is loop-only (GH-148). MCP ``tools/call``
        (routes/mcp.py) — and the admin try-tool endpoint and the
        commitments executor, the other two ``ToolEntry.invoke_any`` callers
        — REJECT a ``$ref:``/``$raw:`` token on a ``ReuseKind`` field outright
        rather than resolving it (RT-A-009; see ``invoke_any``'s GH-148
        docstring paragraph and test_gh148_reuse_kind_substitution.py's
        ``test_mcp_tools_call_ref_token_rejected_no_conversation_transcript``);
        the agent card's ``x-sdk.inputSchema`` (routes/agent_card.py) is
        advisory metadata only — no dispatch path reads it. Advertising the
        hint on either surface would promise an affordance neither honours.

        RT-B-004: when the hint IS included, a ``ReuseKind`` field whose
        advertised type excludes strings (``Annotated[int, ReuseKind(...)]``
        renders as ``{"type": "integer"}``) is widened to ``{"anyOf":
        [<original>, {"type": "string", ...}]}`` so the ``$ref:<kind>``
        token — itself a string sentinel — is actually representable. Without
        that, Bedrock Converse and every other provider that constrains tool
        arguments to the declared schema silently make the mechanism
        unusable on any non-string field while ``reuse_fields_for_model``
        accepts the annotation without complaint. A plain string-typed field
        is untouched: the token is already representable and the schema is
        byte-identical to before. RT-004: a string-typed field whose own
        value space is narrowed by ``pattern``/``const``/``format``/
        ``minLength``/``maxLength`` (a regex-validated or UUID-formatted id,
        for instance) is widened the same way — its own constraint does not
        provably admit the sentinel either. Only the ``include_reuse_hint
        =True`` rendering is widened — the tool's own ``input_model``
        validation is unchanged, and by the time ``ToolEntry.invoke`` runs
        ``model_validate``, ``resolve_reuse_fields`` has already replaced the
        token with the resolved value of the field's real type.
        """
        if self.decl.input_model is None:
            return {
                "type": "object",
                "properties": {},
                "required": [],
                "additionalProperties": self.decl.allow_extra_args,
            }
        schema = self.decl.input_model.model_json_schema()
        extra = self.decl.input_model.model_config.get("extra")
        if self.decl.allow_extra_args or extra == "allow":
            schema["additionalProperties"] = True
        else:
            schema.setdefault("additionalProperties", False)
        schema.setdefault("required", [])
        if include_reuse_hint and self.decl.reuse_fields:
            properties = schema.get("properties")
            if isinstance(properties, dict):
                # RT-019: reuse_fields is keyed by wire name (the field's
                # alias when declared), the same key model_json_schema()
                # uses for `properties` — so this lookup matches an aliased
                # field too, not just an unaliased one.
                for wire_name, kind in self.decl.reuse_fields.items():
                    prop = properties.get(wire_name)
                    if not isinstance(prop, dict):
                        continue
                    # RT-B-004: the hint below is a model-facing affordance
                    # whose token is a STRING. On a field whose advertised
                    # type excludes strings (Annotated[int, ReuseKind(...)]),
                    # a schema-enforcing provider cannot emit that token, so
                    # a description-only hint promises an affordance the
                    # model has no way to use. Widen the advertised type to
                    # accept the token before describing it — never advertise
                    # in prose what the schema forbids.
                    if not _schema_permits_string(prop, schema.get("$defs")):
                        prop = _widen_for_reuse_token(prop)
                        properties[wire_name] = prop
                    hint = (
                        f"Accepts a raw value, or the token $ref:{kind} "
                        f"(or $ref:{kind}:<label> to disambiguate multiple "
                        "resolutions) referencing a value a previous tool "
                        "call in this conversation resolved."
                    )
                    existing = prop.get("description")
                    prop["description"] = f"{existing} {hint}" if existing else hint
        return schema

    def output_schema(self) -> dict[str, Any] | None:
        """MCP outputSchema, derived from emits (DESIGN §5.5). None → no
        structuredContent is ever emitted for this tool (never unclaimed).

        RTGA-001: MarketBriefing is the sole prose-exception type on the
        AG-UI/A2A wire (translator.py emits its to_markdown() as a bare
        string) — but MCP 2025-06-18 requires Tool.outputSchema to always be
        a JSON object (GH-105), so the markdown is wrapped in an object
        under a "markdown" key rather than advertised as {"type": "string"}.
        This method backs MCP's tools/list outputSchema only (the agent card
        no longer repeats it, GH-219). The A2A DataPart wire itself
        (translator.py) stays a bare markdown string.
        """
        from ..models.content_types import MarketBriefing

        emits = self.decl.emits
        if emits is None:
            return None
        if not issubclass(emits, BaseModel):
            return None
        if issubclass(emits, MarketBriefing):
            return {
                "type": "object",
                "properties": {"markdown": {"type": "string"}},
                "required": ["markdown"],
            }
        return emits.model_json_schema()

    async def invoke(
        self,
        arguments: dict[str, Any],
        adapters: dict[type[SourceAdapter], SourceAdapter],
    ) -> Any:
        """Invoke a coroutine tool and return its result.

        For async-generator tools (GH-88) use ``invoke_gen()`` instead.
        This method raises TypeError when called on a generator tool to ensure
        callers always check ``decl.is_generator`` first.
        """
        if self.decl.is_generator:
            raise TypeError(
                f"tool {self.decl.name!r} is an async-generator; use invoke_gen() instead"
            )
        kwargs: dict[str, Any] = {
            pname: adapters[cls] for pname, cls in self.decl.adapter_params.items()
        }
        coro_fn = cast(Callable[..., Awaitable[Any]], self.decl.fn)
        _check_unknown_arguments(self.decl, arguments)
        if self.decl.input_model is not None:
            # RT-004: narrow try — ONLY model_validate. A ValidationError
            # raised later, while coro_fn builds its ContentModel return
            # value, must propagate as a bare ValidationError, not be
            # mistaken for an input-shape defect.
            try:
                inp = self.decl.input_model.model_validate(arguments)
            except ValidationError as exc:
                raise ToolInputValidationError(exc, tool_name=self.decl.name) from exc
            return await coro_fn(inp, **kwargs)
        return await coro_fn(**kwargs)

    async def invoke_gen(
        self,
        arguments: dict[str, Any],
        adapters: dict[type[SourceAdapter], SourceAdapter],
    ) -> AsyncGenerator[Any, None]:
        """GH-88: drain an async-generator tool.

        Contract for async-generator tools:
        - Yield ``ToolProgressEvent`` (or any ``LoopEvent`` subclass) for
          interim notifications.
        - Yield the terminal result (a non-``LoopEvent`` value, e.g. a Pydantic
          model) as the LAST ``yield`` statement.

        This method yields each item from the generator in order; the LAST item
        is always wrapped in a ``ToolTerminalResult`` sentinel so the loop can
        distinguish interim events from the terminal result without inspecting
        every item's type. Callers check ``isinstance(item, ToolTerminalResult)``
        to detect the terminal result.

        Python async generators cannot use ``return <value>`` — the terminal
        result must be the final ``yield`` from the generator function.

        Raises TypeError when called on a non-generator tool.
        """
        if not self.decl.is_generator:
            raise TypeError(
                f"tool {self.decl.name!r} is a coroutine, not an async-generator; "
                "use invoke() instead"
            )
        kwargs: dict[str, Any] = {
            pname: adapters[cls] for pname, cls in self.decl.adapter_params.items()
        }
        gen_fn = cast(Callable[..., AsyncGenerator[Any, None]], self.decl.fn)
        _check_unknown_arguments(self.decl, arguments)
        if self.decl.input_model is not None:
            # RT-004: narrow try — see invoke()'s matching comment.
            try:
                inp = self.decl.input_model.model_validate(arguments)
            except ValidationError as exc:
                raise ToolInputValidationError(exc, tool_name=self.decl.name) from exc
            agen = gen_fn(inp, **kwargs)
        else:
            agen = gen_fn(**kwargs)

        # Drain the generator; buffer the last item to wrap it as the terminal
        # result.  All items EXCEPT the last are yielded as-is (interim events);
        # the last item is wrapped in ToolTerminalResult so the loop can detect
        # the boundary without type-checking every event.
        prev: Any = _SENTINEL  # sentinel: "no item yet"
        async for item in agen:
            if prev is not _SENTINEL:
                yield prev  # emit the previous (interim) item
            prev = item     # buffer current item

        # prev now holds the last (terminal) item — wrap it.
        terminal = None if prev is _SENTINEL else prev
        yield ToolTerminalResult(value=terminal)

    async def invoke_any(
        self,
        arguments: dict[str, Any],
        adapters: dict[type[SourceAdapter], SourceAdapter],
        *,
        timeout: float | None = None,
        policies: "LoopPolicies | None" = None,
    ) -> Any:
        """Invoke this tool regardless of whether it is a coroutine or an
        async-generator (RT-002/LRN-116), optionally under a caller-supplied
        timeout budget (RT-001).

        A caller with no channel to forward interim progress downstream
        (MCP's single JSON-RPC response, the admin console's try-tool
        endpoint, the commitments executor's background fire) should use
        this instead of reimplementing the ``decl.is_generator`` branch: for
        a generator tool it drains ``invoke_gen()``, discarding interim
        ``LoopEvent`` items and returning the terminal value, so callers
        never see the ``TypeError`` ``invoke()`` raises for a generator
        entry.

        A caller that DOES have a channel to forward interim events (the live
        agent loop, ``agent/loop.py``) should keep draining ``invoke_gen()``
        directly — this shortcut always discards them.

        ``timeout`` — when given, bounds the initial invoke/drain (mirroring
        every other invocation surface's ``asyncio.wait_for``/
        ``asyncio.timeout``) under ONE deadline that also covers resolving a
        returned ``DeferredResult`` (RT-003): the handle gets whatever budget
        REMAINS after the initial call, never a fresh ``timeout`` seconds on
        top, so a slow initial call can't double the worst-case wall-clock
        block. When omitted (the commitments executor's call shape, which has
        no per-call deadline of its own), the initial invoke/drain is
        unbounded and only a returned ``DeferredResult`` is bounded, via
        ``resolve_tool_timeout`` against ``policies`` (or a default
        ``LoopPolicies()``). Only the executor's CALL SITE is legacy/unchanged
        (it still calls ``invoke_any(args, adapters)``); the BEHAVIOR is NOT —
        RT-001: before GH-120 this method returned the ``DeferredResult``
        verbatim and the executor dropped the handle unawaited (side effect
        never ran, yet the commitment was still marked fired). The handle is
        now awaited here, so a committed ``long_running`` tool is marked fired
        only after its deferred side effect completes, and marked failed if it
        times out.

        RT-002: a ``long_running=True`` tool may return ``DeferredResult``
        instead of a terminal value (the other long_running form besides the
        async-generator one — ``agent/deferred.py``). This caller has no
        background delivery channel either (mirroring why ``routes/mcp.py``
        resolves it inline), so the handle is awaited here rather than being
        returned verbatim and silently dropped unawaited.

        GH-120: the awaited handle is rechecked — a handle that resolves to
        ANOTHER ``DeferredResult`` is itself resolved (up to
        ``_MAX_DEFERRED_RESOLUTIONS`` handles total), rather than the nested
        object being returned verbatim (which baked an unawaited coroutine's
        repr into the MCP wire text under a false ``isError: false``).
        Nesting beyond that bound raises ``AgentError`` — a clean, generic
        internal error every caller (mcp.py, admin.py, the commitments
        executor) already maps to its existing isError/ok:false path.

        RT-001 (follow-up): the nested-resolution loop itself lives in the
        module-level ``resolve_deferred_result`` (C-012) so ``runner.py``'s
        background deferred-job awaiter shares the identical nesting-DEPTH
        bound and rejection point instead of maintaining its own divergent
        branch.

        RT-002: that shared contract covers depth, not the timeout budget.
        When this method is called with ``timeout=None`` (the commitments
        executor's call shape — see the ``timeout`` paragraph above),
        ``_handle_timeout`` re-derives a FULL ``resolve_tool_timeout`` budget
        before EACH nested await, unlike the one shrinking deadline a
        timeout-bearing ``invoke_any`` call and ``runner.
        _run_deferred_background`` both thread through. A slow nested-
        ``DeferredResult`` chain can therefore succeed on the commitments
        surface while timing out identically on MCP/A2A for the same tool
        contract — intentional, since the commitments path has no per-call
        deadline to shrink in the first place, not a parity regression.

        RT-002 (follow-up, GH-148 cross-surface parity): a tool may return
        ``Reusable`` (GH-148 — a cross-turn-citable result) instead of, or
        nested inside, a resolved ``DeferredResult``. Two OTHER call sites —
        not this method — also unwrap ``Reusable`` and fold its
        ``__resolved__`` marker into a ``messages`` transcript, because both
        have one to fold into: ``agent/loop.py``'s synchronous ``run_loop``
        branch (which additionally grows ``resolved_index`` in place, so a
        LATER tool call in that SAME ``run_loop`` invocation can already
        reference the value via ``$ref:<kind>``) and ``agent/runner.py``'s
        ``_run_deferred_background`` (RT-001: the background awaiter for a
        ``long_running`` tool's ``DeferredEvent`` — it folds the identical
        marker into ``record.messages``, but has no live ``resolved_index``
        to grow since ``run_loop`` already exited at the handoff; a LATER
        contextId continuation's fresh ``run_loop`` call rebuilds the index
        from that folded marker via ``scan_resolved`` instead). The three
        callers of THIS method (MCP ``tools/call``, the admin try-tool
        endpoint, the commitments executor) have no such transcript, so they
        cannot participate in the ``$ref:<kind>`` substitution/validation
        gate — a ``Reusable``-returning tool called from one of them
        therefore never grows the resolved index and never accepts a
        ``$ref:<kind>`` token on that same call, by design (the gate is
        conversation-scoped, i.e. loop.py/runner.py only). What they MUST NOT
        do is leak the wrapper itself: without unwrapping here,
        ``artifact.wire()``/``_tool_text``/``_safe_result`` would each
        serialize the raw ``Reusable`` dataclass (or fail an ``emits``
        coercion against it) instead of its ``.value``, diverging from the
        identical call over A2A/AG-UI in violation of §5.6. So this unwraps
        ``Reusable`` to ``.value`` — same semantics as a plain ``return`` —
        after any ``DeferredResult`` chain is resolved, since a deferred
        handle may itself resolve to a ``Reusable``.

        RT-A-009: "never accepts a ``$ref:<kind>`` token" above is enforced
        as an outright REJECTION, not silent passthrough. Before invoking the
        tool body, every ``decl.reuse_fields`` field (i.e. every
        ``ReuseKind``-annotated field, regardless of its own ``strict``/
        ``allow_raw_override`` flags — those only govern the loop.py path)
        whose supplied argument is a string starting with ``REF_PREFIX``
        (``$ref:``) or ``RAW_PREFIX`` (``$raw:``) raises
        ``AgentError(ErrorCategory.VALIDATION, ...)``, which every caller of
        this method already maps to its existing failure shape — ``isError:
        true`` (mcp.py), ``ok: false`` (admin.py), or ``mark_failed``
        (the commitments executor) — rather than a JSON-RPC/HTTP-level
        error. Landed after GH-148 shipped: neither token means anything
        without a ``messages`` transcript to resolve it against, so handing
        it to the tool body as an ordinary string — e.g. a lookup for an
        entity literally named ``"$ref:entity_id"`` — is a silent,
        wrong-but-successful result, strictly worse than failing outright.
        Previously this method let it through unchanged (pinned, before this
        fix, by test_gh148_reuse_kind_substitution.py's
        ``test_mcp_tools_call_ref_token_passes_through_no_conversation_transcript``,
        since renamed to
        ``test_mcp_tools_call_ref_token_rejected_no_conversation_transcript``
        to match) — an MCP client (or any caller of these three surfaces)
        that read the token syntax off the CHANGELOG or the loop-side
        ``input_schema(include_reuse_hint=True)`` description got a
        wrong-but-successful result instead of a diagnosable error.
        """
        if self.decl.reuse_fields:
            for field_name in self.decl.reuse_fields:
                raw = arguments.get(field_name)
                if isinstance(raw, str) and (
                    raw.startswith(REF_PREFIX) or raw.startswith(RAW_PREFIX)
                ):
                    raise AgentError(
                        ErrorCategory.VALIDATION,
                        f"tool {self.decl.name!r} field {field_name!r} does "
                        "not support $ref:/$raw: reuse tokens on this call "
                        "surface — supply the raw value directly",
                        source=self.decl.name,
                    )

        deadline = time.monotonic() + timeout if timeout is not None else None

        if not self.decl.is_generator:
            invoke_coro = self.invoke(arguments, adapters)
            result = (
                await asyncio.wait_for(invoke_coro, timeout=timeout)
                if timeout is not None
                else await invoke_coro
            )
        else:
            result = None
            gen = self.invoke_gen(arguments, adapters)
            if timeout is not None:
                async with asyncio.timeout(timeout):
                    async for gen_item in gen:
                        if isinstance(gen_item, ToolTerminalResult):
                            result = gen_item.value
            else:
                async for gen_item in gen:
                    if isinstance(gen_item, ToolTerminalResult):
                        result = gen_item.value

        def _handle_timeout() -> float:
            if deadline is not None:
                return max(0.0, deadline - time.monotonic())
            from .loop import LoopPolicies, resolve_tool_timeout  # local: avoid import cycle

            return resolve_tool_timeout(self.decl.name, self, policies or LoopPolicies())

        result = await resolve_deferred_result(
            result, tool_name=self.decl.name, handle_timeout=_handle_timeout
        )
        if isinstance(result, Reusable):
            result = result.value
        return result


class ToolRegistry:
    """Resolved registry: built once at build_app(); single source of truth
    for the card, MCP tools/list, the loop's toolConfig and the console."""

    def __init__(
        self,
        toolsets: list[ToolSet],
        registered_adapters: dict[type[SourceAdapter], Any],
    ) -> None:
        self.entries: dict[str, ToolEntry] = {}
        for ts in toolsets:
            for decl in ts.decls:
                if len(decl.name) > 64:
                    raise ValueError(
                        f"tool name {decl.name!r} exceeds 64-char MCP Directory limit"
                    )
                if decl.name in self.entries:
                    raise ValueError(f"duplicate tool name {decl.name!r}")
                for pname, cls in decl.adapter_params.items():
                    if cls not in registered_adapters:
                        raise ValueError(
                            f"tool {decl.name!r} parameter {pname!r} requires adapter "
                            f"{cls.__name__} which is not registered "
                            f"(call agent.register_source({cls.__name__}, ...))"
                        )
                self.entries[decl.name] = ToolEntry(decl=decl)

    def get(self, name: str) -> ToolEntry | None:
        return self.entries.get(name)

    def tier1(self) -> list[ToolEntry]:
        return [e for e in self.entries.values() if e.tier == 1]

    def all(self) -> list[ToolEntry]:
        return list(self.entries.values())
