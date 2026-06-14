"""Offline MASTER_KEY rotation (DESIGN.md §6).

Decrypt-all/re-encrypt-all under a new key + fresh salt, in one EXCLUSIVE
sqlite transaction. Refuses to run while another process holds the store
(the exclusive lock fails) — run it with the server stopped.
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .crypto import decrypt as _decrypt_blob
from .crypto import derive_key
from .crypto import encrypt as _encrypt_blob
from .encrypted_sqlite import _CHECK_FIELD, _CHECK_VALUE


class RotationError(Exception):
    """Rotation refused or failed; message is operator-safe (no key material)."""


def _derive(master_key: str, salt: bytes) -> AESGCM:
    return AESGCM(derive_key(master_key, salt))


def _encrypt(aes: AESGCM, namespace: str, field: str, value: str) -> bytes:
    return _encrypt_blob(aes, namespace, field, value)


def _decrypt(aes: AESGCM, namespace: str, field: str, blob: bytes) -> str:
    # AgentError (raised by crypto.decrypt on InvalidTag) is a subclass of
    # Exception, so the rotation's broad except handler still catches it.
    return _decrypt_blob(aes, namespace, field, blob)


def rotate_master_key(db_path: str | Path, old_key: str, new_key: str) -> int:
    """Re-encrypt every credential under ``new_key``. Returns the number of
    credentials rotated. Raises RotationError on any refusal — the store is
    left untouched (single transaction)."""
    if len(new_key) < 32:
        raise RotationError("new MASTER_KEY must be at least 32 characters")
    path = Path(db_path)
    if not path.is_file():
        raise RotationError(f"credential store not found: {path}")

    conn = sqlite3.connect(path, timeout=0.5)
    try:
        try:
            conn.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as exc:
            raise RotationError(
                "refusing to rotate: another process holds the credential store "
                "(stop the agent server first)"
            ) from exc

        salt_row = conn.execute("SELECT value FROM meta WHERE key='salt'").fetchone()
        check_row = conn.execute("SELECT value FROM meta WHERE key='check'").fetchone()
        if salt_row is None or check_row is None:
            raise RotationError("store is missing key metadata; cannot rotate")

        old_aes = _derive(old_key, salt_row[0])
        try:
            if _decrypt(old_aes, "__meta__", _CHECK_FIELD, check_row[0]) != _CHECK_VALUE:
                raise RotationError("old MASTER_KEY does not match the store")
        except RotationError:
            raise
        except Exception as exc:
            raise RotationError("old MASTER_KEY does not match the store") from exc

        new_salt = os.urandom(16)
        new_aes = _derive(new_key, new_salt)

        rows = conn.execute("SELECT namespace, field, value FROM credentials").fetchall()
        for i, (namespace, field, blob) in enumerate(rows):
            try:
                plaintext = _decrypt(old_aes, namespace, field, blob)
            except Exception as exc:
                raise RotationError(
                    f"a credential failed to decrypt (row {i + 1} of {len(rows)}); "
                    "store may be corrupt — rotation aborted"
                ) from exc
            conn.execute(
                "UPDATE credentials SET value=? WHERE namespace=? AND field=?",
                (_encrypt(new_aes, namespace, field, plaintext), namespace, field),
            )

        conn.execute("UPDATE meta SET value=? WHERE key='salt'", (new_salt,))
        conn.execute(
            "UPDATE meta SET value=? WHERE key='check'",
            (_encrypt(new_aes, "__meta__", _CHECK_FIELD, _CHECK_VALUE),),
        )
        conn.commit()
        return len(rows)
    finally:
        conn.close()
