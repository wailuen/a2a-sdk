"""E2E integration test for app.py Azure credential-store wiring (P4-05).

Validates that:
- When AZURE_STORAGE_CONNECTION_STRING is configured, Agent._build_credential_store()
  returns an AzureTableCredentialStore (lazy import, no real Azure connection).
- When neither Azure env var is set, it returns an EncryptedSqliteStore.
- The raw connection string never appears in log output (SI-6).
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest
from pydantic import SecretStr

from agent_sdk import BaseAgentSettings
from agent_sdk.credentials.azure_table import AzureTableCredentialStore
from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore

_CONN_STR = (
    "DefaultEndpointsProtocol=https;AccountName=devstoreaccount1;"
    "AccountKey=dGVzdA==;EndpointSuffix=core.windows.net"
)
_MASTER_KEY = "test-master-key-32-chars-minimum!!"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_azure_settings(tmp_path) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        MASTER_KEY=_MASTER_KEY,
        AZURE_STORAGE_CONNECTION_STRING=_CONN_STR,
    )


def _make_sqlite_settings(tmp_path) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
    )


def _make_mock_azure_table_service(mock_table_client: MagicMock):
    """Build a mock TableServiceClient that returns mock_table_client."""
    mock_service = MagicMock()
    mock_service.create_table_if_not_exists.return_value = mock_table_client
    return mock_service


def _make_mock_table_client() -> MagicMock:
    """A mock azure table client that supports the get/upsert operations used
    by AzureTableCredentialStore at init time (salt + check entities)."""
    mock_table = MagicMock()

    # Simulate "no salt yet" → triggers upsert_entity (create salt)
    # Then simulate "no check yet" → triggers upsert_entity (create check)
    from azure.core.exceptions import ResourceNotFoundError

    mock_table.get_entity.side_effect = ResourceNotFoundError("not found")
    mock_table.upsert_entity.return_value = None
    return mock_table


# ---------------------------------------------------------------------------
# Test: Azure store wired when AZURE_STORAGE_CONNECTION_STRING is set
# ---------------------------------------------------------------------------

def test_azure_credential_store_wired(tmp_path):
    """When AZURE_STORAGE_CONNECTION_STRING is set, the credential store is
    an AzureTableCredentialStore.  The raw connection string must not appear
    in any log record captured during the test (SI-6)."""
    from agent_sdk.example.agent import make_agent

    settings = _make_azure_settings(tmp_path)

    mock_table = _make_mock_table_client()

    log_records: list[str] = []

    class _CapHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            log_records.append(self.format(record))

    root_logger = logging.getLogger()
    handler = _CapHandler()
    root_logger.addHandler(handler)

    try:
        with patch(
            "azure.data.tables.TableServiceClient.from_connection_string",
        ) as mock_from_conn:
            mock_service = MagicMock()
            mock_service.create_table_if_not_exists.return_value = mock_table
            mock_from_conn.return_value = mock_service

            agent = make_agent(settings)
            # _build_credential_store() is called inside build_app();
            # we call it directly here to stay outside the lifespan.
            store = agent._build_credential_store()
    finally:
        root_logger.removeHandler(handler)

    assert isinstance(store, AzureTableCredentialStore), (
        f"expected AzureTableCredentialStore, got {type(store).__name__}"
    )

    # SI-6: connection string must not appear in any log output
    conn_str_value = _CONN_STR
    for record in log_records:
        assert conn_str_value not in record, (
            f"connection string leaked into log: {record!r}"
        )


# ---------------------------------------------------------------------------
# Test: SQLite store wired when no Azure env vars are set
# ---------------------------------------------------------------------------

def test_sqlite_credential_store_wired(tmp_path):
    """When neither Azure env var is set, the credential store is an
    EncryptedSqliteStore."""
    from agent_sdk.example.agent import make_agent

    settings = _make_sqlite_settings(tmp_path)
    agent = make_agent(settings)
    store = agent._build_credential_store()

    assert isinstance(store, EncryptedSqliteStore), (
        f"expected EncryptedSqliteStore, got {type(store).__name__}"
    )
    store.close()


# ---------------------------------------------------------------------------
# Test: AZURE_STORAGE_ACCOUNT_NAME path also returns AzureTableCredentialStore
# ---------------------------------------------------------------------------

def test_azure_account_name_wired(tmp_path):
    """When AZURE_STORAGE_ACCOUNT_NAME is set, AzureTableCredentialStore is
    used (managed-identity path)."""
    from agent_sdk.example.agent import make_agent

    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        MASTER_KEY=_MASTER_KEY,
        AZURE_STORAGE_ACCOUNT_NAME="myaccount",
    )

    mock_table = _make_mock_table_client()

    with patch(
        "azure.identity.DefaultAzureCredential",
        return_value=MagicMock(),
    ), patch(
        "azure.data.tables.TableServiceClient",
    ) as mock_service_cls:
        mock_service = MagicMock()
        mock_service.create_table_if_not_exists.return_value = mock_table
        mock_service_cls.return_value = mock_service

        agent = make_agent(settings)
        store = agent._build_credential_store()

    assert isinstance(store, AzureTableCredentialStore), (
        f"expected AzureTableCredentialStore, got {type(store).__name__}"
    )
