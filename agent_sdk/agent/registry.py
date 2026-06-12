"""ToolSet (declaration) and ToolRegistry (resolved at build_app).

ToolSet is a stateless declaration list — explicit collection, no import
side effects (DESIGN.md §4.1). Adapter dependencies are declared solely by
keyword-only parameter annotations (exact-class match); there is no
``source=`` kwarg. All wiring errors raise at ``build_app()``, never at
call time.
"""

from __future__ import annotations

import inspect
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from pydantic import BaseModel

from ..sources import SourceAdapter


@dataclass(slots=True)
class ToolDecl:
    fn: Callable[..., Awaitable[Any]]
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
    ) -> Callable:
        if tier not in (1, 2):
            raise ValueError("tier must be 1 (query: A2A+MCP) or 2 (composite: A2A only)")
        # ``read_only=True`` seeds the safe hints for a pure query; an explicit
        # ``annotations`` dict overrides field-by-field.
        ann: dict[str, Any] = {}
        if read_only:
            ann["readOnlyHint"] = True
            ann["destructiveHint"] = False
        ann.update(annotations or {})
        merged_annotations = ann or None

        def decorator(fn: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
            if not inspect.iscoroutinefunction(fn):
                raise TypeError(f"tool {fn.__name__!r} must be async")
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
            description = inspect.getdoc(fn) or fn.__name__.replace("_", " ")
            self.decls.append(
                ToolDecl(
                    fn=fn,
                    name=name or fn.__name__,
                    description=description.strip(),
                    tier=tier,
                    emits=emits,
                    sample=sample,
                    input_model=input_model,
                    adapter_params=adapter_params,
                    title=title,
                    annotations=merged_annotations,
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
            return {"type": "object", "properties": {}, "additionalProperties": False}
        return self.decl.input_model.model_json_schema()

    def output_schema(self) -> dict[str, Any] | None:
        """MCP outputSchema, derived from emits (DESIGN §5.5). None → no
        structuredContent is ever emitted for this tool (never unclaimed)."""
        emits = self.decl.emits
        if emits is not None and issubclass(emits, BaseModel):
            return emits.model_json_schema()
        return None

    async def invoke(
        self,
        arguments: dict[str, Any],
        adapters: dict[type[SourceAdapter], SourceAdapter],
    ) -> Any:
        kwargs: dict[str, Any] = {
            pname: adapters[cls] for pname, cls in self.decl.adapter_params.items()
        }
        if self.decl.input_model is not None:
            inp = self.decl.input_model.model_validate(arguments)
            return await self.decl.fn(inp, **kwargs)
        return await self.decl.fn(**kwargs)


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
