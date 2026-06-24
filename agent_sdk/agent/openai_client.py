"""OpenAIModelClient — gpt-5 (Azure or vanilla) behind the ModelClient seam.

A second, opt-in backend alongside :class:`~agent_sdk.agent.bedrock.BedrockModelClient`.
The loop speaks Bedrock **Converse** shapes (DESIGN §8); this client translates
Converse↔OpenAI chat-completions in both directions so the loop is unchanged:

- assistant turn   ``{"role":"assistant","content":[{"text"},{"toolUse"}]}``
  → OpenAI assistant message with ``content`` + ``tool_calls``
- tool results     ``{"role":"user","content":[{"toolResult":...}]}``
  → one OpenAI ``{"role":"tool", "tool_call_id", "content"}`` per result
- OpenAI response  → :class:`ModelResponse` (text segments + ``ModelToolCall`` list)

``import openai`` is deferred (like boto3) so test/Bedrock deployments never pay
for it. gpt-5 is a reasoning model: temperature is left at its only supported
value (default) and the token cap is applied ONLY when explicitly configured —
a small ``max_completion_tokens`` would be consumed by reasoning and yield an
empty completion, so by default we let the model manage its own budget.

Errors are wrapped to ``AgentError(UPSTREAM, "model invocation failed")`` with
no provider detail — request content never leaks into logs or errors.
"""

from __future__ import annotations

import json
from typing import Any

from ..models.errors import AgentError, ErrorCategory
from .model_client import ModelResponse, ModelToolCall

# OpenAI finish_reason → Converse stop_reason (informational; the loop keys
# control flow off the presence of tool_calls, not this field).
_STOP_REASON = {"tool_calls": "tool_use", "length": "max_tokens", "stop": "end_turn"}


class OpenAIModelClient:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        azure_endpoint: str | None = None,
        azure_api_version: str | None = None,
        azure_deployment: str | None = None,
        reasoning_effort: str | None = None,
        max_completion_tokens: int | None = None,
    ) -> None:
        if not model and not azure_deployment:
            raise ValueError("OpenAIModelClient requires model or azure_deployment")
        self._model = azure_deployment or model
        self._api_key = api_key
        self._base_url = base_url
        self._azure_endpoint = azure_endpoint
        self._azure_api_version = azure_api_version
        self._azure_deployment = azure_deployment
        self._reasoning_effort = reasoning_effort
        self._max_completion_tokens = max_completion_tokens
        self._client: Any = None

    # ── client construction (deferred import) ──
    def _openai_client(self) -> Any:
        if self._client is None:
            import openai  # deferred: optional dependency, like boto3

            if self._azure_endpoint:
                self._client = openai.AsyncAzureOpenAI(
                    azure_endpoint=self._azure_endpoint,
                    api_key=self._api_key,
                    api_version=self._azure_api_version,
                )
            else:
                self._client = openai.AsyncOpenAI(
                    api_key=self._api_key, base_url=self._base_url
                )
        return self._client

    # ── seam ──
    async def converse(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
    ) -> ModelResponse:
        request: dict[str, Any] = {
            "model": self._model,
            "messages": self._to_openai_messages(system, messages),
        }
        if tools:
            request["tools"] = self._to_openai_tools(tools)
            request["tool_choice"] = "auto"
        if self._reasoning_effort:
            request["reasoning_effort"] = self._reasoning_effort
        if self._max_completion_tokens is not None:
            request["max_completion_tokens"] = self._max_completion_tokens

        try:
            raw = await self._openai_client().chat.completions.create(**request)
        except ModuleNotFoundError:
            raise
        except Exception as exc:  # openai raises dynamic error classes
            raise AgentError(
                ErrorCategory.UPSTREAM, "model invocation failed", source="openai"
            ) from exc
        return self._parse(raw)

    # ── Converse → OpenAI ──
    @staticmethod
    def _to_openai_messages(
        system: str, messages: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        out: list[dict[str, Any]] = []
        if system:
            out.append({"role": "system", "content": system})
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content") or []
            if role == "assistant":
                out.append(OpenAIModelClient._assistant_to_openai(content))
            else:  # "user": text query and/or folded tool results
                text_parts: list[str] = []
                for block in content:
                    if "toolResult" in block:
                        # tool messages must directly follow the assistant
                        # tool_calls turn — emit them before any user text.
                        tr = block["toolResult"]
                        out.append(
                            {
                                "role": "tool",
                                "tool_call_id": tr.get("toolUseId", ""),
                                "content": OpenAIModelClient._tool_result_text(
                                    tr.get("content") or []
                                ),
                            }
                        )
                    elif "text" in block:
                        text_parts.append(block["text"])
                if text_parts:
                    out.append({"role": "user", "content": "\n".join(text_parts)})
        return out

    @staticmethod
    def _assistant_to_openai(content: list[dict[str, Any]]) -> dict[str, Any]:
        text_parts: list[str] = []
        tool_calls: list[dict[str, Any]] = []
        for block in content:
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                tu = block["toolUse"]
                tool_calls.append(
                    {
                        "id": tu.get("toolUseId", ""),
                        "type": "function",
                        "function": {
                            "name": tu.get("name", ""),
                            "arguments": json.dumps(tu.get("input", {}) or {}),
                        },
                    }
                )
        message: dict[str, Any] = {
            "role": "assistant",
            "content": "\n".join(text_parts) if text_parts else None,
        }
        if tool_calls:
            message["tool_calls"] = tool_calls
        return message

    @staticmethod
    def _tool_result_text(content_blocks: list[dict[str, Any]]) -> str:
        parts: list[str] = []
        for block in content_blocks:
            if "json" in block:
                parts.append(json.dumps(block["json"]))
            elif "text" in block:
                parts.append(block["text"])
        return "\n".join(parts)

    @staticmethod
    def _to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t.get("description", ""),
                    "parameters": t["input_schema"],
                },
            }
            for t in tools
        ]

    # ── OpenAI → ModelResponse ──
    @staticmethod
    def _parse(raw: Any) -> ModelResponse:
        choice = raw.choices[0]
        message = choice.message
        out = ModelResponse(
            stop_reason=_STOP_REASON.get(choice.finish_reason or "stop", "end_turn")
        )
        if message.content:
            out.text_segments.append(message.content)
        for tc in getattr(message, "tool_calls", None) or []:
            try:
                arguments = json.loads(tc.function.arguments or "{}")
            except (ValueError, TypeError):
                arguments = {}
            if not isinstance(arguments, dict):
                arguments = {}
            out.tool_calls.append(
                ModelToolCall(
                    tool_call_id=tc.id, name=tc.function.name, arguments=arguments
                )
            )
        usage = getattr(raw, "usage", None)
        if usage is not None:
            out.input_tokens = getattr(usage, "prompt_tokens", 0) or 0
            out.output_tokens = getattr(usage, "completion_tokens", 0) or 0
        return out
