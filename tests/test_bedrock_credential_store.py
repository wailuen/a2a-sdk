"""GH#72 — BedrockModelClient reads credentials from the store, not just env vars.

RED→GREEN test:
- BedrockModelClient accepts bearer_token / aws_access_key_id / aws_secret_access_key kwargs
- _boto_client() does NOT mutate os.environ — bearer token scoped to botocore session only (SI-6)
- _build_model_client() reads NS_BEDROCK fields and passes them to BedrockModelClient
- SI-6: AWS_BEARER_TOKEN_BEDROCK must never land in os.environ during or after client build
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from agent_sdk.agent.bedrock import BedrockModelClient


# ── unit: BedrockModelClient accepts credential kwargs ──────────────────────

def test_bedrock_client_accepts_bearer_token_kwarg():
    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        bearer_token="tok-from-store",
    )
    assert client._bearer_token == "tok-from-store"


def test_bedrock_client_accepts_static_iam_kwargs():
    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
        aws_secret_access_key="secret",
    )
    assert client._aws_access_key_id == "AKIAIOSFODNN7EXAMPLE"
    assert client._aws_secret_access_key == "secret"


def test_boto_client_does_not_mutate_os_environ(monkeypatch):
    """Bearer token from store must NOT be written to the shared os.environ (SI-6).

    The token must be scoped to a per-client botocore session, never to the
    global process environment where it would be inherited by subprocesses.
    """
    import botocore.session
    import botocore.tokens

    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    captured_envs: list[dict] = []

    real_ScopedEnvTokenProvider = botocore.tokens.ScopedEnvTokenProvider

    def capturing_provider(session, environ=None):
        captured_envs.append(environ if environ is not None else os.environ)
        return real_ScopedEnvTokenProvider(session, environ=environ)

    fake_boto3 = MagicMock()
    fake_boto3.Session.return_value.client.return_value = MagicMock()

    monkeypatch.setattr(botocore.tokens, "ScopedEnvTokenProvider", capturing_provider)

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        bearer_token="tok-from-store",
    )

    with patch.dict("sys.modules", {"boto3": fake_boto3}):
        client._boto_client()

    # The token must never appear in the shared process environment.
    assert "AWS_BEARER_TOKEN_BEDROCK" not in os.environ

    # The isolated env dict passed to ScopedEnvTokenProvider must contain the token,
    # but this must NOT be os.environ itself (it is a copy with the token added).
    assert len(captured_envs) == 1, "ScopedEnvTokenProvider must be called exactly once"
    isolated_env = captured_envs[0]
    assert isolated_env.get("AWS_BEARER_TOKEN_BEDROCK") == "tok-from-store"
    assert isolated_env is not os.environ


def test_boto_client_bearer_env_is_minimal_dict(monkeypatch):
    """isolated_env passed to ScopedEnvTokenProvider must contain ONLY the bearer
    token key — not a full os.environ copy — to minimise the credential-leak surface
    (RT-002 / SI-6 hardening).
    """
    import botocore.session
    import botocore.tokens

    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    captured_envs: list[dict] = []

    real_ScopedEnvTokenProvider = botocore.tokens.ScopedEnvTokenProvider

    def capturing_provider(session, environ=None):
        captured_envs.append(environ if environ is not None else os.environ)
        return real_ScopedEnvTokenProvider(session, environ=environ)

    fake_boto3 = MagicMock()
    fake_boto3.Session.return_value.client.return_value = MagicMock()

    monkeypatch.setattr(botocore.tokens, "ScopedEnvTokenProvider", capturing_provider)

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        bearer_token="tok-minimal",
    )

    with patch.dict("sys.modules", {"boto3": fake_boto3}):
        client._boto_client()

    assert len(captured_envs) == 1
    isolated_env = captured_envs[0]
    assert isolated_env == {"AWS_BEARER_TOKEN_BEDROCK": "tok-minimal"}


def test_boto_client_bearer_drops_static_iam_kwargs(monkeypatch):
    """RT-006: when both bearer_token and static IAM creds are present, the IAM
    creds must NOT be forwarded to the boto3 session client.  Bearer is the
    active auth mode; leaking IAM kwargs into the same call is an ambiguous
    dual-auth configuration that misleads operators.
    """
    import botocore.session
    import botocore.tokens

    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    captured_session_client_kwargs: dict = {}

    real_ScopedEnvTokenProvider = botocore.tokens.ScopedEnvTokenProvider

    def passthrough_provider(session, environ=None):
        return real_ScopedEnvTokenProvider(session, environ=environ)

    monkeypatch.setattr(botocore.tokens, "ScopedEnvTokenProvider", passthrough_provider)

    fake_boto3 = MagicMock()

    def _fake_session_client(name, **kwargs):
        captured_session_client_kwargs.update(kwargs)
        return MagicMock()

    fake_boto3.Session.return_value.client.side_effect = _fake_session_client

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        bearer_token="tok-bearer",
        aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
        aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )

    with patch.dict("sys.modules", {"boto3": fake_boto3}):
        client._boto_client()

    assert "aws_access_key_id" not in captured_session_client_kwargs, (
        "Static IAM key must not be passed when bearer_token is active"
    )
    assert "aws_secret_access_key" not in captured_session_client_kwargs, (
        "Static IAM secret must not be passed when bearer_token is active"
    )


def test_boto_client_static_iam_passed_as_kwargs(monkeypatch):
    """Static IAM credentials from store are forwarded to boto3.client as kwargs."""
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    captured: dict = {}
    fake_boto3 = MagicMock()

    def _fake_client(name, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    fake_boto3.client.side_effect = _fake_client

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
        aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )

    with patch.dict("sys.modules", {"boto3": fake_boto3}):
        client._boto_client()

    assert captured.get("aws_access_key_id") == "AKIAIOSFODNN7EXAMPLE"
    assert captured.get("aws_secret_access_key") == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"


def test_bedrock_client_accepts_session_token_kwarg():
    """RT-002 (debug r4): STS temporary credentials require aws_session_token."""
    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        aws_access_key_id="ASIAIOSFODNN7EXAMPLE",
        aws_secret_access_key="secret",
        aws_session_token="FwoGZXIvYXdz...session",
    )
    assert client._aws_session_token == "FwoGZXIvYXdz...session"


def test_boto_client_static_iam_with_session_token_forwarded(monkeypatch):
    """RT-002 (debug r4): aws_session_token must reach boto3.client alongside the
    access/secret pair, or STS / temporary credentials silently fail to authenticate.
    """
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    captured: dict = {}
    fake_boto3 = MagicMock()

    def _fake_client(name, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    fake_boto3.client.side_effect = _fake_client

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        aws_access_key_id="ASIAIOSFODNN7EXAMPLE",
        aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        aws_session_token="FwoGZXIvYXdzEXAMPLEsessiontoken",
    )

    with patch.dict("sys.modules", {"boto3": fake_boto3}):
        client._boto_client()

    assert captured.get("aws_access_key_id") == "ASIAIOSFODNN7EXAMPLE"
    assert captured.get("aws_secret_access_key") == "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    assert captured.get("aws_session_token") == "FwoGZXIvYXdzEXAMPLEsessiontoken", (
        "aws_session_token must be forwarded for STS / temporary credentials"
    )


def test_boto_client_session_token_omitted_when_absent(monkeypatch):
    """Long-lived IAM keys (no session token): aws_session_token must NOT appear
    in the boto3.client kwargs — passing an empty/None token breaks signing.
    """
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    captured: dict = {}
    fake_boto3 = MagicMock()

    def _fake_client(name, **kwargs):
        captured.update(kwargs)
        return MagicMock()

    fake_boto3.client.side_effect = _fake_client

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        aws_access_key_id="AKIAIOSFODNN7EXAMPLE",
        aws_secret_access_key="wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
    )

    with patch.dict("sys.modules", {"boto3": fake_boto3}):
        client._boto_client()

    assert "aws_session_token" not in captured


def test_build_model_client_reads_ns_bedrock_session_token(tmp_path):
    """RT-002 (debug r4): NS_BEDROCK aws_session_token must reach BedrockModelClient."""
    from agent_sdk import BaseAgentSettings
    from agent_sdk.app import Agent
    from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore
    from agent_sdk.credentials.store import NS_BEDROCK

    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        BEDROCK_MODEL_ARN="arn:aws:bedrock:us-east-1::foundation-model/test",
    )

    _MK = "test-master-key-padded-to-32-chars!!"
    store_path = tmp_path / "data" / "credentials.db"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store = EncryptedSqliteStore(store_path, _MK)
    store.set(NS_BEDROCK, "aws_access_key_id", "ASIAIOSFODNN7EXAMPLE")
    store.set(NS_BEDROCK, "aws_secret_access_key", "wJalrXUtnFEMI/K7MDENG")
    store.set(NS_BEDROCK, "aws_session_token", "FwoGZXIvYXdzEXAMPLE")
    store.close()

    store2 = EncryptedSqliteStore(store_path, _MK)
    try:
        agent = Agent(settings=settings, persona="Test agent.")
        mc = agent._build_model_client(store2)
        assert isinstance(mc, BedrockModelClient)
        assert mc._aws_session_token == "FwoGZXIvYXdzEXAMPLE"
    finally:
        store2.close()


def test_boto_client_no_store_creds_no_env_falls_through(monkeypatch):
    """No store creds + no env var: boto3 called without extra kwargs (IAM chain)."""
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    fake_boto3 = MagicMock()
    fake_boto3.client.return_value = MagicMock()

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
    )

    with patch.dict("sys.modules", {"boto3": fake_boto3}):
        client._boto_client()

    call_kwargs = fake_boto3.client.call_args[1]
    assert "aws_access_key_id" not in call_kwargs
    assert "aws_secret_access_key" not in call_kwargs


# ── integration: _build_model_client reads NS_BEDROCK from store ─────────────

def test_build_model_client_reads_ns_bedrock_bearer_token(tmp_path):
    """NS_BEDROCK bearer_token in the store must be forwarded to BedrockModelClient."""
    from agent_sdk import BaseAgentSettings
    from agent_sdk.app import Agent
    from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore
    from agent_sdk.credentials.store import NS_BEDROCK

    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        BEDROCK_MODEL_ARN="arn:aws:bedrock:us-east-1::foundation-model/test",
    )

    _MK = "test-master-key-padded-to-32-chars!!"
    store_path = tmp_path / "data" / "credentials.db"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store = EncryptedSqliteStore(store_path, _MK)
    store.set(NS_BEDROCK, "bearer_token", "tok-from-store-integration")
    store.close()

    # Re-open same DB as the agent would
    store2 = EncryptedSqliteStore(store_path, _MK)
    try:
        agent = Agent(settings=settings, persona="Test agent.")
        mc = agent._build_model_client(store2)
        assert isinstance(mc, BedrockModelClient)
        assert mc._bearer_token == "tok-from-store-integration"
    finally:
        store2.close()


def test_build_model_client_reads_ns_bedrock_static_iam(tmp_path):
    """NS_BEDROCK aws_access_key_id + aws_secret_access_key must reach BedrockModelClient."""
    from agent_sdk import BaseAgentSettings
    from agent_sdk.app import Agent
    from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore
    from agent_sdk.credentials.store import NS_BEDROCK

    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        BEDROCK_MODEL_ARN="arn:aws:bedrock:us-east-1::foundation-model/test",
    )

    _MK = "test-master-key-padded-to-32-chars!!"
    store_path = tmp_path / "data" / "credentials.db"
    store_path.parent.mkdir(parents=True, exist_ok=True)
    store = EncryptedSqliteStore(store_path, _MK)
    store.set(NS_BEDROCK, "aws_access_key_id", "AKIAIOSFODNN7EXAMPLE")
    store.set(NS_BEDROCK, "aws_secret_access_key", "wJalrXUtnFEMI/K7MDENG")
    store.close()

    store2 = EncryptedSqliteStore(store_path, _MK)
    try:
        agent = Agent(settings=settings, persona="Test agent.")
        mc = agent._build_model_client(store2)
        assert isinstance(mc, BedrockModelClient)
        assert mc._aws_access_key_id == "AKIAIOSFODNN7EXAMPLE"
        assert mc._aws_secret_access_key == "wJalrXUtnFEMI/K7MDENG"
    finally:
        store2.close()


# ── RT-001: lazy-init lock — boto3.client built exactly once under concurrency ─

def test_boto_client_constructed_exactly_once_under_concurrency(monkeypatch):
    """Concurrent converse() calls must build the boto3 client exactly once.

    Without a lock, N concurrent first-callers all see self._client is None
    and each construct a separate client (last write wins, wasted construction).
    This test asserts the lock prevents that.
    """
    import threading

    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    call_count = 0
    lock = threading.Lock()

    def _fake_boto3_client(name, **kwargs):
        nonlocal call_count
        with lock:
            call_count += 1
        return MagicMock()

    fake_boto3 = MagicMock()
    fake_boto3.client.side_effect = _fake_boto3_client

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
    )

    barrier = threading.Barrier(8)
    errors: list[Exception] = []

    def _call():
        try:
            barrier.wait()
            with patch.dict("sys.modules", {"boto3": fake_boto3}):
                client._boto_client()
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=_call) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Unexpected errors: {errors}"
    assert call_count == 1, (
        f"boto3.client was constructed {call_count} times; expected exactly 1"
    )


# ── RT-002: pin signing_name → env-var-name contract ────────────────────────

def test_scoped_env_token_provider_resolves_bedrock_signing_name():
    """ScopedEnvTokenProvider.load_token(signing_name='bedrock') must resolve the
    bearer token from a dict whose only key is AWS_BEARER_TOKEN_BEDROCK.

    This test does NOT mock botocore — it exercises the real resolution path so
    that a botocore rename of the env-var convention (signing_name → env-var key)
    is caught immediately rather than silently breaking auth with green tests.

    Contract pinned: signing_name='bedrock' → AWS_BEARER_TOKEN_BEDROCK
    """
    import botocore.session
    import botocore.tokens

    bcore_session = botocore.session.Session()
    isolated_env = {"AWS_BEARER_TOKEN_BEDROCK": "tok-contract-pin"}
    provider = botocore.tokens.ScopedEnvTokenProvider(bcore_session, environ=isolated_env)

    frozen = provider.load_token(signing_name="bedrock")

    assert frozen is not None, (
        "ScopedEnvTokenProvider.load_token(signing_name='bedrock') returned None — "
        "the env-var key AWS_BEARER_TOKEN_BEDROCK no longer maps to signing_name='bedrock'; "
        "check botocore's _get_bearer_env_var_name and update BedrockModelClient._boto_client()."
    )
    assert frozen.token == "tok-contract-pin", (
        f"Expected token 'tok-contract-pin', got {frozen.token!r} — "
        "botocore resolved a different env var for signing_name='bedrock'."
    )


def test_get_token_from_environment_bedrock_contract():
    """botocore.utils.get_token_from_environment('bedrock', ...) must read
    AWS_BEARER_TOKEN_BEDROCK — pins the low-level helper that ScopedEnvTokenProvider
    delegates to, catching a rename one layer lower than the provider test.
    """
    from botocore.utils import get_token_from_environment

    isolated_env = {"AWS_BEARER_TOKEN_BEDROCK": "tok-low-level"}
    result = get_token_from_environment("bedrock", isolated_env)

    assert result == "tok-low-level", (
        f"get_token_from_environment('bedrock', ...) returned {result!r} — "
        "the env-var name for signing_name='bedrock' has changed in botocore; "
        "update the isolated_env key in BedrockModelClient._boto_client()."
    )


def test_ns_bedrock_imported_in_app():
    """NS_BEDROCK must be importable from agent_sdk.app (used by _build_model_client)."""
    import importlib
    import ast
    from pathlib import Path

    src = Path("/Users/wailuen/Development/a2a-sdk/agent_sdk/app.py").read_text()
    tree = ast.parse(src)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module and "store" in node.module:
                for alias in node.names:
                    imports.append(alias.name)
    assert "NS_BEDROCK" in imports, "NS_BEDROCK must be imported in app.py"


# ── RT-001: botocore version floor ──────────────────────────────────────────

def test_botocore_scoped_env_token_provider_exists():
    """botocore.tokens.ScopedEnvTokenProvider must exist — gates the botocore>=1.39 floor.

    ScopedEnvTokenProvider was added in botocore 1.39.0 (boto3 1.39.0).
    If this test fails, the installed botocore is below the required floor and
    bearer-token Bedrock auth will raise AttributeError at runtime.
    """
    import botocore.tokens

    assert hasattr(botocore.tokens, "ScopedEnvTokenProvider"), (
        "botocore.tokens.ScopedEnvTokenProvider not found — upgrade to botocore>=1.39 "
        "(boto3>=1.39)"
    )
    assert callable(botocore.tokens.ScopedEnvTokenProvider)


def test_boto_client_bearer_raises_clear_error_on_old_botocore(monkeypatch):
    """_boto_client() on the bearer path must raise RuntimeError with a clear message
    if ScopedEnvTokenProvider is absent (i.e. botocore < 1.39), not AttributeError.

    RT-001: the guard converts the silent AttributeError into an actionable message.
    """
    import botocore.tokens

    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    monkeypatch.delattr(botocore.tokens, "ScopedEnvTokenProvider", raising=False)

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        bearer_token="tok-old-botocore",
    )

    with pytest.raises(RuntimeError, match="botocore>=1.39"):
        client._boto_client()


def test_boto_client_bearer_raises_clear_error_when_token_provider_chain_absent(monkeypatch):
    """RT-005: if botocore retains ScopedEnvTokenProvider but removes/renames
    TokenProviderChain, _boto_client() must still raise the actionable RuntimeError
    rather than a raw AttributeError.

    The guard must check every symbol the bearer code path touches.
    """
    import botocore.tokens

    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    monkeypatch.delattr(botocore.tokens, "TokenProviderChain", raising=False)

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        bearer_token="tok-no-chain",
    )

    with pytest.raises(RuntimeError, match="botocore>=1.39"):
        client._boto_client()
