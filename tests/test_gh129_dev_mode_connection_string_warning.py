"""GH-129 / SI-2: DEV_MODE + AZURE_STORAGE_CONNECTION_STRING boot warning.

RT-008 (round-4 debug): this test previously lived in tests/test_app_azure_wire.py,
whose module-level ``pytestmark = pytest.mark.skipif(not shutil.which("npx"))``
guard skips the ENTIRE module on any machine without Node. GH-129 carries SI: SI-2
with an AC mandating a named regression test asserting the connection string is
absent from the emitted LogRecord (LRN-128) — but under that guard the SI-2
assertion silently did not run on CI runners or dev boxes without Node, so the
mandated gate existed on paper only.

It has no Azurite dependency to justify the guard: the warning is emitted by
``Agent._build_credential_store()`` BEFORE ``AzureTableCredentialStore`` is
constructed, so a synthetic connection string plus a stubbed store class
exercises the whole SI-2 contract with no emulator, no Node, and no network.
This module therefore carries NO skip guard and runs in the default
``pytest -q`` suite.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from agent_sdk.config import BaseAgentSettings

_MASTER_KEY = "test-master-key-32-chars-minimum!!"

# Synthetic, non-live credential — shaped like a real Azure connection string
# (the AccountKey is the thing SI-2 must keep out of logs) but pointing nowhere.
_FAKE_ACCOUNT_KEY = "ZmFrZS1hY2NvdW50LWtleS1uZXZlci1sb2dnZWQtMDAwMDAwMDA="
_FAKE_CONN_STR = (
    "DefaultEndpointsProtocol=https;"
    "AccountName=notarealaccount;"
    f"AccountKey={_FAKE_ACCOUNT_KEY};"
    "TableEndpoint=https://notarealaccount.table.core.windows.net/;"
)


class _StubStore:
    """Stands in for AzureTableCredentialStore — the warning under test is
    emitted before the real store is built, and the real one eagerly calls
    create_table_if_not_exists() (network) in __init__."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs

    def close(self) -> None:
        pass


def _build_records(
    monkeypatch, tmp_path, conn_str: str, *, dev_mode: bool = True
) -> list[logging.LogRecord]:
    """Build the credential store with a stubbed Azure backend, returning every
    LogRecord emitted on the agent_sdk.app logger."""
    from agent_sdk.credentials import azure_table
    from agent_sdk.example.agent import make_agent

    monkeypatch.setattr(azure_table, "AzureTableCredentialStore", _StubStore)

    settings = BaseAgentSettings(
        DEV_MODE=dev_mode,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        MASTER_KEY=_MASTER_KEY,
        AZURE_STORAGE_CONNECTION_STRING=conn_str,
    )

    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    app_logger = logging.getLogger("agent_sdk.app")
    handler = _Collector()
    app_logger.addHandler(handler)
    try:
        store = make_agent(settings)._build_credential_store()
    finally:
        app_logger.removeHandler(handler)

    assert isinstance(store, _StubStore), (
        "the Azure branch must have been taken — otherwise this test would pass "
        "vacuously against the SQLite fallback path"
    )
    return records


@pytest.fixture()
def captured_app_logs(monkeypatch, tmp_path):
    return _build_records(monkeypatch, tmp_path, _FAKE_CONN_STR)


def test_dev_mode_with_connection_string_emits_warning(captured_app_logs):
    """DEV_MODE=True + AZURE_STORAGE_CONNECTION_STRING set must emit a boot
    WARNING (GH-129), mirroring the sibling azure_storage_account_name branch.

    This is the confirmed root enabler of a real production incident: ~30 days
    of local test runs with DEV_MODE=True pointed at a live connection string
    minted 18,969 admin API keys into the production credential store,
    silently, with no boot-time signal.
    """
    messages = [r.getMessage() for r in captured_app_logs]
    assert any(
        "AZURE_STORAGE_CONNECTION_STRING" in m and "DEV_MODE" in m.upper()
        for m in messages
    ), f"Expected a DEV_MODE/AZURE_STORAGE_CONNECTION_STRING boot warning; got: {messages}"

    assert any(
        r.levelno >= logging.WARNING
        and "AZURE_STORAGE_CONNECTION_STRING" in r.getMessage()
        for r in captured_app_logs
    ), "the dev-mode mismatch signal must be at WARNING or above, not INFO"


def test_warning_never_leaks_the_connection_string(captured_app_logs):
    """SI-2 (LRN-128): the warning must name the SETTING only. The connection
    string is a live credential — its AccountKey is a base64 storage key that
    grants full account access — and must never reach a log sink, neither whole
    nor in fragments."""
    for record in captured_app_logs:
        message = record.getMessage()
        assert _FAKE_CONN_STR not in message, (
            f"connection string leaked into log record: {message!r}"
        )
        assert _FAKE_ACCOUNT_KEY not in message, (
            f"AccountKey leaked into log record: {message!r}"
        )
        assert "notarealaccount" not in message, (
            f"account name leaked into log record: {message!r}"
        )
        # also guard the un-rendered args tuple, which some handlers format
        assert _FAKE_ACCOUNT_KEY not in str(record.args or ()), (
            "AccountKey present in the LogRecord args tuple"
        )


@pytest.mark.parametrize(
    "conn_str",
    [
        pytest.param("UseDevelopmentStorage=true", id="bare-shortcut"),
        pytest.param(
            "AccountName=devstoreaccount1;AccountKey=Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1"
            "OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw==;"
            "DefaultEndpointsProtocol=http;"
            "TableEndpoint=http://127.0.0.1:10002/devstoreaccount1;",
            id="azurite-explicit-endpoint",
        ),
    ],
)
def test_dev_mode_with_azurite_shortcut_emits_no_warning(monkeypatch, tmp_path, conn_str):
    """RT-010: the Azurite emulator shortcut is the one config the GH-129
    warning exists to steer people TOWARD — it must never trip the warning
    that tells them to switch to it."""
    records = _build_records(monkeypatch, tmp_path, conn_str)
    messages = [r.getMessage() for r in records]
    assert not any(
        "AZURE_STORAGE_CONNECTION_STRING" in m and "DEV_MODE" in m.upper()
        for m in messages
    ), f"Azurite emulator connection string must not trigger the DEV_MODE warning; got: {messages}"


def test_dev_mode_with_real_shaped_connection_string_still_warns(monkeypatch, tmp_path):
    """RT-010 regression guard: the fix must not blanket-suppress the warning —
    a real-shaped (non-emulator) connection string in DEV_MODE still warns."""
    records = _build_records(monkeypatch, tmp_path, _FAKE_CONN_STR)
    messages = [r.getMessage() for r in records]
    assert any(
        "AZURE_STORAGE_CONNECTION_STRING" in m and "DEV_MODE" in m.upper()
        for m in messages
    ), f"Expected the DEV_MODE boot warning for a real-shaped connection string; got: {messages}"
