"""BedrockModelClient — boto3 Converse on a dedicated bounded executor.

Model calls never share the default ``to_thread`` pool (they would starve
adapter I/O and health checks under load — DESIGN.md §8).

Credential resolution (NS_BEDROCK in the encrypted credential store):
  - ``bearer_token`` — scoped to a per-client botocore session; never written
    to ``os.environ`` (SI-6).  When present, static IAM kwargs are excluded
    from the boto3 call so auth mode is unambiguous.
  - ``aws_access_key_id`` / ``aws_secret_access_key`` — forwarded as boto3
    constructor kwargs; only used when bearer_token is absent.
  - ``aws_session_token`` — forwarded alongside the access/secret keys when
    present (required for STS / temporary credentials; long-lived IAM keys
    omit it).  Only used when bearer_token is absent.
  - Absence of all falls through to the boto3 default chain
    (env vars / instance-profile IAM role).

ARN and region come purely from config.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..models.errors import AgentError, ErrorCategory
from .model_client import ModelResponse, ModelToolCall

_EXECUTOR_MAX_WORKERS = 8


class BedrockModelClient:
    def __init__(
        self,
        *,
        region: str,
        model_arn: str,
        bearer_token: str | None = None,
        aws_access_key_id: str | None = None,
        aws_secret_access_key: str | None = None,
        aws_session_token: str | None = None,
    ) -> None:
        if not model_arn:
            raise ValueError("BEDROCK_MODEL_ARN is required")
        self._region = region
        self._model_arn = model_arn
        self._bearer_token = bearer_token
        self._aws_access_key_id = aws_access_key_id
        self._aws_secret_access_key = aws_secret_access_key
        self._aws_session_token = aws_session_token
        self._client: Any = None
        self._client_lock = threading.Lock()
        self._executor = ThreadPoolExecutor(
            max_workers=_EXECUTOR_MAX_WORKERS, thread_name_prefix="bedrock"
        )

    def _boto_client(self) -> Any:
        if self._client is not None:
            return self._client
        with self._client_lock:
            if self._client is not None:
                return self._client
            import boto3  # deferred: keeps import cheap for tests using FakeModelClient
            import botocore.session
            import botocore.tokens

            kwargs: dict[str, Any] = {"region_name": self._region}

            if self._bearer_token:
                _missing = [
                    name
                    for name in ("ScopedEnvTokenProvider", "TokenProviderChain")
                    if not getattr(botocore.tokens, name, None)
                ]
                if _missing:
                    raise RuntimeError(
                        "Bedrock bearer-token auth requires botocore>=1.39; "
                        "upgrade boto3>=1.39 in your project dependencies."
                    )
                # Minimal single-key dict — never copies the full process env (SI-6).
                bcore_session = botocore.session.Session()
                isolated_env = {"AWS_BEARER_TOKEN_BEDROCK": self._bearer_token}
                token_provider = botocore.tokens.TokenProviderChain(
                    providers=[
                        botocore.tokens.ScopedEnvTokenProvider(bcore_session, environ=isolated_env),
                    ]
                )
                bcore_session.register_component("token_provider", token_provider)
                boto_session = boto3.Session(botocore_session=bcore_session)
                self._client = boto_session.client("bedrock-runtime", **kwargs)
            else:
                if self._aws_access_key_id and self._aws_secret_access_key:
                    kwargs["aws_access_key_id"] = self._aws_access_key_id
                    kwargs["aws_secret_access_key"] = self._aws_secret_access_key
                    # STS / temporary credentials authenticate only with the
                    # session token alongside the access/secret pair.
                    if self._aws_session_token:
                        kwargs["aws_session_token"] = self._aws_session_token
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
