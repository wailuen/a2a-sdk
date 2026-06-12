"""Offline MASTER_KEY rotation (DESIGN.md §6).

Decrypt-all/re-encrypt-all under a new key + fresh salt, in one EXCLUSIVE
sqlite transaction. Refuses to run while another process holds the store
(the exclusive lock fails) — run it with the server stopped.
"""

from __future__ import annotations

import base64
import os
import sqlite3
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from .encrypted_sqlite import PBKDF2_ITERATIONS, _CHECK_FIELD, _CHECK_VALUE


class RotationError(Exception):
    """Rotation refused or failed; message is operator-safe (no key material)."""


def _derive(master_key: str, salt: bytes) -> AESGCM:
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS
    )
    return AESGCM(kdf.derive(master_key.encode()))


def _encrypt(aes: AESGCM, namespace: str, field: str, value: str) -> bytes:
    nonce = os.urandom(12)
    ct = aes.encrypt(nonce, value.encode(), f"{namespace}/{field}".encode())
    return base64.b64encode(nonce + ct)


def _decrypt(aes: AESGCM, namespace: str, field: str, blob: bytes) -> str:
    raw = base64.b64decode(blob)
    return aes.decrypt(raw[:12], raw[12:], f"{namespace}/{field}".encode()).decode()


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
        for namespace, field, blob in rows:
            try:
                plaintext = _decrypt(old_aes, namespace, field, blob)
            except Exception as exc:
                raise RotationError(
                    f"credential {namespace}/{field} failed to decrypt; store may "
                    "be corrupt — rotation aborted, nothing changed"
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
