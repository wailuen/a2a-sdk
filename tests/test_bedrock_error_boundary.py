"""bedrock.py converse() error-boundary findings.

RT-002: a bearer-setup RuntimeError raised deep inside _boto_client() must
leave a diagnosable trail (exception type + bedrock.py:line, SI-2-safe) in
the server logs when it reaches an operator THROUGH converse() — the only
surface every caller (loop.py/runner.py) actually exercises. A unit test
that calls _boto_client() directly proves nothing about that reachability,
so every test here drives through BedrockModelClient.converse().

RT-003: deferred boto3/botocore imports must not be silently caught by
converse()'s or _boto_client()'s broad `except Exception` handlers — a
missing package must propagate as ModuleNotFoundError, mirroring the
existing guard in openai_client.py (tests/test_gh93_openai_missing_package.py).

RT-010: a botocore ClientError carrying a throttling/quota code must map to
ErrorCategory.RATE_LIMITED, not UPSTREAM — mirroring openai_client.py's
RateLimitError clause (tests/test_gh94_rate_limit_error.py, GH-94).

RT-006 (redteam on RT-003): a bare `except ModuleNotFoundError: raise` alone
does not "surface as an install hint" (LRN-104 Layer 3) — loop.py catches
only AgentError around converse(), so the exception escapes into runner.py's
generic catch-all, which sets the task FAILED with a bare "internal error"
and has no logger of its own to record it. converse() must log the
exception (type + str — an import error names only a module, SI-2-safe)
before re-raising, at the last point it is still typed; a test asserting
propagation alone proves nothing about whether the hint is actually
diagnosable once it reaches an operator.

boto3/botocore are core (non-optional) dependencies (pyproject.toml
`"boto3>=1.39"`), so tests use the REAL installed botocore.exceptions.ClientError
class directly rather than a hand-written fake exception hierarchy.
"""

from __future__ import annotations

import logging
from typing import Any

import botocore.exceptions
import pytest
import pytest_asyncio  # noqa: F401 — imported for plugin registration

from agent_sdk.agent.bedrock import BedrockModelClient
from agent_sdk.models.errors import AgentError, ErrorCategory

_CONVERSE_KWARGS: dict[str, Any] = {
    "system": "test",
    "messages": [{"role": "user", "content": [{"text": "hi"}]}],
    "tools": [],
}


def _make_client(**kwargs: Any) -> BedrockModelClient:
    defaults: dict[str, Any] = {
        "region": "us-east-1",
        "model_arn": "arn:aws:bedrock:us-east-1::foundation-model/test",
    }
    defaults.update(kwargs)
    return BedrockModelClient(**defaults)


