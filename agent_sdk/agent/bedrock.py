"""BedrockModelClient — boto3 Converse on a dedicated bounded executor.

Model calls never share the default ``to_thread`` pool (they would starve
adapter I/O and health checks under load — DESIGN.md §8). Credential chain:
Bedrock API key → static IAM env vars → boto3 default chain. ARN and region
come purely from config.
"""

from __future__ import annotations

import asyncio
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..models.errors import AgentError, ErrorCategory
from .model_client import ModelResponse, ModelToolCall

_EXECUTOR_MAX_WORKERS = 8


class BedrockModelClient:
    def __init__(self, *, region: str, model_arn: str) -> None:
        if not model_arn:
            raise ValueError("BEDROCK_MODEL_ARN is required")
        self._region = region
        self._model_arn = model_arn
        self._client: Any = None
        self._executor = ThreadPoolExecutor(
            max_workers=_EXECUTOR_MAX_WORKERS, thread_name_prefix="bedrock"
        )

    def _boto_client(self) -> Any:
        if self._client is None:
            import boto3  # deferred: keeps import cheap for tests using FakeModelClient

            kwargs: dict[str, Any] = {"region_name": self._region}
            # Bedrock API key support: boto3 reads AWS_BEARER_TOKEN_BEDROCK natively.
            if not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
                pass  # fall through to IAM static / default chain
            self._client = boto3.client("bedrock-runtime", **kwargs)
        return self._client

    async def converse(
        self,
        *,
        system: str,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]],
        max_tokens: int = 4096,
    ) -> ModelResponse:
        request: dict[str, Any] = {
            "modelId": self._model_arn,
            "system": [{"text": system}],
            "messages": messages,
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if tools:
            request["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": t["name"],
                            "description": t.get("description", ""),
                            "inputSchema": {"json": t["input_schema"]},
                        }
                    }
                    for t in tools
                ]
            }
        loop = asyncio.get_running_loop()
        try:
            raw = await loop.run_in_executor(
                self._executor, lambda: self._boto_client().converse(**request)
            )
        except Exception as exc:  # boto errors are dynamic classes
            raise AgentError(
                ErrorCategory.UPSTREAM, "model invocation failed", source="bedrock"
            ) from exc
        return self._parse(raw)

    @staticmethod
    def _parse(raw: dict[str, Any]) -> ModelResponse:
        out = ModelResponse(stop_reason=raw.get("stopReason", "end_turn"))
        usage = raw.get("usage", {})
        out.input_tokens = usage.get("inputTokens", 0)
        out.output_tokens = usage.get("outputTokens", 0)
        content = raw.get("output", {}).get("message", {}).get("content", [])
        for block in content:
            if "text" in block:
                out.text_segments.append(block["text"])
            elif "toolUse" in block:
                tu = block["toolUse"]
                out.tool_calls.append(
                    ModelToolCall(
                        tool_call_id=tu["toolUseId"],
                        name=tu["name"],
                        arguments=tu.get("input", {}) or {},
                    )
                )
        return out

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
