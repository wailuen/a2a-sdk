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

Retry asymmetry (GH-133): :class:`~agent_sdk.sources.SourceAdapter._request`
retries once itself on a 429/503 response (sources.py:151-154). This client
does not — it has no retry-once policy of its own. ``max_retries``/``timeout``,
when passed to ``__init__``, are forwarded verbatim to the underlying
``AsyncOpenAI``/``AsyncAzureOpenAI`` constructor, which owns its own retry
count and backoff; left unset, the openai SDK's own defaults apply.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from ..common.redact import frame_locations
from ..models.errors import AgentError, ErrorCategory
from .model_client import ModelResponse, ModelToolCall

logger = logging.getLogger(__name__)

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
        max_retries: int | None = None,
        timeout: float | None = None,
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
        self._max_retries = max_retries
        self._timeout = timeout
        self._client: Any = None

    # ── client construction (deferred import) ──
    def _openai_client(self) -> Any:
        # Retry asymmetry vs SourceAdapter._request(): see module docstring.
        if self._client is None:
            import openai  # deferred: optional dependency, like boto3

            extra: dict[str, Any] = {}
            if self._max_retries is not None:
                extra["max_retries"] = self._max_retries
            if self._timeout is not None:
                extra["timeout"] = self._timeout

            if self._azure_endpoint:
                self._client = openai.AsyncAzureOpenAI(
                    azure_endpoint=self._azure_endpoint,
                    api_key=self._api_key,
                    api_version=self._azure_api_version,
                    **extra,
                )
            else:
                self._client = openai.AsyncOpenAI(
                    api_key=self._api_key, base_url=self._base_url, **extra
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
            # Deferred import INSIDE the try: when the optional `openai` extra
            # is simply not installed, this line is what raises — so leaving it
            # above the try made the ModuleNotFoundError branch below
            # unreachable for the overwhelmingly common case. `_openai` is only
            # dereferenced by the RateLimitError clause, which Python never
            # evaluates when the earlier ModuleNotFoundError clause matches.
            import openai as _openai
            raw = await self._openai_client().chat.completions.create(**request)
        except ModuleNotFoundError as exc:
            # A broken install is NOT a model error, and is deliberately never
            # wrapped in AgentError. This is the older half of the contract:
            # GH-93 established it here (bedrock.py gained the matching branch
            # later, for parity). Read bedrock.py's ModuleNotFoundError branch
            # for the full "why not AgentError(UPSTREAM, ...)" rationale —
            # short version: UPSTREAM means "vendor failed, retry", a missing
            # module is a permanent local defect where retry is guaranteed
            # waste, and GH-93 already catches the real case at BOOT
            # (build_app() raises ImportError("agent-sdk[openai]")), so
            # reaching this line means the process cannot serve any request.
            # The log line is what carries the actionable hint: runner.py's
            # catch-all around run_loop has no logger of its own, so this is
            # the last point the exception is still typed. str(exc) names a
            # module only (SI-2 safe).
            logger.error("openai model backend unavailable: %s", exc)
            raise
        except _openai.RateLimitError as exc:
            retry_after: int | None = None
            if exc.response is not None:
                raw_header = exc.response.headers.get("retry-after")
                if raw_header is not None:
                    try:
                        retry_after = int(raw_header)
                    except (ValueError, TypeError):
                        pass
            raise AgentError(
                ErrorCategory.RATE_LIMITED,
                "model rate limit exceeded; retry later",
                source="openai",
                detail={"retry_after": retry_after} if retry_after is not None else None,
            ) from exc
        except Exception as exc:
            # C-017 parity with BedrockModelClient._log_and_wrap_upstream_error:
            # bind the exception TYPE plus frame_locations() — never exc's
            # str/args, which can embed vendor-response detail (SI-2) — so the
            # failure stays diagnosable in server logs while the wire-facing
            # AgentError message stays generic. Without this the two model
            # clients had different diagnosability contracts.
            logger.error(
                "openai model invocation failed error_type=%s frames=%s",
                type(exc).__name__,
                frame_locations(exc),
            )
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
