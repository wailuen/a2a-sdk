"""ToolSet (declaration) and ToolRegistry (resolved at build_app).

ToolSet is a stateless declaration list — explicit collection, no import
side effects (DESIGN.md §4.1). Adapter dependencies are declared solely by
keyword-only parameter annotations (exact-class match); there is no
``source=`` kwarg. All wiring errors raise at ``build_app()``, never at
call time.
"""

from __future__ import annotations

import inspect
import logging
from dataclasses import dataclass, field
from typing import Any, AsyncGenerator, AsyncIterator, Awaitable, Callable, Optional, Union, cast

from pydantic import BaseModel

from ..sources import SourceAdapter

logger = logging.getLogger(__name__)


# ── GH-88 sentinel types ──

# Unique object used as "no item buffered yet" placeholder in invoke_gen.
_SENTINEL = object()


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
        # ``annotations`` dict overrides field-by-field.
        ann: dict[str, Any] = {}
        if read_only:
            ann["readOnlyHint"] = True
            ann["destructiveHint"] = False
        if tier == 1 or read_only:
            ann["openWorldHint"] = False
        ann.update(annotations or {})
        merged_annotations = ann or None

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
                    annotations=merged_annotations,
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
            inp = self.decl.input_model.model_validate(arguments)
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
        from .events import LoopEvent  # local import to avoid circulars

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
            inp = self.decl.input_model.model_validate(arguments)
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
    ) -> Any:
        """Invoke this tool regardless of whether it is a coroutine or an
        async-generator (RT-002/LRN-116).

        A caller with no channel to forward interim progress downstream (MCP's
        single JSON-RPC response, the commitments executor's background fire)
        should use this instead of reimplementing the ``decl.is_generator``
        branch: for a generator tool it drains ``invoke_gen()``, discarding
        interim ``LoopEvent`` items and returning the terminal value, so
        callers never see the ``TypeError`` ``invoke()`` raises for a
        generator entry.

        A caller that DOES have a channel to forward interim events (the live
        agent loop, ``agent/loop.py``) should keep draining ``invoke_gen()``
        directly — this shortcut always discards them.
        """
        if not self.decl.is_generator:
            return await self.invoke(arguments, adapters)
        result: Any = None
        async for gen_item in self.invoke_gen(arguments, adapters):
            if isinstance(gen_item, ToolTerminalResult):
                result = gen_item.value
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
