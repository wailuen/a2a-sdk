"""ModelClient seam (DESIGN.md §8). v1 backend: Bedrock Converse."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable


@dataclass(slots=True)
class ModelToolCall:
    tool_call_id: str
    name: str
    arguments: dict[str, Any]


@dataclass(slots=True)
class ModelResponse:
    text_segments: list[str] = field(default_factory=list)
    tool_calls: list[ModelToolCall] = field(default_factory=list)
    stop_reason: str = "end_turn"  # "end_turn" | "tool_use" | "max_tokens"
    input_tokens: int = 0
    output_tokens: int = 0


@runtime_checkable
class ModelClient(Protocol):
    async def converse(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
        tool_choice: Literal["auto", "none"] = "auto",
    ) -> ModelResponse: ...

    # reserved (non-breaking to add): async def converse_stream(...)
