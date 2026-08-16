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
    fake_client = MagicMock()
    fake_boto3.Session.return_value.client.return_value = fake_client

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
    fake_client = MagicMock()
    fake_boto3.Session.return_value.client.return_value = fake_client

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


# ── GH-139: bearer selection must not depend on the real process env var ────

def test_boto_client_bearer_resolves_signature_version_without_real_env_var(
    monkeypatch, tmp_path
):
    """GH-139: _boto_client()'s bearer path must select signature_version='bearer'
    even when the REAL process os.environ has no AWS_BEARER_TOKEN_BEDROCK set.

    Root cause: botocore's own gate for attempting bearer auth
    (_should_prefer_bearer_auth in botocore/handlers.py) calls
    get_token_from_environment(), which reads the REAL os.environ — not the
    isolated per-client dict the token_provider is scoped to. Without an
    explicit signature_version='bearer' in the client Config,
    has_in_code_configuration stays False, the gate falls through, and
    resolution silently picks SigV4 with no IAM credentials configured
    (NoCredentialsError at signing time), even though the token_provider is
    correctly wired.

    This exercises botocore's real choose-signer resolution (no mocking of
    boto3/botocore) by replicating exactly the request_context
    BaseClient._make_api_call builds before signing — no network call is made.
    """
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    # Isolate from any real ~/.aws/config on the host (e.g. a login_session
    # profile) that could otherwise perturb credential/auth resolution.
    monkeypatch.setenv("AWS_CONFIG_FILE", str(tmp_path / "no-such-config"))
    monkeypatch.setenv("AWS_SHARED_CREDENTIALS_FILE", str(tmp_path / "no-such-creds"))

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        bearer_token="tok-regression-no-env",
    )

    boto_client = client._boto_client()

    operation_model = boto_client._service_model.operation_model("Converse")
    request_context = {
        "client_region": boto_client.meta.region_name,
        "client_config": boto_client.meta.config,
        "has_streaming_input": operation_model.has_streaming_input,
        "auth_type": operation_model.resolved_auth_type,
        "unsigned_payload": operation_model.unsigned_payload,
        "auth_options": boto_client._service_model.metadata.get("auth"),
    }
    resolved = boto_client._request_signer._choose_signer(
        "Converse", "standard", request_context
    )

    assert resolved == "bearer", (
        f"expected bearer signature version, got {resolved!r} — with no real "
        "AWS_BEARER_TOKEN_BEDROCK env var, botocore's environment-based "
        "bearer-auth gate falls through to SigV4, which has no credentials "
        "configured and fails with NoCredentialsError at signing time"
    )

    auth = boto_client._request_signer.get_auth_instance(
        signing_name="bedrock", region_name="us-east-1", signature_version=resolved
    )
    assert auth.auth_token.token == "tok-regression-no-env", (
        "resolved to bearer but the token_provider did not supply the "
        "configured bearer token"
    )


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


# ── RT-013: signature_version must actually resolve to 'bearer', not just be requested ──

def test_bearer_signer_is_registered_in_real_botocore_auth_type_maps():
    """RT-005: pins the registry the guard probes against the REAL installed
    botocore — not a mock. ``RequestSigner.get_auth_instance()`` looks the
    signature_version up in ``botocore.auth.AUTH_TYPE_MAPS`` and raises
    ``UnknownSignatureVersionError`` on a miss, so this membership is exactly
    what decides whether Config(signature_version='bearer') can sign. If a
    future botocore renames or drops the bearer signer, THIS test goes red and
    names the cause, instead of the SDK failing at first model call."""
    import botocore.auth

    assert "bearer" in botocore.auth.AUTH_TYPE_MAPS


