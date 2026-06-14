"""MASTER_KEY rotation (§6) — offline decrypt-all/re-encrypt-all."""

from __future__ import annotations

import sqlite3

import pytest

from agent_sdk.credentials.encrypted_sqlite import EncryptedSqliteStore
from agent_sdk.credentials.rotate import RotationError, rotate_master_key
from agent_sdk.models.errors import AgentError, ErrorCategory

OLD = "old-master-key-0123456789abcdefXYZ"
NEW = "new-master-key-0123456789abcdefXYZ"


def test_rotation_roundtrip(tmp_path):
    db = tmp_path / "credentials.db"
    store = EncryptedSqliteStore(db, OLD)
    store.set("eodhd", "api_token", "secret-value")
    store.set("other", "password", "p@ss")
    store.close()

    assert rotate_master_key(db, OLD, NEW) == 2

    rotated = EncryptedSqliteStore(db, NEW)
    assert rotated.get("eodhd", "api_token") == "secret-value"
    assert rotated.get("other", "password") == "p@ss"
    rotated.close()

    # the old key no longer opens the store
    with pytest.raises(AgentError):
        EncryptedSqliteStore(db, OLD)


def test_rotation_refuses_wrong_old_key(tmp_path):
    db = tmp_path / "credentials.db"
    store = EncryptedSqliteStore(db, OLD)
    store.set("eodhd", "api_token", "secret-value")
    store.close()

    with pytest.raises(RotationError, match="does not match"):
        rotate_master_key(db, "wrong-key-0123456789abcdefXYZwrong", NEW)

    # untouched: old key still works
    store = EncryptedSqliteStore(db, OLD)
    assert store.get("eodhd", "api_token") == "secret-value"
    store.close()


def test_rotation_refuses_weak_new_key(tmp_path):
    db = tmp_path / "credentials.db"
    EncryptedSqliteStore(db, OLD).close()
    with pytest.raises(RotationError, match="32 characters"):
        rotate_master_key(db, OLD, "short")


def test_rotation_refuses_live_store(tmp_path):
    db = tmp_path / "credentials.db"
    store = EncryptedSqliteStore(db, OLD)
    store.set("eodhd", "api_token", "v")
    # hold a write transaction like a live server mid-write
    store._conn.execute("BEGIN IMMEDIATE")
    try:
        with pytest.raises(RotationError, match="another process"):
            rotate_master_key(db, OLD, NEW)
    finally:
        store._conn.rollback()
        store.close()


# ── CRYPTO-001 regression guards ────────────────────────────────────────────

def test_corrupt_blob_invalid_base64_raises_agent_error(tmp_path):
    """A DB row whose value is not valid base64 must surface as
    AgentError(INTERNAL), not a bare binascii.Error (CRYPTO-001)."""
    db = tmp_path / "credentials.db"
    store = EncryptedSqliteStore(db, OLD)
    store.set("ns", "field", "real-value")
    # Overwrite the stored blob with invalid base64 directly in the DB.
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE credentials SET value = ? WHERE namespace = 'ns' AND field = 'field'",
        (b"not-valid-base64===!!!",),
    )
    conn.commit()
    conn.close()
    with pytest.raises(AgentError) as exc_info:
        store.get("ns", "field")
    assert exc_info.value.category == ErrorCategory.INTERNAL
    store.close()


def test_corrupt_blob_too_short_raises_agent_error(tmp_path):
    """A blob that decodes to fewer than 12 bytes (no room for a nonce) must
    surface as AgentError(INTERNAL), not a bare ValueError (CRYPTO-001)."""
    db = tmp_path / "credentials.db"
    store = EncryptedSqliteStore(db, OLD)
    store.set("ns", "field", "real-value")
    import base64
    # 8 bytes — not enough for a 12-byte GCM nonce.
    short_blob = base64.b64encode(b"\x00" * 8)
    conn = sqlite3.connect(db)
    conn.execute(
        "UPDATE credentials SET value = ? WHERE namespace = 'ns' AND field = 'field'",
        (short_blob,),
    )
    conn.commit()
    conn.close()
    with pytest.raises(AgentError) as exc_info:
        store.get("ns", "field")
    assert exc_info.value.category == ErrorCategory.INTERNAL
    store.close()
