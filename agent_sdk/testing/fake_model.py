"""FakeModelClient — scripted ModelClient for tests (DESIGN.md §11)."""

from __future__ import annotations

import uuid
from typing import Any

from ..agent.model_client import ModelResponse, ModelToolCall
from ..models.errors import AgentError, ErrorCategory


def reply(text: str, *, input_tokens: int = 10, output_tokens: int = 10) -> ModelResponse:
    """A final assistant turn (no tool calls → loop completes)."""
    return ModelResponse(
        text_segments=[text],
        stop_reason="end_turn",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def tool_call(
    name: str,
    arguments: dict[str, Any] | None = None,
    *,
    text: str = "",
    tool_call_id: str | None = None,
    input_tokens: int = 10,
    output_tokens: int = 10,
) -> ModelResponse:
    """An assistant turn that invokes one tool."""
    return ModelResponse(
        text_segments=[text] if text else [],
        tool_calls=[
            ModelToolCall(
                tool_call_id=tool_call_id or uuid.uuid4().hex,
                name=name,
                arguments=arguments or {},
            )
        ],
        stop_reason="tool_use",
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


class FakeModelClient:
    """Replays the scripted responses in order; records every converse call
    (``.calls``) for assertions. Exhausting the script raises — a test that
    loops longer than scripted is a bug, not a hang."""

    def __init__(self, responses: list[ModelResponse] | None = None) -> None:
        self.responses = list(responses or [])
        self.calls: list[dict[str, Any]] = []

    def script(self, *responses: ModelResponse) -> "FakeModelClient":
        self.responses.extend(responses)
        return self

    async def converse(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
    ) -> ModelResponse:
        self.calls.append(
            {
                "system": system,
                "messages": [dict(m) for m in messages],
                "tools": tools,
                "max_tokens": max_tokens,
            }
        )
        if not self.responses:
            raise AgentError(
                ErrorCategory.INTERNAL,
                "FakeModelClient script exhausted "
                f"(call #{len(self.calls)}; scripted {len(self.calls) - 1})",
            )
        return self.responses.pop(0)