def test_bearer_token_resolver_wiring_delivers_signing_name_scoped_token():
    """RT-010 (LRN-084 recurrence class): AUTH_TYPE_MAPS pins whether botocore
    can SIGN with signature_version='bearer'; it says nothing about whether the
    isolated-env token built in _boto_client() ever REACHES that signer.

    The real delivery path (no mocking) is:
      botocore/client.py ClientCreator.create_client()
        -> _evaluate_client_specific_token(service_model.signing_name)
        -> self._auth_token_resolver(signing_name=signing_name)
      where _auth_token_resolver is wired at Session.create_client() as
      auth_token_resolver=self.get_auth_token (botocore/session.py)
        -> Session.get_auth_token(signing_name='bedrock')
        -> provider.load_token(signing_name='bedrock')

    botocore/tokens.py's ScopedEnvTokenProvider.load_token() returns None
    whenever `signing_name` is absent from its kwargs. So a botocore build
    inside the declared boto3>=1.39 floor that keeps ClientCreator/Session
    but drops or breaks the signing_name hand-off would let the client
    construct cleanly with auth_token=None and fail only at first call —
    the exact GH-139 symptom the AUTH_TYPE_MAPS guard was added to prevent,
    one hop earlier in the chain.

    Verified against the exact floor: `boto3==1.39.0` resolves to
    `botocore==1.39.0`, and both `auth_token_resolver` and the
    signing_name-aware `Session.get_auth_token` are already present there —
    so this probe exists to catch a future botocore regression, not to
    raise today's floor.
    """
    import inspect

    import botocore.client
    import botocore.session
    import botocore.tokens

    assert "auth_token_resolver" in inspect.signature(
        botocore.client.ClientCreator.__init__
    ).parameters, (
        "botocore.client.ClientCreator.__init__ dropped auth_token_resolver — "
        "Session.create_client() can no longer hand Session.get_auth_token to "
        "the client, breaking bearer-token delivery for every signing_name, "
        "not just 'bedrock'."
    )

    session = botocore.session.Session()
    isolated_env = {"AWS_BEARER_TOKEN_BEDROCK": "tok-rt-010-floor-probe"}
    token_provider = botocore.tokens.TokenProviderChain(
        providers=[botocore.tokens.ScopedEnvTokenProvider(session, environ=isolated_env)]
    )
    session.register_component("token_provider", token_provider)

    resolved = session.get_auth_token(signing_name="bedrock")

    assert resolved is not None, (
        "Session.get_auth_token(signing_name='bedrock') returned None — it "
        "stopped forwarding signing_name to the registered token_provider. "
        "botocore.tokens.ScopedEnvTokenProvider.load_token() returns None "
        "whenever signing_name is absent, so _boto_client() would build a "
        "client with auth_token=None and fail only at first call with an "
        "unactionable error (GH-139 symptom, re-armed above the "
        "AUTH_TYPE_MAPS guard)."
    )
    assert resolved.token == "tok-rt-010-floor-probe", (
        f"expected 'tok-rt-010-floor-probe', got {resolved.token!r} — "
        "Session.get_auth_token resolved a different token than the one "
        "registered on the isolated env dict."
    )


def test_boto_client_bearer_raises_clear_error_when_bearer_signer_unregistered(
    monkeypatch,
):
    """RT-013 (LRN-084 follow-up), rewritten for RT-005: setting
    Config(signature_version='bearer') is a request, not a guarantee. If a
    botocore build past the version floor ignores/renames the bearer-signer
    machinery, the client would otherwise construct cleanly and fail only at
    first call with an unactionable error (GH-139 symptom, re-armed).

    The guard must probe something botocore actually consults. The previous
    revision of this test asserted on a guard that read back
    ``built_client.meta.config.signature_version`` — the value the SDK had set
    two lines earlier — and fabricated the impossible state
    ``fake_client.meta.config.signature_version = "v4"`` on a MagicMock to make
    it fire. Real botocore echoes ANY string back verbatim (verified: a client
    built with signature_version='totally-bogus-scheme' reports exactly that)
    and resolves no signer at construction, so that branch could never fire in
    production while its mocked test stayed green — LRN-084's own lesson
    recurring. The guard now probes ``botocore.auth.AUTH_TYPE_MAPS``, and this
    test removes the key from the real module to trigger it.

    Must raise a distinct, actionable RuntimeError — never the version-floor
    message, since this failure mode is orthogonal to "botocore too old" and
    telling an operator already past the floor to upgrade is unactionable
    (RT-011). The message must never echo the bearer token (SI-2).
    """
    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    import botocore.auth

    patched = dict(botocore.auth.AUTH_TYPE_MAPS)
    patched.pop("bearer", None)
    monkeypatch.setattr(botocore.auth, "AUTH_TYPE_MAPS", patched)

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        bearer_token="tok-secret-should-not-leak",
    )

    with pytest.raises(RuntimeError, match="bearer") as excinfo:
        client._boto_client()

    message = str(excinfo.value)
    assert "AUTH_TYPE_MAPS" in message, (
        "the message must name the registry the operator can inspect"
    )
    assert "botocore>=1.39" not in message, (
        "RT-011: this failure mode is orthogonal to the version-floor guard — "
        "an operator already on a supported botocore should not be told to "
        "upgrade to a version they already exceed"
    )
    assert "tok-secret-should-not-leak" not in message, (
        "bearer token must never be interpolated into the exception message (SI-2)"
    )


