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

Signer selection (GH-145): botocore's choose-signer handler chain
(``_set_auth_scheme_preference_signer`` / ``_should_prefer_bearer_auth`` in
``botocore.handlers``) decides bearer-vs-sigv4 by calling
``get_token_from_environment(signing_name)``, which reads the REAL process
``os.environ`` directly — it never consults the ``token_provider`` component
registered on the botocore session above. Since the bearer token is
deliberately never written to the real env (SI-6), that check always sees no
token and silently falls back to sigv4, which then fails with
``NoCredentialsError`` because no real IAM credentials exist in a
bearer-only deployment. The bearer branch below therefore pins
``config=Config(signature_version="bearer")`` explicitly on the boto3 client
so signer selection never depends on the real env var. Do not remove this in
a future simplification — without it, the env-var-sniffing path silently
comes back and bearer-only deployments break with a sigv4 credentials error.

Error mapping (RT-004/RT-010): ``converse()`` maps a botocore
``ClientError`` carrying a throttling/quota code (``ThrottlingException``,
``TooManyRequestsException``, ``ServiceQuotaExceededException`` — matched by
error CODE, never the dynamic exception class) to
``ErrorCategory.RATE_LIMITED``; every other upstream failure stays a fixed,
generic ``ErrorCategory.UPSTREAM`` (RT-006 — the wire message never names the
failing exception class), logged with the exception type plus
``frame_locations()`` (RT-002/LRN-044) so it stays diagnosable via server
logs. ``require_bearer_auth_botocore()`` is the
botocore>=1.39 floor check for bearer-token auth, called both eagerly from
``app.py``'s ``_build_model_client()`` at startup and again from
``_boto_client()`` as a hot-path fallback (LRN-104). The Layer-3 fallback
matters for exactly one path: a caller-constructed ``BedrockModelClient``
passed via ``Agent(model_client=...)``, which returns early from
``_build_model_client()`` (app.py) and so never runs the Layer-2 startup
probe. That failure is raised as ``BedrockBearerAuthUnsupported`` (a
``RuntimeError`` subclass); ``converse()`` catches THAT CLASS specifically —
never the ``RuntimeError`` base — ahead of its broad ``except Exception``,
logs the upgrade instruction at ``ERROR``, and re-raises unmasked rather than
folding it into the generic upstream ``AgentError``.

RT-005: both halves of that are load-bearing. The log is what actually
delivers the instruction — an escaping non-``AgentError`` is not handled by
``run_loop`` (loop.py catches only ``AgentError``) and lands in
``run_task_worker``'s generic handler, which logs the class name with no
message and no ``exc_info`` and returns the fixed literal "internal error",
so re-raising on its own surfaced the message nowhere. And the narrow catch
is what keeps every OTHER ``RuntimeError`` — boto3's, or the bounded
executor's "cannot schedule new futures after shutdown" after
``shutdown()`` — on the normal ``AgentError`` path instead of bypassing
``run_loop``.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Literal

from ..common.redact import frame_locations
from ..models.errors import AgentError, ErrorCategory
from .model_client import ModelResponse, ModelToolCall

logger = logging.getLogger(__name__)


def _has_tool_blocks(messages: list[dict[str, Any]]) -> bool:
    """Converse rejects a request carrying toolUse/toolResult blocks without toolConfig."""
    return any(
        isinstance(block, dict) and ("toolUse" in block or "toolResult" in block)
        for msg in messages
        if isinstance(msg, dict) and isinstance(msg.get("content"), list)
        for block in msg["content"]
    )

_EXECUTOR_MAX_WORKERS = 8
# botocore ClientError codes that mean "retry later", not a fatal upstream
# failure (RT-010/GH-94 parity — see openai_client.py's RateLimitError clause).
_RATE_LIMIT_ERROR_CODES = frozenset(
    {"ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException"}
)

_BEARER_AUTH_BOTOCORE_SYMBOLS = ("ScopedEnvTokenProvider", "TokenProviderChain")


class BedrockBearerAuthUnsupported(RuntimeError):
    """Bearer-token auth cannot proceed: either the installed botocore
    predates bearer-token support (LRN-104), it has no 'bearer' signer
    registered (RT-002), or client construction otherwise failed in a way
    that must not be mistaken for an ambient-profile-free build (RT-002
    defense in depth, see ``_boto_client()``).

    RT-005: a dedicated class, not a bare ``RuntimeError``, because
    ``converse()`` re-raises this ONE condition unmasked past its broad
    ``except Exception``. Catching the base class there was too wide — any
    unrelated ``RuntimeError`` from boto3 or from the bounded executor (e.g.
    ``ThreadPoolExecutor``'s "cannot schedule new futures after shutdown"
    after ``BedrockModelClient.shutdown()``) escaped as a non-``AgentError``
    too, bypassing ``run_loop``'s ``AgentError`` -> ``DoneEvent`` path and
    landing in ``run_task_worker``'s generic handler instead.

    Subclasses ``RuntimeError`` so any caller that already catches
    ``RuntimeError`` around ``require_bearer_auth_botocore()`` (app.py's
    startup probe) is unaffected.
    """


