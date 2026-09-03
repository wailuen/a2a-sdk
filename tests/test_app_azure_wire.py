"""E2E integration test for app.py Azure credential-store wiring (P4-05).

Validates that:
- When AZURE_STORAGE_CONNECTION_STRING is configured, Agent._build_credential_store()
  returns an AzureTableCredentialStore backed by a real (Azurite) table service.
- When neither Azure env var is set, it returns an EncryptedSqliteStore.
- The raw connection string never appears in log output (SI-6).

Uses Azurite (https://github.com/Azure/Azurite) as an in-process Azure Table
emulator so no real Azure connection or MagicMock is required.  Azurite is
started once per test session with ``--inMemoryPersistence`` so all data is
discarded when the process exits.

Requires: ``npx azurite`` on PATH (ships with Node.js / npm).
"""

from __future__ import annotations

import logging
import shutil
import socket
import subprocess
import time
from unittest.mock import patch

import pytest
from pydantic import SecretStr

from agent_sdk import BaseAgentSettings
from agent_sdk.credentials.azure_table import AzureTableCredentialStore
from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore

_MASTER_KEY = "test-master-key-32-chars-minimum!!"

# ---------------------------------------------------------------------------
# Availability guard — skip the entire module when Azurite (npx azurite) is
# not present in the environment.  This prevents infrastructure-only errors
# from masking real test failures in CI environments without an Azure emulator.
# Run with ``-k azurite`` (or start Azurite first) to exercise these tests.
# ---------------------------------------------------------------------------

_AZURITE_AVAILABLE = shutil.which("npx") is not None

pytestmark = pytest.mark.skipif(
    not _AZURITE_AVAILABLE,
    reason="Azurite not available (npx not found); start Azurite or run with -k azurite",
)

# Azurite well-known devstore credentials (public, built into the emulator).
_AZURITE_ACCOUNT = "devstoreaccount1"
_AZURITE_KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq"
    "/K1SZFPTOtr/KBHBeksoGMGw=="
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _free_port() -> int:
    """Return an available TCP port on 127.0.0.1."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_port(host: str, port: int, timeout: float = 10.0) -> None:
    """Block until *host:port* accepts connections or *timeout* elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(0.2)
            try:
                s.connect((host, port))
                return
            except OSError:
                time.sleep(0.1)
    raise RuntimeError(
        f"Azurite Table service did not start on {host}:{port} within {timeout}s"
    )


# ---------------------------------------------------------------------------
# Session-scoped Azurite fixture
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session")
def azurite_table_port():
    """Start Azurite once per test session; yield the table-service port.

    Uses ``--inMemoryPersistence`` so no disk I/O occurs and all data is
    discarded when the process exits.  Blob and queue services also start
    (Azurite always starts all three) but are not used by these tests.

    If Azurite fails to start (e.g. the npm package is not installed) the
    fixture skips the session rather than erroring, so infrastructure issues
    are clearly distinguishable from code bugs.
    """
    table_port = _free_port()
    blob_port = _free_port()
    queue_port = _free_port()

    proc = subprocess.Popen(
        [
            "npx",
            "azurite",
            "--inMemoryPersistence",
            "--silent",
            "--tablePort", str(table_port),
            "--blobPort", str(blob_port),
            "--queuePort", str(queue_port),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    try:
        _wait_for_port("127.0.0.1", table_port)
    except RuntimeError as exc:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        pytest.skip(f"Azurite Table service did not start: {exc}")

    try:
        yield table_port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


@pytest.fixture(scope="session")
def azurite_conn_str(azurite_table_port):
    """Return the Azurite Table Storage connection string."""
    return (
        f"DefaultEndpointsProtocol=http;"
        f"AccountName={_AZURITE_ACCOUNT};"
        f"AccountKey={_AZURITE_KEY};"
        f"TableEndpoint=http://127.0.0.1:{azurite_table_port}/{_AZURITE_ACCOUNT};"
    )


def _make_azure_settings(tmp_path, conn_str: str) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        MASTER_KEY=_MASTER_KEY,
        AZURE_STORAGE_CONNECTION_STRING=conn_str,
    )


def _make_sqlite_settings(tmp_path) -> BaseAgentSettings:
    return BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
    )


# ---------------------------------------------------------------------------
# Test: Azure store wired when AZURE_STORAGE_CONNECTION_STRING is set
# ---------------------------------------------------------------------------