class _FakeBotoClient:
    """Stand-in for the constructed boto3 client — raises on .converse()."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc

    def converse(self, **_kwargs: Any) -> Any:
        raise self._exc


def _patch_boto_client(monkeypatch: pytest.MonkeyPatch, client: BedrockModelClient, exc: Exception) -> None:
    """Make client._boto_client() return a fake client whose .converse() raises *exc*."""
    monkeypatch.setattr(client, "_boto_client", lambda: _FakeBotoClient(exc))


# ---------------------------------------------------------------------------
# RT-002: bearer-setup RuntimeError must be diagnosable via converse()'s logs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bearer_misconfiguration_reaches_operator_via_converse_logs(monkeypatch, sdk_caplog):
    """A RuntimeError raised inside _boto_client()'s bearer path must survive
    converse()'s wrapping AgentError(UPSTREAM, "model invocation failed") catch-all
    by leaving a type+frame diagnostic in the logs — not through _boto_client()
    called directly, which every prior GH-139 unit test exercised.

    Uses ``sdk_caplog`` (tests/conftest.py), not plain ``caplog``: once any
    test in the session builds an app, ``configure_logging()`` sets
    ``propagate = False`` on the ``agent_sdk`` root logger, so records from
    ``agent_sdk.agent.bedrock`` stop reaching the stdlib root logger that
    ``caplog`` attaches to.
    """
    import botocore.tokens

    monkeypatch.delattr(botocore.tokens, "ScopedEnvTokenProvider", raising=False)

    client = _make_client(bearer_token="tok-should-not-leak-in-logs")

    with sdk_caplog("agent_sdk.agent.bedrock", logging.ERROR) as records:
        with pytest.raises(AgentError) as ei:
            await client.converse(**_CONVERSE_KWARGS)

    err = ei.value
    # The wire-facing shape every consumer (loop.py/runner.py) reads is
    # unchanged by this fix — only .message, never __cause__, reaches them.
    assert err.category == ErrorCategory.UPSTREAM
    assert err.message == "model invocation failed"
    assert isinstance(err.__cause__, RuntimeError)
    assert "botocore>=1.39" in str(err.__cause__)

    error_records = [r for r in records if r.levelname == "ERROR"]
    assert error_records, (
        "converse() must log the bearer-setup failure — without this, an "
        "operator sees only the generic 'model invocation failed' message "
        "with no way to find the actual (actionable) RuntimeError"
    )
    logged = error_records[-1].getMessage()
    assert "BedrockBearerSetupError" in logged, "log line must name the exception type"
    assert "bedrock.py" in logged, "log line must locate the raise site (frame_locations)"
    # RT-009: the three GH-139 bearer-setup diagnostics are SDK-authored
    # constants with no caller/vendor data — logging them is SI-2-safe, and
    # without this the actionable install/upgrade hint never reaches any log
    # sink (only __cause__, which no caller of converse() ever reads).
    assert "botocore>=1.39" in logged, "actionable hint must reach the log record itself, not only __cause__"
    # SI-2: the bearer token itself must never be interpolated into the log.
    assert "tok-should-not-leak-in-logs" not in logged


@pytest.mark.asyncio
async def test_generic_boto_failure_still_logs_diagnostic_via_converse(monkeypatch, sdk_caplog):
    """Parity check: a plain (non-RuntimeError) boto/botocore failure gets the
    same type+frame diagnostic treatment, not just the bearer-setup path.
    """
    client = _make_client()
    exc = ConnectionResetError("connection reset by peer")
    _patch_boto_client(monkeypatch, client, exc)

    with sdk_caplog("agent_sdk.agent.bedrock", logging.ERROR) as records:
        with pytest.raises(AgentError) as ei:
            await client.converse(**_CONVERSE_KWARGS)

    assert ei.value.category == ErrorCategory.UPSTREAM
    assert ei.value.message == "model invocation failed"

    error_records = [r for r in records if r.levelname == "ERROR"]
    assert error_records
    logged = error_records[-1].getMessage()
    assert "ConnectionResetError" in logged
    assert "bedrock.py" in logged


# ---------------------------------------------------------------------------
# RT-003: ModuleNotFoundError must not be swallowed by either broad catch-all
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_missing_boto3_propagates_through_converse(monkeypatch, sdk_caplog):
    """converse()'s except ModuleNotFoundError: raise guard must let a missing
    boto3/botocore package propagate unmodified — not become a generic
    AgentError(UPSTREAM, "model invocation failed") — AND (RT-006) must log
    the hint before re-raising: runner.py's catch-all around run_loop has no
    logger of its own, so a bare re-raise alone reaches the operator only as
    an opaque "internal error", discarding the actionable install hint that
    LRN-104 Layer 3 requires stay surfaced.
    """
    client = _make_client()

    def _raise_mnfe() -> Any:
        raise ModuleNotFoundError("No module named 'boto3'")

    monkeypatch.setattr(client, "_boto_client", _raise_mnfe)

    with sdk_caplog("agent_sdk.agent.bedrock", logging.ERROR) as records:
        with pytest.raises(ModuleNotFoundError):
            await client.converse(**_CONVERSE_KWARGS)

    error_records = [r for r in records if r.levelname == "ERROR"]
    assert error_records, (
        "converse() must log the ModuleNotFoundError before re-raising it — "
        "without this, runner.py's catch-all (no logger in that module) "
        "discards the install hint entirely, leaving only a bare "
        "'internal error' for the operator"
    )
    logged = error_records[-1].getMessage()
    assert "boto3" in logged, "log line must preserve the install hint (names the missing module)"
    assert "unavailable" in logged


def test_missing_module_during_bearer_client_construction_propagates(monkeypatch):
    """_boto_client()'s own except ModuleNotFoundError: raise guard (around the
    boto_session.client() call in the bearer path) must not relabel a missing
    optional botocore extra as the generic ambient-profile-interference
    RuntimeError.
    """
    import boto3

    def _boom(self: Any, *args: Any, **kwargs: Any) -> Any:
        raise ModuleNotFoundError("No module named 'botocore_crt_fake'")

    monkeypatch.setattr(boto3.Session, "client", _boom)

    client = _make_client(bearer_token="tok-no-crt")

    with pytest.raises(ModuleNotFoundError, match="botocore_crt_fake"):
        client._boto_client()


# ---------------------------------------------------------------------------
# RT-010: botocore ClientError rate-limit codes map to ErrorCategory.RATE_LIMITED
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "code",
    ["ThrottlingException", "TooManyRequestsException", "ServiceQuotaExceededException"],
)
async def test_client_error_rate_limit_codes_map_to_rate_limited(monkeypatch, code):
    client = _make_client()
    exc = botocore.exceptions.ClientError(
        {"Error": {"Code": code, "Message": "boom"}}, "Converse"
    )
    _patch_boto_client(monkeypatch, client, exc)

    with pytest.raises(AgentError) as ei:
        await client.converse(**_CONVERSE_KWARGS)

    err = ei.value
    assert err.category == ErrorCategory.RATE_LIMITED
    assert err.message == "model rate limit exceeded; retry later"
    assert err.category != ErrorCategory.UPSTREAM


@pytest.mark.asyncio
async def test_client_error_non_rate_limit_code_stays_upstream(monkeypatch, sdk_caplog):
    """A ClientError with a non-throttling code (e.g. auth failure) must NOT be
    misreported as RATE_LIMITED — it stays UPSTREAM, same as before this fix,
    and still gets the type+frame diagnostic (RT-002 parity within the new
    ClientError branch itself).
    """
    client = _make_client()
    exc = botocore.exceptions.ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "denied"}}, "Converse"
    )
    _patch_boto_client(monkeypatch, client, exc)

    with sdk_caplog("agent_sdk.agent.bedrock", logging.ERROR) as records:
        with pytest.raises(AgentError) as ei:
            await client.converse(**_CONVERSE_KWARGS)

    err = ei.value
    assert err.category == ErrorCategory.UPSTREAM
    assert err.message == "model invocation failed"

    error_records = [r for r in records if r.levelname == "ERROR"]
    assert error_records
    logged = error_records[-1].getMessage()
    assert "ClientError" in logged
    assert "bedrock.py" in logged


@pytest.mark.asyncio
async def test_fatal_non_client_error_still_upstream(monkeypatch):
    """Non-ClientError exceptions still produce ErrorCategory.UPSTREAM (existing
    catch-all behaviour preserved)."""
    client = _make_client()
    exc = TimeoutError("boto3 read timeout")
    _patch_boto_client(monkeypatch, client, exc)

    with pytest.raises(AgentError) as ei:
        await client.converse(**_CONVERSE_KWARGS)

    assert ei.value.category == ErrorCategory.UPSTREAM
