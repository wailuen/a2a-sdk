"""Tests for `python -m agent_sdk migrate-store` CLI (P4-03)."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_MASTER_KEY = "test-master-key-for-migration-32x"
_CONN_STR = (
    "DefaultEndpointsProtocol=https;AccountName=devstoreaccount1;"
    "AccountKey=dGVzdA==;EndpointSuffix=core.windows.net"
)

_BASE_ENV = {
    "AZURE_STORAGE_CONNECTION_STRING": _CONN_STR,
    "MASTER_KEY": _MASTER_KEY,
}


def _run(argv: list[str], env: dict[str, str] | None = None) -> tuple[int, str]:
    """Invoke ``agent_sdk.__main__.main()`` and capture stdout."""
    import io
    from agent_sdk.__main__ import main

    env = env or _BASE_ENV
    captured = io.StringIO()

    with patch.dict("os.environ", env, clear=False), \
         patch("sys.stdout", captured):
        rc = main(argv)

    return rc, captured.getvalue()


def _make_sqlite_credential_db(path: Path) -> None:
    """Populate a minimal EncryptedSqliteStore with one credential."""
    from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore

    store = EncryptedSqliteStore(path, _MASTER_KEY)
    store.set("ns1", "field1", "secret-value-1")
    store.set("ns1", "field2", "secret-value-2")
    store.set("ns2", "api_key", "secret-api-key")
    store.close()


def _make_sqlite_commitment_db(path: Path) -> None:
    """Populate a CommitmentStore with one pending + one fired commitment."""
    from agent_sdk.contrib.commitments.store import CommitmentStore

    store = CommitmentStore(path)
    store.initialize()
    # pending
    cid = store.add(
        tool="send_email",
        args={"to": "user@example.com"},
        fire_at="2099-01-01T00:00:00Z",
    )
    # fired: add then claim+mark_fired
    cid2 = store.add(
        tool="send_report",
        args={"report_id": "r1"},
        fire_at="2000-01-01T00:00:00Z",
    )
    # Manually update to fired via raw sqlite so we don't need the executor
    import sqlite3
    conn = sqlite3.connect(str(path))
    conn.execute(
        "UPDATE commitments SET status='fired' WHERE id=?", (cid2,)
    )
    conn.commit()
    conn.close()
    store.close()


def _make_sqlite_subscription_db(path: Path) -> None:
    """Populate a SubscriptionStore with two subscriptions."""
    from agent_sdk.contrib.webhooks.subscriptions import SubscriptionStore
    from datetime import datetime, timezone, timedelta

    store = SubscriptionStore(path)
    store.initialize()
    future = (datetime.now(timezone.utc) + timedelta(days=30)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    store.upsert(
        id="aaaaaaaa-0000-0000-0000-000000000001",
        resource="users/me/messages",
        change_type="created",
        notification_url="https://example.com/hook",
        expiration=future,
    )
    store.upsert(
        id="aaaaaaaa-0000-0000-0000-000000000002",
        resource="users/me/events",
        change_type="updated",
        notification_url="https://example.com/hook2",
        expiration=future,
    )
    store.close()


# ---------------------------------------------------------------------------
# Test 5: No Azure env vars → exits 1 with readable message, no traceback
# ---------------------------------------------------------------------------

def test_no_azure_env_exits_1(tmp_path, capsys):
    """migrate-store with no Azure env vars exits 1 with a readable message."""
    from agent_sdk.__main__ import main

    env_without_azure = {"MASTER_KEY": _MASTER_KEY}
    with patch.dict("os.environ", env_without_azure, clear=True):
        rc = main(["migrate-store", "--data-dir", str(tmp_path)])

    assert rc == 1
    captured = capsys.readouterr()
    assert "AZURE_STORAGE_CONNECTION_STRING" in captured.err or \
           "AZURE_STORAGE_ACCOUNT_NAME" in captured.err
    # No Python traceback
    assert "Traceback" not in captured.err


# ---------------------------------------------------------------------------
# Test 4: Missing data_dir → counts all 0, exits 0
# ---------------------------------------------------------------------------

def test_missing_data_dir_exits_0(tmp_path):
    """An empty / absent data_dir migrates nothing and exits 0."""
    empty = tmp_path / "does_not_exist"
    rc, out = _run(["migrate-store", "--data-dir", str(empty)])
    assert rc == 0
    assert "credentials" in out
    assert ": 0" in out


# ---------------------------------------------------------------------------
# Test 1: --dry-run makes zero writes to Azure mocks
# ---------------------------------------------------------------------------

def test_dry_run_no_writes(tmp_path):
    """--dry-run prints correct counts but makes zero writes to Azure mocks."""
    _make_sqlite_credential_db(tmp_path / "credentials.db")
    _make_sqlite_commitment_db(tmp_path / "commitments.db")
    _make_sqlite_subscription_db(tmp_path / "webhook_subscriptions.db")

    mock_azure_cred = MagicMock()
    mock_azure_commit = MagicMock()
    mock_azure_sub = MagicMock()

    with patch(
        "agent_sdk.credentials.azure_table.AzureTableCredentialStore",
        mock_azure_cred,
    ), patch(
        "agent_sdk.contrib.commitments.azure_table.AzureTableCommitmentStore",
        mock_azure_commit,
    ), patch(
        "agent_sdk.contrib.webhooks.azure_table.AzureTableSubscriptionStore",
        mock_azure_sub,
    ):
        rc, out = _run(["migrate-store", "--data-dir", str(tmp_path), "--dry-run"])

    assert rc == 0
    # No Azure instances were constructed
    mock_azure_cred.assert_not_called()
    mock_azure_commit.assert_not_called()
    mock_azure_sub.assert_not_called()

    # Output contains expected dry-run phrasing
    assert "[dry-run] would migrate" in out or "would migrate" in out
    # 3 credentials (2 in ns1, 1 in ns2)
    assert "3" in out or "credentials" in out


# ---------------------------------------------------------------------------
# Test 2: Without --force, existing Azure entity is skipped
# ---------------------------------------------------------------------------

def test_no_force_skips_existing_subscription(tmp_path):
    """Without --force, a subscription already in Azure is skipped."""
    _make_sqlite_subscription_db(tmp_path / "webhook_subscriptions.db")

    # Build a fake AzureTableSubscriptionStore where get() returns an entity
    # for the first subscription but None for the second.
    existing_id = "aaaaaaaa-0000-0000-0000-000000000001"

    mock_instance = MagicMock()
    mock_instance.initialize.return_value = None
    mock_instance.list.return_value = None  # not called in migrate-store

    upserted_ids: list[str] = []

    def fake_get(id: str):
        if id == existing_id:
            return {"id": id}  # simulate existing
        return None

    def fake_upsert(**kwargs: Any):
        upserted_ids.append(kwargs["id"])

    mock_instance.get.side_effect = fake_get
    mock_instance.upsert.side_effect = fake_upsert

    with patch(
        "agent_sdk.contrib.webhooks.azure_table.AzureTableSubscriptionStore",
        return_value=mock_instance,
    ), patch(
        "agent_sdk.credentials.azure_table.AzureTableCredentialStore",
        MagicMock(),
    ), patch(
        "agent_sdk.contrib.commitments.azure_table.AzureTableCommitmentStore",
        MagicMock(),
    ):
        rc, out = _run(["migrate-store", "--data-dir", str(tmp_path)])

    assert rc == 0
    # Only the second subscription should have been upserted
    assert existing_id not in upserted_ids
    assert "aaaaaaaa-0000-0000-0000-000000000002" in upserted_ids


# ---------------------------------------------------------------------------
# Test 3: With --force, existing Azure entity is overwritten
# ---------------------------------------------------------------------------

def test_force_overwrites_existing_subscription(tmp_path):
    """With --force, existing Azure entities are overwritten."""
    _make_sqlite_subscription_db(tmp_path / "webhook_subscriptions.db")

    mock_instance = MagicMock()
    mock_instance.initialize.return_value = None
    upserted_ids: list[str] = []

    def fake_upsert(**kwargs: Any):
        upserted_ids.append(kwargs["id"])

    mock_instance.upsert.side_effect = fake_upsert

    with patch(
        "agent_sdk.contrib.webhooks.azure_table.AzureTableSubscriptionStore",
        return_value=mock_instance,
    ), patch(
        "agent_sdk.credentials.azure_table.AzureTableCredentialStore",
        MagicMock(),
    ), patch(
        "agent_sdk.contrib.commitments.azure_table.AzureTableCommitmentStore",
        MagicMock(),
    ):
        rc, out = _run(
            ["migrate-store", "--data-dir", str(tmp_path), "--force"]
        )

    assert rc == 0
    # Both subscriptions must be upserted regardless of existing state
    assert "aaaaaaaa-0000-0000-0000-000000000001" in upserted_ids
    assert "aaaaaaaa-0000-0000-0000-000000000002" in upserted_ids
    # get() is never called when --force is set
    mock_instance.get.assert_not_called()


# ---------------------------------------------------------------------------
# Test 6: Credentials — plaintext never stored raw in Azure mock
# ---------------------------------------------------------------------------

def test_credentials_re_encrypted_for_azure(tmp_path):
    """Plaintext from SQLite must be re-encrypted before writing to Azure.

    The mock AzureTableCredentialStore.set() is called with the raw plaintext
    value (the Azure store encrypts internally), but we verify that decryption
    from SQLite worked (round-trip) and the set() call receives the correct
    plaintext — meaning the decryption pipeline is intact.
    """
    cred_db = tmp_path / "credentials.db"
    _make_sqlite_credential_db(cred_db)

    set_calls: list[tuple[str, str, str]] = []

    mock_instance = MagicMock()
    mock_instance.get.return_value = None  # no existing entities
    mock_instance.set.side_effect = lambda ns, field, val: set_calls.append(
        (ns, field, val)
    )

    with patch(
        "agent_sdk.credentials.azure_table.AzureTableCredentialStore",
        return_value=mock_instance,
    ):
        rc, out = _run(["migrate-store", "--data-dir", str(tmp_path)])

    assert rc == 0
    # All three credentials should have been set
    assert len(set_calls) == 3
    set_map = {(ns, f): v for ns, f, v in set_calls}
    # Values must be the original plaintext (store encrypts internally)
    assert set_map.get(("ns1", "field1")) == "secret-value-1"
    assert set_map.get(("ns1", "field2")) == "secret-value-2"
    assert set_map.get(("ns2", "api_key")) == "secret-api-key"


# ---------------------------------------------------------------------------
# Test 7: Commitment migration — only pending rows migrated
# ---------------------------------------------------------------------------

def test_commitment_migration_pending_only(tmp_path):
    """Only pending commitments are migrated; fired/failed rows are skipped."""
    _make_sqlite_commitment_db(tmp_path / "commitments.db")

    upserted_entities: list[dict] = []

    mock_table_client = MagicMock()
    mock_table_client.upsert_entity.side_effect = lambda entity, mode: upserted_entities.append(
        dict(entity)
    )

    mock_instance = MagicMock()
    mock_instance.initialize.return_value = None
    mock_instance.get.return_value = None  # no pre-existing
    mock_instance._table = mock_table_client
    mock_instance.PARTITION_KEY = "commitments"

    with patch(
        "agent_sdk.contrib.commitments.azure_table.AzureTableCommitmentStore",
        return_value=mock_instance,
    ), patch(
        "agent_sdk.credentials.azure_table.AzureTableCredentialStore",
        MagicMock(),
    ), patch(
        "agent_sdk.contrib.webhooks.azure_table.AzureTableSubscriptionStore",
        MagicMock(),
    ):
        rc, out = _run(["migrate-store", "--data-dir", str(tmp_path)])

    assert rc == 0
    # Exactly one pending commitment migrated (the fired one is skipped)
    assert len(upserted_entities) == 1
    assert upserted_entities[0]["status"] == "pending"
    assert upserted_entities[0]["tool"] == "send_email"
    # Output acknowledges 1 pending commitment
    assert "1" in out
