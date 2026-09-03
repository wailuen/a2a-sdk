"""RT-004: BedrockModelClient.converse folded every distinct upstream failure
into AgentError(UPSTREAM) -> 502, losing two things LRN-105 and LRN-104
already name:

1. A real Bedrock ThrottlingException must surface as RATE_LIMITED (429), not
   a bare 502, so the caller gets a back-off signal (matches
   OpenAIModelClient's RateLimitError handling in openai_client.py). The
   match is on the botocore error CODE (``exc.response["Error"]["Code"]``),
   never on the dynamic exception class object -- a bare Python exception
   that merely happens to be named ``ThrottlingException`` must NOT trigger
   this branch (see test_rtb002_bedrock_error_class_enrichment.py's
   ``test_converse_error_wire_message_identical_across_failure_kinds``, which
   pins that exact non-match).

2. ``_boto_client()`` (which raises an actionable RuntimeError when the
   installed botocore predates 1.39, i.e. lacks bearer-token auth support)
   runs inside converse()'s try/except, so that message was unreachable in
   production -- the operator only ever saw a generic 502 and
   ``error_type=RuntimeError`` in the log. LRN-104's Layer 2 (eager probe in
   build_app()) closes that gap: a bearer_token configured with too-old a
   botocore now fails fast at startup with the upgrade instruction, mirroring
   the ``import openai`` probe at app.py's ``_build_model_client()``.

Layer 3 (the hot-path fallback inside ``_boto_client()``) stays in place --
see test_bedrock_credential_store.py's
``test_boto_client_bearer_raises_clear_error_on_old_botocore`` -- because a
bearer_token can be configured via the admin API after the app has already
started, past the point the Layer 2 probe ran.
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock, patch

import pytest
from botocore.exceptions import ClientError

from agent_sdk.agent.bedrock import BedrockModelClient
from agent_sdk.models.errors import AgentError, ErrorCategory


def _client(**kwargs: object) -> BedrockModelClient:
    return BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        **kwargs,
    )


def _converse_raising(exc: Exception) -> AgentError:
    client = _client()
    boto = MagicMock()
    boto.converse.side_effect = exc
    with patch.object(client, "_boto_client", return_value=boto):
        with pytest.raises(AgentError) as excinfo:
            asyncio.run(client.converse(system="s", messages=[], tools=[]))
    return excinfo.value


# ── throttling -> RATE_LIMITED (matched by botocore error code) ─────────────

def test_converse_throttling_client_error_maps_to_rate_limited():
    err = _converse_raising(
        ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "Converse",
        )
    )

    assert err.category is ErrorCategory.RATE_LIMITED
    assert err.source == "bedrock"
    assert err.message == "model rate limit exceeded; retry later"


def test_converse_throttling_error_never_leaks_botocore_message_text():
    err = _converse_raising(
        ClientError(
            {"Error": {"Code": "ThrottlingException", "Message": "Rate exceeded"}},
            "Converse",
        )
    )

    assert "Rate exceeded" not in err.message
    assert "Converse" not in err.message


def test_converse_non_throttling_client_error_still_maps_to_upstream():
    err = _converse_raising(
        ClientError(
            {"Error": {"Code": "ValidationException", "Message": "bad request"}},
            "Converse",
        )
    )

    assert err.category is ErrorCategory.UPSTREAM
    assert err.message == "model invocation failed"


# ── LRN-104 Layer 3: missing optional dependency must never be masked ───────

def test_converse_module_not_found_error_propagates_unwrapped():
    client = _client()
    with patch.object(
        client,
        "_boto_client",
        side_effect=ModuleNotFoundError("No module named 'boto3'"),
    ):
        with pytest.raises(ModuleNotFoundError):
            asyncio.run(client.converse(system="s", messages=[], tools=[]))


# ── LRN-104 Layer 2: eager build_app() probe for the botocore>=1.39 floor ───

def test_build_model_client_raises_on_old_botocore_when_bearer_token_configured(
    tmp_path, monkeypatch
):
    import botocore.tokens

    from agent_sdk import BaseAgentSettings
    from agent_sdk.app import Agent
    from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore
    from agent_sdk.credentials.store import NS_BEDROCK

    monkeypatch.delattr(botocore.tokens, "ScopedEnvTokenProvider", raising=False)

    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        BEDROCK_MODEL_ARN="arn:aws:bedrock:us-east-1::foundation-model/test",
    )

    master_key = "test-master-key-padded-to-32-chars!!"
    store_path = tmp_path / "data" / "credentials.db"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store = EncryptedSqliteStore(store_path, master_key)
    store.set(NS_BEDROCK, "bearer_token", "tok-old-botocore")
    store.close()

    store2 = EncryptedSqliteStore(store_path, master_key)
    try:
        agent = Agent(settings=settings, persona="Test agent.")
        with pytest.raises(RuntimeError, match="botocore>=1.39"):
            agent._build_model_client(store2)
    finally:
        store2.close()


def test_build_model_client_does_not_probe_botocore_without_bearer_token(
    tmp_path, monkeypatch
):
    """Static IAM creds (no bearer_token) must never trip the bearer-only
    botocore floor check -- confirms the Layer 2 probe is gated correctly."""
    import botocore.tokens

    from agent_sdk import BaseAgentSettings
    from agent_sdk.app import Agent
    from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore
    from agent_sdk.credentials.store import NS_BEDROCK

    monkeypatch.delattr(botocore.tokens, "ScopedEnvTokenProvider", raising=False)

    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        BEDROCK_MODEL_ARN="arn:aws:bedrock:us-east-1::foundation-model/test",
    )

    master_key = "test-master-key-padded-to-32-chars!!"
    store_path = tmp_path / "data" / "credentials.db"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store = EncryptedSqliteStore(store_path, master_key)
    store.set(NS_BEDROCK, "aws_access_key_id", "AKIAIOSFODNN7EXAMPLE")
    store.set(NS_BEDROCK, "aws_secret_access_key", "secret")
    store.close()

    store2 = EncryptedSqliteStore(store_path, master_key)
    try:
        agent = Agent(settings=settings, persona="Test agent.")
        mc = agent._build_model_client(store2)
        assert isinstance(mc, BedrockModelClient)
    finally:
        store2.close()
