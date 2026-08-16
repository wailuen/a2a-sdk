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

from pydantic import BaseModel, ValidationError

from ..models.errors import AgentError, ErrorCategory
from ..sources import SourceAdapter
from .deferred import DeferredResult

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
    """
    resolutions = 0
    while isinstance(result, DeferredResult):
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
    return result


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

    def input_schema(self) -> dict[str, Any]:
        if self.decl.input_model is None:
            return {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
        schema = self.decl.input_model.model_json_schema()
        schema.setdefault("additionalProperties", False)
        schema.setdefault("required", [])
        return schema

    def output_schema(self) -> dict[str, Any] | None:
        """MCP outputSchema, derived from emits (DESIGN §5.5). None → no
        structuredContent is ever emitted for this tool (never unclaimed).

        RTGA-001: MarketBriefing is the sole prose-exception type on the
        AG-UI/A2A wire (translator.py emits its to_markdown() as a bare
        string) — but MCP 2025-06-18 requires Tool.outputSchema to always be
        a JSON object (GH-105), so the markdown is wrapped in an object
        under a "markdown" key rather than advertised as {"type": "string"}.
        This method backs both advertisement surfaces — MCP's tools/list
        outputSchema and the agent card's x-sdk.outputSchema (agent_card.py,
        RT-004) — so the object-wrapper appears in both. Only the A2A
        DataPart wire itself (translator.py) stays a bare markdown string.
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
        if self.decl.input_model is not None:
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
        if self.decl.input_model is not None:
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
        """
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

        return await resolve_deferred_result(
            result, tool_name=self.decl.name, handle_timeout=_handle_timeout
        )


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