def test_azure_credential_store_wired(tmp_path, azurite_conn_str):
    """When AZURE_STORAGE_CONNECTION_STRING is set, the credential store is an
    AzureTableCredentialStore backed by a real Azurite table service.  The raw
    connection string must not appear in any log record (SI-6)."""
    from agent_sdk.example.agent import make_agent

    settings = _make_azure_settings(tmp_path, azurite_conn_str)

    log_records: list[str] = []

    class _CapHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            log_records.append(self.format(record))

    root_logger = logging.getLogger()
    handler = _CapHandler()
    root_logger.addHandler(handler)

    try:
        agent = make_agent(settings)
        store = agent._build_credential_store()
    finally:
        root_logger.removeHandler(handler)
        if "store" in dir():
            store.close()

    assert isinstance(store, AzureTableCredentialStore), (
        f"expected AzureTableCredentialStore, got {type(store).__name__}"
    )

    # SI-6: connection string must not appear in any log output.
    for record in log_records:
        assert azurite_conn_str not in record, (
            f"connection string leaked into log: {record!r}"
        )


# ---------------------------------------------------------------------------
# Note: GH-129 — DEV_MODE mismatch boot warning on the connection_string path
# ---------------------------------------------------------------------------
#
# RT-008: the SI-2 regression test for this warning (GH-129) does NOT live in
# this module. This module is skipped whenever `npx` is absent (see the
# module-level `pytestmark` above), so an SI-2-mandated gate placed here would
# silently not run on any CI runner or dev box without Node — exactly the
# failure RT-008 flagged. The warning is emitted by
# `Agent._build_credential_store()` *before* `AzureTableCredentialStore` is
# constructed, so the test needs no Azurite/emulator to exercise it. Its
# unguarded, unconditionally-run canonical home is
# tests/test_gh129_dev_mode_connection_string_warning.py.
#
# ---------------------------------------------------------------------------
# Test: Round-trip read/write on the real Azurite-backed store
# ---------------------------------------------------------------------------


def test_azure_store_round_trip(tmp_path, azurite_conn_str):
    """A credential written to the Azurite-backed store can be read back."""
    from agent_sdk.example.agent import make_agent

    settings = _make_azure_settings(tmp_path, azurite_conn_str)
    agent = make_agent(settings)
    store = agent._build_credential_store()

    try:
        store.set("testns", "api_key", "top-secret")
        retrieved = store.get("testns", "api_key")
    finally:
        store.close()

    assert retrieved == "top-secret"


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


def test_azure_account_name_wired(tmp_path, azurite_conn_str):
    """When AZURE_STORAGE_ACCOUNT_NAME is set, AzureTableCredentialStore is
    used (managed-identity path).

    Azurite only accepts the well-known devstore key; it does not implement
    DefaultAzureCredential token issuance.  We therefore patch only the
    external identity-provider call (``DefaultAzureCredential``) — an infra
    dependency outside the SDK — and redirect the ``TableServiceClient``
    constructor to Azurite via the well-known connection string so that real
    table I/O still occurs against the emulator.
    """
    from agent_sdk.example.agent import make_agent
    from azure.data.tables import TableServiceClient

    settings = BaseAgentSettings(
        DEV_MODE=True,
        DATA_DIR=str(tmp_path / "data"),
        AGENT_NAME="test-agent",
        MASTER_KEY=_MASTER_KEY,
        AZURE_STORAGE_ACCOUNT_NAME="myaccount",
    )

    # Build a real TableServiceClient pointed at Azurite to substitute for the
    # one that would normally connect to Azure using DefaultAzureCredential.
    azurite_svc = TableServiceClient.from_connection_string(azurite_conn_str)

    def _fake_table_service_client(*, endpoint: str, credential: object) -> TableServiceClient:
        # Ignore the managed-identity endpoint/credential; return Azurite client.
        return azurite_svc

    with patch(
        "azure.identity.DefaultAzureCredential",
        return_value=object(),  # not used; just satisfies the type check
    ), patch(
        "azure.data.tables.TableServiceClient",
        side_effect=None,
        **{"return_value": azurite_svc},
    ) as mock_svc_cls:
        # Make the constructor return our Azurite-backed service.
        mock_svc_cls.return_value = azurite_svc
        # Ensure from_connection_string still works (used by other tests).
        mock_svc_cls.from_connection_string = TableServiceClient.from_connection_string

        agent = make_agent(settings)
        store = agent._build_credential_store()

    try:
        assert isinstance(store, AzureTableCredentialStore), (
            f"expected AzureTableCredentialStore, got {type(store).__name__}"
        )
        # Verify the store actually works against the emulator.
        store.set("idns", "token", "abc123")
        assert store.get("idns", "token") == "abc123"
    finally:
        store.close()
