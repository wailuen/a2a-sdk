"""GH-162: warn when a shared store is paired with per-process sign-in state."""

from __future__ import annotations

import logging

import pytest

from agent_sdk.config import BaseAgentSettings
from agent_sdk.example.agent import make_agent

AZURITE = "UseDevelopmentStorage=true"
IDP = {
    "AGENT_SDK_OAUTH_IDP": "oidc",
    "AGENT_SDK_OAUTH_IDP_ISSUER": "https://login.microsoftonline.com/"
    "11111111-1111-1111-1111-111111111111/v2.0",
    "AGENT_SDK_OAUTH_IDP_CLIENT_ID": "client-1",
    "AGENT_SDK_OAUTH_IDP_ALLOW_ALL_ISSUER_USERS": "true",
}


def _boot(monkeypatch, caplog, env: dict[str, str]) -> list[str]:
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DEV_MODE", "true")
    settings = BaseAgentSettings(_env_file=None)
    records: list[logging.LogRecord] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    handler = _Capture(level=logging.WARNING)
    app_logger = logging.getLogger("agent_sdk.app")
    app_logger.addHandler(handler)
    try:
        make_agent(settings).build_app()
    except Exception:
        pass
    finally:
        app_logger.removeHandler(handler)
    return [r.getMessage() for r in records if "single replica" in r.getMessage()]


def test_warns_once_for_shared_store_with_idp(monkeypatch, caplog):
    msgs = _boot(monkeypatch, caplog, {"AZURE_STORAGE_CONNECTION_STRING": AZURITE, **IDP})
    assert len(msgs) == 1
    assert "exactly one replica" in msgs[0]


def test_warns_for_shared_store_with_oauth_consent(monkeypatch, caplog):
    env = {"AZURE_STORAGE_CONNECTION_STRING": AZURITE, "AGENT_SDK_OAUTH_ONE_TIME_CONSENT": "true"}
    assert len(_boot(monkeypatch, caplog, env)) == 1


def test_warns_for_shared_store_with_default_oauth_mode(monkeypatch, caplog):
    msgs = _boot(monkeypatch, caplog, {"AZURE_STORAGE_CONNECTION_STRING": AZURITE})
    assert len(msgs) == 1
    assert "exactly one replica" in msgs[0]


def test_no_warning_on_local_store(monkeypatch, caplog):
    assert _boot(monkeypatch, caplog, dict(IDP)) == []


def test_config_comment_no_longer_claims_multi_replica():
    import inspect

    from agent_sdk import config

    assert "multi-replica deployments are supported" not in inspect.getsource(config)


def test_warning_leaks_no_connection_string_parts(monkeypatch, caplog):
    marker = (
        "DefaultEndpointsProtocol=https;AccountName=MARKACCT;"
        "AccountKey=MARKKEYHEAD0123MARKKEYTAIL==;EndpointSuffix=core.windows.net"
    )
    env = {
        "AZURE_STORAGE_CONNECTION_STRING": marker,
        "AZURE_STORAGE_TABLE_PREFIX": "MARKPFX",
        **IDP,
    }
    msgs = _boot(monkeypatch, caplog, env)
    assert len(msgs) == 1
    for part in ("MARKACCT", "MARKKEYHEAD", "MARKKEYTAIL", "MARKPFX", "DefaultEndpoints", "core.windows"):
        assert part not in msgs[0]


def test_warns_for_shared_store_by_account_name(monkeypatch, caplog):
    # Ruling: https://github.com/wailuen/a2a-sdk/issues/162#issuecomment-6142451447
    msgs = _boot(monkeypatch, caplog, {"AZURE_STORAGE_ACCOUNT_NAME": "acct"})
    assert len(msgs) == 1
