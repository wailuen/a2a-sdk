"""BedrockModelClient — boto3 Converse on a dedicated bounded executor.

Model calls never share the default ``to_thread`` pool (they would starve
adapter I/O and health checks under load — DESIGN.md §8).

Credential resolution (NS_BEDROCK in the encrypted credential store):
  - ``bearer_token`` — scoped to a per-client botocore session; never written
    to ``os.environ`` (SI-6).  When present, static IAM kwargs are excluded
    from the boto3 call so auth mode is unambiguous.  Client construction
    passes dummy static credentials to prevent botocore from resolving the
    host's ambient AWS profile chain (~/.aws/config, SSO/login sessions,
    credential_process, ...); bearer auth depends on the token alone (RT-011).
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
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from ..common.redact import frame_locations
from ..models.errors import AgentError, ErrorCategory
from .model_client import ModelResponse, ModelToolCall

logger = logging.getLogger(__name__)

_EXECUTOR_MAX_WORKERS = 8
# botocore ClientError codes that mean "retry later", not a fatal upstream
# failure (RT-010/GH-94 parity — see openai_client.py's RateLimitError clause).
_RATE_LIMIT_ERROR_CODES = frozenset(
    {"ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException"}
)
_BEARER_AUTH_UNSUPPORTED_MSG = (
    "Bedrock bearer-token auth requires botocore>=1.39; "
    "upgrade boto3>=1.39 in your project dependencies."
)
_BEARER_SIGNER_UNRESOLVED_MSG = (
    "Bedrock bearer-token auth: this botocore build has no 'bearer' signer "
    "registered in botocore.auth.AUTH_TYPE_MAPS, so "
    "Config(signature_version='bearer') would fail at first call with "
    "UnknownSignatureVersionError. Pin a botocore version known to implement "
    "the bearer signer."
)
_BEARER_CLIENT_CONSTRUCTION_FAILED_MSG = (
    "Bedrock bearer-token auth: failed to construct the boto3 client. "
    "Bearer-token auth is scoped to the token alone and must not depend on "
    "the host's ambient AWS profile/credential chain (~/.aws/config, "
    "AWS_PROFILE, SSO/login sessions, credential_process, etc.) — check "
    "whether an ambient profile is interfering."
)


class BedrockBearerSetupError(RuntimeError):
    """Bearer-auth setup diagnostic raised by `_boto_client()`.

    Message is always one of the SDK-authored `_BEARER_*_MSG` constants above
    — no caller/vendor data — so `_log_and_wrap_upstream_error` logs it
    verbatim (SI-2-safe) instead of dropping it behind the generic
    "model invocation failed" AgentError (RT-009).
    """


# Dummy static credentials (RT-011): pre-seeded directly on the botocore
# session (Session.set_credentials) only to short-circuit
# Session.create_client()'s unconditional `credentials = self.get_credentials()`
# call in its no-explicit-creds branch — get_credentials() returns
# self._credentials immediately once it is non-None, never reaching
# self._components.get_component('credential_provider').load_credentials(),
# which is what walks the host's ambient AWS profile chain and can raise
# arbitrary vendor exceptions unrelated to the bearer token. Reproduced via a
# `login_session` profile with no botocore[crt] installed, which raised
# MissingDependencyException before the bearer signer was ever consulted.
# Bearer auth signs exclusively through the token_provider registered below;
# these dummy values are never read by the bearer signer (verified:
# RequestSigner resolves signature_version='bearer' from the explicit Config
# regardless of what credentials, if any, are attached to the session) and
# are never passed as boto3.client() kwargs, so they cannot be confused with
# real static IAM credentials (RT-006).
_BEARER_DUMMY_STATIC_CREDENTIAL = ""


def _log_and_wrap_upstream_error(exc: Exception) -> AgentError:
    # RT-002/LRN-044: bind + log the exception TYPE plus frame_locations()
    # (never exc's str/args — SI-2, can embed vendor-response detail; frame
    # filename/lineno only, never `.line` source text) so any boto/botocore
    # failure stays diagnosable via server logs even though the wire-facing
    # AgentError message stays generic (C-017 parity contract).
    #
    # RT-009: BedrockBearerSetupError is the one exception class exempted
    # from that str-omission rule — its message is always one of the
    # SDK-authored `_BEARER_*_MSG` constants (no caller/vendor data), and
    # without logging it here the actionable install/upgrade hint never
    # reaches any log sink or wire response (runner.py has no logger of its
    # own around the run_loop catch-all).
    if isinstance(exc, BedrockBearerSetupError):
        logger.error(
            "bedrock model invocation failed error_type=%s frames=%s detail=%s",
            type(exc).__name__,
            frame_locations(exc),
            str(exc),
        )
    else:
        logger.error(
            "bedrock model invocation failed error_type=%s frames=%s",
            type(exc).__name__,
            frame_locations(exc),
        )
    return AgentError(ErrorCategory.UPSTREAM, "model invocation failed", source="bedrock")


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
            import botocore.auth
            import botocore.client
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
                    raise BedrockBearerSetupError(_BEARER_AUTH_UNSUPPORTED_MSG)
                # LRN-084/RT-013/RT-005: Config(signature_version="bearer") is a
                # request, not a guarantee — a botocore build past the version
                # floor that ignored or renamed the bearer signer would construct
                # cleanly and fail only at first call (the GH-139 symptom,
                # re-armed). AUTH_TYPE_MAPS is the registry botocore itself
                # consults in RequestSigner.get_auth_instance(), which raises
                # UnknownSignatureVersionError on a miss — so probing it here is
                # the same question, asked at construction time where the error
                # is actionable. (An earlier revision instead read back
                # built_client.meta.config.signature_version, which is just the
                # value set two lines above: botocore echoes ANY string back
                # verbatim and performs no signer resolution at construction, so
                # that branch could never fire.)
                if "bearer" not in botocore.auth.AUTH_TYPE_MAPS:
                    raise BedrockBearerSetupError(_BEARER_SIGNER_UNRESOLVED_MSG)
                # Minimal single-key dict — never copies the full process env (SI-6).
                bcore_session = botocore.session.Session()
                isolated_env = {"AWS_BEARER_TOKEN_BEDROCK": self._bearer_token}
                token_provider = botocore.tokens.TokenProviderChain(
                    providers=[
                        botocore.tokens.ScopedEnvTokenProvider(bcore_session, environ=isolated_env),
                    ]
                )
                bcore_session.register_component("token_provider", token_provider)
                # RT-011: pre-seed dummy session credentials so
                # Session.get_credentials() short-circuits on self._credentials
                # instead of walking the host's ambient AWS profile chain —
                # see _BEARER_DUMMY_STATIC_CREDENTIAL above.
                bcore_session.set_credentials(
                    _BEARER_DUMMY_STATIC_CREDENTIAL, _BEARER_DUMMY_STATIC_CREDENTIAL
                )
                boto_session = boto3.Session(botocore_session=bcore_session)
                # botocore's env-var-based bearer-auth gate
                # (_should_prefer_bearer_auth) reads the REAL os.environ, not
                # our isolated per-client dict, so it never fires here.
                # Setting signature_version explicitly resolves to 'bearer'
                # directly, independent of that gate, while the token_provider
                # above still supplies the token at signing time.
                kwargs["config"] = botocore.client.Config(signature_version="bearer")
                try:
                    self._client = boto_session.client("bedrock-runtime", **kwargs)
                except ModuleNotFoundError:
                    # LRN-104 Layer 3: a missing optional botocore extra (e.g.
                    # botocore[crt]) must surface as an install hint, not be
                    # relabelled as an ambient-profile misconfiguration.
                    raise
                except Exception as exc:
                    raise BedrockBearerSetupError(_BEARER_CLIENT_CONSTRUCTION_FAILED_MSG) from exc
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
            # Deferred import INSIDE the try: when the optional boto3/botocore
            # extra is not installed, this line is what raises, so leaving it
            # above the try made the ModuleNotFoundError branch below
            # unreachable in exactly the case it exists for. `botocore` is only
            # dereferenced by the ClientError clause, which Python never
            # evaluates when the earlier ModuleNotFoundError clause matches.
            import botocore.exceptions
            raw = await loop.run_in_executor(
                self._executor, lambda: self._boto_client().converse(**request)
            )
        except ModuleNotFoundError as exc:
            # A broken install is NOT a model error. It must not be dressed as
            # one — this is the deliberate contract, not an oversight; see the
            # "why not AgentError" note below before changing it.
            #
            # LRN-104 Layer 3: a missing package must surface as an install
            # hint. A bare re-raise alone does not achieve that, because
            # runner.py's catch-all around run_loop has no logger of its own,
            # so log it HERE, at the last point the exception is still typed.
            # str(exc) is safe for an import error: it names a module, never
            # request content (SI-2).
            #
            # Why not wrap this in AgentError(UPSTREAM, ...) like every other
            # failure below — the question this branch attracts on every review
            # pass, answered here so it stays answered:
            #   1. It is not upstream. UPSTREAM means "the vendor failed";
            #      consumers read it as transient and retry. A missing module
            #      is a permanent local deployment defect, and every retry
            #      against it is guaranteed waste. Mislabelling it would be a
            #      worse contract than declining to label it at all.
            #   2. It is not per-request. GH-93 catches this at BOOT —
            #      build_app() raises ImportError("agent-sdk[openai]") for the
            #      openai backend, and boto3/botocore are core deps
            #      (pyproject.toml "boto3>=1.39"), so reaching this line at all
            #      means the process is running on an install that can never
            #      serve a request. Terminating the task as an internal error
            #      is the honest outcome; "model backend unavailable" on the
            #      wire would only tell an end user about our deployment.
            #   3. It stays distinguishable. The whole point of this dedicated
            #      branch (vs. the generic `except Exception` below) is that a
            #      missing package never becomes indistinguishable from a
            #      vendor outage — in the logs OR in the exception type an
            #      operator sees. Wrapping it re-merges the two.
            # openai_client.py carries the identical branch and the identical
            # reasoning; the two are deliberate parity, not copy-paste.
            logger.error("bedrock model backend unavailable: %s", exc)
            raise
        except botocore.exceptions.ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in _RATE_LIMIT_ERROR_CODES:
                raise AgentError(
                    ErrorCategory.RATE_LIMITED,
                    "model rate limit exceeded; retry later",
                    source="bedrock",
                ) from exc
            raise _log_and_wrap_upstream_error(exc) from exc
        except Exception as exc:  # boto errors are dynamic classes
            raise _log_and_wrap_upstream_error(exc) from exc
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