def require_bearer_auth_botocore() -> None:
    """Raise ``BedrockBearerAuthUnsupported`` with an upgrade hint if the
    installed botocore predates the Bedrock bearer-token auth support added in
    1.39 (LRN-104).

    Two callers, by design: ``app.py``'s ``_build_model_client()`` calls this
    eagerly (Layer 2) when a bearer_token is configured, so the upgrade
    instruction reaches the operator at startup instead of a generic 502 on
    the first real request. ``_boto_client()`` calls it again (Layer 3) as a
    hot-path fallback for a caller-constructed ``BedrockModelClient`` passed
    via ``Agent(model_client=...)`` — that path returns early from
    ``_build_model_client()`` and never runs the Layer-2 probe, so this is
    the only guard that ever fires for it. ``converse()`` LOGS this
    exception's message and then re-raises it unmasked (RT-A05/RT-005)
    instead of folding it into the generic upstream ``AgentError``.
    """
    import botocore.tokens

    missing = [
        name
        for name in _BEARER_AUTH_BOTOCORE_SYMBOLS
        if not getattr(botocore.tokens, name, None)
    ]
    if missing:
        raise BedrockBearerAuthUnsupported(
            "Bedrock bearer-token auth requires botocore>=1.39; "
            "upgrade boto3>=1.39 in your project dependencies."
        )


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
            import botocore.client
            import botocore.session
            import botocore.tokens

            kwargs: dict[str, Any] = {"region_name": self._region}

            if self._bearer_token:
                require_bearer_auth_botocore()
                import botocore.auth

                # RT-002 (debug round 6): `Config(signature_version="bearer")`
                # below is a REQUEST for a signer, not a guarantee that one
                # exists. botocore resolves that string against
                # `botocore.auth.AUTH_TYPE_MAPS` lazily, at REQUEST time — so a
                # botocore past the 1.39 floor that renamed or dropped the
                # bearer signer builds this client cleanly and then fails on
                # the first `converse()` with `UnknownSignatureVersionError`,
                # which `converse()`'s broad `except Exception` masks as the
                # generic "model invocation failed". `require_bearer_auth_
                # botocore()` cannot catch that: it only probes
                # `botocore.tokens` symbols, never the signer registry. Probe
                # the registry HERE, where the failure is still actionable.
                if "bearer" not in botocore.auth.AUTH_TYPE_MAPS:
                    raise BedrockBearerAuthUnsupported(
                        "the installed botocore build has no 'bearer' signer "
                        "registered in botocore.auth.AUTH_TYPE_MAPS, so "
                        "Config(signature_version='bearer') would fail at "
                        "first call with UnknownSignatureVersionError. Pin a "
                        "botocore version known to implement the bearer "
                        "signer."
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
                # RT-002 (debug round 6): botocore's `Session.create_client()`
                # calls `self.get_credentials()` UNCONDITIONALLY
                # (botocore/session.py), before any signer is consulted and
                # regardless of `signature_version="bearer"`. On a bearer-only
                # deployment that walk goes looking for SigV4 credentials the
                # deployment deliberately does not have, and resolves against
                # the HOST's ambient AWS configuration — ~/.aws/config,
                # AWS_PROFILE, SSO, `credential_process` — none of which this
                # client has any business reading (SI-6). It does not merely
                # return None: a provider in that chain can RAISE, and then
                # the bearer client is never constructed at all. Reproduced on
                # a stock botocore 1.43 host, where the login provider raises
                # `MissingDependencyException` ("requires botocore[crt]")
                # during `create_client` — surfaced to the caller as the
                # generic "model invocation failed" because `_boto_client()`
                # runs inside `converse()`'s broad `except Exception`.
                #
                # Pre-seeding static placeholder credentials makes
                # `get_credentials()` return immediately from the session's own
                # cache and never start the chain walk. The values are never
                # used to sign anything — the pinned bearer signer below owns
                # signing — so they are deliberately non-secret, fixed strings
                # rather than anything credential-shaped.
                bcore_session.set_credentials(
                    "bedrock-bearer-auth-unused", "bedrock-bearer-auth-unused"
                )
                boto_session = boto3.Session(botocore_session=bcore_session)
                # Pin the signer explicitly — botocore's choose-signer handler
                # otherwise reads the REAL os.environ for AWS_BEARER_TOKEN_BEDROCK
                # (see module docstring, GH-145), which SI-6 never sets.
                kwargs["config"] = botocore.client.Config(signature_version="bearer")
                try:
                    self._client = boto_session.client("bedrock-runtime", **kwargs)
                except ModuleNotFoundError:
                    # LRN-104 Layer 3: a missing optional botocore extra (e.g.
                    # botocore[crt]) must surface as an install hint, not be
                    # relabelled as an ambient-profile misconfiguration below.
                    raise
                except Exception as exc:
                    # RT-002: defense in depth. The pre-seeded credentials
                    # above prevent the KNOWN ambient-chain-walk failure, but
                    # that is not a guarantee for every botocore build. If
                    # construction still fails here, the raw vendor exception
                    # must not reach `converse()`'s broad `except Exception`,
                    # which would mask it as the generic "model invocation
                    # failed" with no actionable detail. SI-2: `exc` itself is
                    # never interpolated below — botocore construction
                    # failures can carry request ids or credential-process
                    # detail.
                    raise BedrockBearerAuthUnsupported(
                        "failed to construct the Bedrock bearer-token client; "
                        "bearer-token auth is scoped to the token alone and "
                        "must not depend on the host's ambient AWS profile or "
                        "credential chain (~/.aws/config, AWS_PROFILE, "
                        "SSO/login sessions, credential_process, etc.) — "
                        "check whether an ambient profile is interfering"
                    ) from exc
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
        tool_choice: Literal["auto", "none"] = "auto",
    ) -> ModelResponse:
        request: dict[str, Any] = {
            "modelId": self._model_arn,
            "system": [{"text": system}],
            "messages": messages,
            "inferenceConfig": {"maxTokens": max_tokens},
        }
        if tools and (tool_choice == "auto" or _has_tool_blocks(messages)):
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
            # LRN-104 Layer 3: a missing optional dependency (e.g. boto3 not
            # installed) must never be masked as a generic upstream failure.
            # A bare re-raise alone does not surface it as an install hint:
            # runner.py's catch-all around run_loop has no logger of its own,
            # so log it HERE, at the last point the exception is still typed.
            # str(exc) is safe for an import error: it names a module, never
            # request content (SI-2).
            logger.error("bedrock model backend unavailable: %s", exc)
            raise
        except BedrockBearerAuthUnsupported as exc:
            # RT-A05 / LRN-104 Layer 3: require_bearer_auth_botocore()'s
            # actionable "upgrade boto3>=1.39" message (raised from
            # _boto_client() above, which runs inside this try) must never be
            # masked as a generic upstream failure — same rule as
            # ModuleNotFoundError, same broad except below it would otherwise
            # fall into.
            #
            # RT-005: re-raising ALONE never delivered that. This exception is
            # not an AgentError, so run_loop (which catches only AgentError)
            # does not handle it; it reaches run_task_worker's generic
            # handler, which logs `type(exc).__name__` with no message and no
            # exc_info and maps the wire response to the fixed literal
            # "internal error". The upgrade instruction therefore reached
            # neither the log nor the wire. Log it HERE, at the only point
            # that still holds the message. SI-2 is satisfied: this string is
            # SDK-authored (see require_bearer_auth_botocore), never botocore
            # text, so it carries no request id, ARN or credential context.
            logger.error("bedrock bearer auth unsupported: %s", exc)
            raise
        except botocore.exceptions.ClientError as exc:
            # RT-004/RT-010/LRN-105: throttling/quota codes are distinguished
            # from every other failure so the caller gets a 429 + back-off
            # signal instead of a bare 502 (matches OpenAIModelClient's
            # RateLimitError handling, GH-94). Matched on the stable botocore
            # error CODE, never the dynamic exception class object — a code
            # string is not credential or request-payload text, so this stays
            # within SI-2.
            code = exc.response.get("Error", {}).get("Code", "")
            if code in _RATE_LIMIT_ERROR_CODES:
                raise AgentError(
                    ErrorCategory.RATE_LIMITED,
                    "model rate limit exceeded; retry later",
                    source="bedrock",
                ) from exc
            logger.error(
                "bedrock converse failed error_type=%s frames=%s",
                type(exc).__name__,
                frame_locations(exc),
            )
            raise AgentError(
                ErrorCategory.UPSTREAM,
                "model invocation failed",
                source="bedrock",
            ) from exc
        except Exception as exc:  # boto errors are dynamic classes
            # RT-006: run_loop turns AgentError.message into
            # DoneEvent(ok=False, error=...), which reaches the untrusted A2A
            # caller verbatim (runner.py folds it into both the WireError and
            # the user-facing Message) — nothing here reaches an operator log
            # by itself. The exception CLASS name (NoCredentialsError /
            # UnauthorizedException, distinguishing auth from validation
            # failures) is therefore kept out of the wire message and logged
            # instead, matching OpenAIModelClient's fixed "model invocation
            # failed" wire text (openai_client.py) — no upstream provider or
            # failure-mode fingerprint is disclosed to the caller.
            # RT-002/LRN-044: bind the exception TYPE plus frame_locations()
            # (never exc's str/args — SI-2, can embed vendor-response detail;
            # frame filename/lineno only, never `.line` source text) so any
            # boto/botocore failure stays diagnosable via server logs even
            # though the wire-facing AgentError message stays generic.
            logger.error(
                "bedrock converse failed error_type=%s frames=%s",
                type(exc).__name__,
                frame_locations(exc),
            )
            raise AgentError(
                ErrorCategory.UPSTREAM,
                "model invocation failed",
                source="bedrock",
            ) from exc
        response = self._parse(raw)
        if tool_choice == "none":
            response.tool_calls = []
        return response

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