# ── RT-011: bearer path must not couple to the host's ambient AWS profile ────

def test_boto_client_bearer_never_calls_session_get_credentials(monkeypatch):
    """RT-011: bearer-path client construction must never walk the ambient
    AWS credential-provider chain.

    botocore.session.Session.create_client() unconditionally calls
    self.get_credentials() unless explicit static credentials are passed (or
    signature_version is UNSIGNED, which bearer auth cannot use), and
    get_credentials() falls through to
    CredentialResolver.load_credentials() — which walks the host's ambient
    AWS profile chain (~/.aws/config, AWS_PROFILE, SSO/login sessions,
    credential_process...) — whenever Session._credentials is still unset.
    That chain can raise arbitrary vendor exceptions that have nothing to do
    with the bearer token — reproduced on a machine with a `login_session`
    profile and no botocore[crt] installed: MissingDependencyException
    raised before the bearer signer is ever reached. Bearer auth signs
    exclusively via the token_provider registered on the session and must be
    independent of this chain entirely.
    """
    import botocore.credentials

    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)

    called = []
    real_load_credentials = botocore.credentials.CredentialResolver.load_credentials

    def _tracking_load_credentials(self):
        called.append(True)
        return real_load_credentials(self)

    monkeypatch.setattr(
        botocore.credentials.CredentialResolver,
        "load_credentials",
        _tracking_load_credentials,
    )

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        bearer_token="tok-rt-011",
    )

    client._boto_client()

    assert not called, (
        "CredentialResolver.load_credentials() was called during bearer-path "
        "client construction — the bearer path is coupled to the host's "
        "ambient AWS profile chain (RT-011)"
    )


def test_boto_client_bearer_succeeds_when_ambient_profile_would_raise(monkeypatch):
    """RT-011 repro: even when the host's ambient AWS profile chain would
    raise (e.g. MissingDependencyException from a `login_session` profile
    lacking botocore[crt]), bearer-path client construction must succeed —
    it never consults that chain in the first place.
    """
    import botocore.credentials
    import botocore.exceptions

    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    def _raising_load_credentials(self):
        raise botocore.exceptions.MissingDependencyException(
            msg=(
                "Using the login credential provider requires an additional "
                'dependency. You will need to pip install "botocore[crt]" '
                "before proceeding."
            )
        )

    monkeypatch.setattr(
        botocore.credentials.CredentialResolver,
        "load_credentials",
        _raising_load_credentials,
    )

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        bearer_token="tok-rt-011-repro",
    )

    boto_client = client._boto_client()

    assert boto_client.meta.config.signature_version == "bearer"


def test_boto_client_bearer_wraps_construction_failure_actionably(monkeypatch):
    """RT-011 defense-in-depth: if bearer-path client construction fails for
    any other, unforeseen reason, the caller must see a clear, actionable
    RuntimeError naming the ambient-profile coupling as the likely cause —
    never a raw boto3/botocore exception, and never the bearer token (SI-2).
    """
    import boto3

    monkeypatch.delenv("AWS_BEARER_TOKEN_BEDROCK", raising=False)

    def _boom(self, *args, **kwargs):
        raise RuntimeError("boom: tok-should-not-leak-secret")

    monkeypatch.setattr(boto3.Session, "client", _boom)

    client = BedrockModelClient(
        region="us-east-1",
        model_arn="arn:aws:bedrock:us-east-1::foundation-model/test",
        bearer_token="tok-should-not-leak-secret",
    )

    with pytest.raises(RuntimeError) as excinfo:
        client._boto_client()

    message = str(excinfo.value)
    assert "tok-should-not-leak-secret" not in message, (
        "bearer token must never be interpolated into the exception message (SI-2)"
    )
    assert "ambient" in message.lower() or "profile" in message.lower(), (
        "the wrapped error must name the ambient-profile coupling as the "
        "likely cause (RT-011)"
    )
