"""RT-B-002 / RT-006: BedrockModelClient.converse's wire message stays fixed
and generic; the failing exception CLASS goes to the operator log only.

History: RT-B-002 made ``converse``'s catch-all interpolate
``type(exc).__name__`` into ``AgentError.message`` so an operator could tell
a credential failure from a throttle from a malformed request — the same
opacity that made GH-145's ``NoCredentialsError`` undiagnosable. But
``AgentError.message`` is not operator-only: ``run_loop`` turns it into
``DoneEvent(ok=False, error=...)``, which reaches the untrusted A2A caller
verbatim (runner.py folds it into both the wire ``WireError`` and the
user-facing ``Message``). RT-006 found that this disclosed the upstream model
provider and its exact auth/quota failure mode to every caller, with no
GH-145 AC requesting a wire-message change.

The fix keeps the diagnostic where it is actually useful — a
``logger.warning`` before the raise — and restores the fixed, generic wire
message (matching ``OpenAIModelClient``'s "model invocation failed", see
``openai_client.py``). SI-2: only ``type(exc).__name__`` is ever logged,
never ``str(exc)``, because botocore error strings can embed request ids,
ARNs and credential context.
"""

from __future__ import annotations

import asyncio
import logging
from unittest.mock import MagicMock, patch

import pytest

from agent_sdk.agent.bedrock import BedrockModelClient
from agent_sdk.models.errors import AgentError, ErrorCategory


class NoCredentialsError(Exception):
    """Stands in for botocore's dynamically-built exception class."""


SECRET_TOKEN = "bearer-tok-must-not-leak"
SECRET_DETAIL = (
    f"Unable to locate credentials; tried token {SECRET_TOKEN} "
    "for request-id 0123456789abcdef arn:aws:bedrock:us-east-1:123456789012:x"
)


def _client() -> BedrockModelClient:
    return BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        bearer_token=SECRET_TOKEN,
    )


def _converse_raising(exc: Exception) -> AgentError:
    client = _client()
    boto = MagicMock()
    boto.converse.side_effect = exc
    with patch.object(client, "_boto_client", return_value=boto):
        with pytest.raises(AgentError) as excinfo:
            asyncio.run(client.converse(system="s", messages=[], tools=[]))
    return excinfo.value


def test_converse_error_wire_message_is_fixed_and_generic():
    """The caller-visible message never names the upstream exception class."""
    err = _converse_raising(NoCredentialsError(SECRET_DETAIL))

    assert err.category is ErrorCategory.UPSTREAM
    assert err.source == "bedrock"
    assert err.message == "model invocation failed"
    assert "NoCredentialsError" not in err.message


def test_converse_error_wire_message_identical_across_failure_kinds():
    """Different upstream failures must not be distinguishable on the wire."""

    class ThrottlingException(Exception):
        pass

    creds = _converse_raising(NoCredentialsError("no creds"))
    throttle = _converse_raising(ThrottlingException("slow down"))

    assert creds.message == throttle.message == "model invocation failed"


def test_converse_error_never_leaks_exception_text():
    """SI-2: no token, request id, ARN or message body reaches the caller."""
    err = _converse_raising(NoCredentialsError(SECRET_DETAIL))

    assert SECRET_TOKEN not in err.message
    assert "request-id" not in err.message
    assert "0123456789abcdef" not in err.message
    assert "arn:aws:bedrock" not in err.message
    assert "Unable to locate credentials" not in err.message


def test_converse_error_chains_the_original_exception():
    """The raw exception stays available to logs via ``__cause__``."""
    original = NoCredentialsError(SECRET_DETAIL)
    err = _converse_raising(original)
    assert err.__cause__ is original


def test_converse_error_logs_the_exception_class_for_operators(caplog):
    """RT-006: the diagnostic that used to ride the wire now goes to the log."""
    with caplog.at_level(logging.WARNING, logger="agent_sdk.agent.bedrock"):
        _converse_raising(NoCredentialsError(SECRET_DETAIL))

    assert any("NoCredentialsError" in rec.message for rec in caplog.records)


def test_converse_error_log_never_leaks_exception_text(caplog):
    """SI-2 applies to the log line too: class name only, never str(exc)."""
    with caplog.at_level(logging.WARNING, logger="agent_sdk.agent.bedrock"):
        _converse_raising(NoCredentialsError(SECRET_DETAIL))

    logged = "\n".join(rec.message for rec in caplog.records)
    assert SECRET_TOKEN not in logged
    assert "request-id" not in logged
    assert "arn:aws:bedrock" not in logged
