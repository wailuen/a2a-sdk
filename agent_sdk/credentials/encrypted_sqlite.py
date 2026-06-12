"""Encrypted SQLite credential store (DESIGN.md §6).

- KDF pinned: PBKDF2-HMAC-SHA256, 600k iterations, per-store random salt
  persisted in the (plaintext) meta table.
- Values encrypted with AES-256-GCM; the ``{namespace}/{field}`` slot is
  bound as AAD so a ciphertext moved between rows fails to decrypt.
- A check value written at store creation detects a wrong MASTER_KEY at
  startup with a clear error instead of garbage reads.
- Synchronous sqlite3 + lock: credential traffic is rare (adapter resolves,
  console writes); no async driver needed.
"""

from __future__ import annotations

import base64
import os
import sqlite3
import threading
import time
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ..models.errors import AgentError, ErrorCategory
from .store import CredentialStore

PBKDF2_ITERATIONS = 600_000
_CHECK_FIELD = "__check__"
_CHECK_VALUE = "agent-sdk-store-check"


class EncryptedSqliteStore(CredentialStore):
    def __init__(self, db_path: str | Path, master_key: str) -> None:
        if len(master_key) < 32:
            raise ValueError("MASTER_KEY must be at least 32 characters")
        self._path = Path(db_path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._path, check_same_thread=False)
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value BLOB)"
        )
        self._conn.execute(
            "CREATE TABLE IF NOT EXISTS credentials ("
            " namespace TEXT NOT NULL, field TEXT NOT NULL, value BLOB NOT NULL,"
            " updated_at REAL NOT NULL, PRIMARY KEY (namespace, field))"
        )
        self._conn.commit()
        self._aes = AESGCM(self._derive_key(master_key))
        self._verify_master_key()

    # ── key handling ──

    def _derive_key(self, master_key: str) -> bytes:
        row = self._conn.execute("SELECT value FROM meta WHERE key='salt'").fetchone()
        if row is None:
            salt = os.urandom(16)
            with self._lock:
                self._conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('salt', ?)", (salt,)
                )
                self._conn.commit()
        else:
            salt = row[0]
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(), length=32, salt=salt, iterations=PBKDF2_ITERATIONS
        )
        return kdf.derive(master_key.encode())

    def _verify_master_key(self) -> None:
        row = self._conn.execute("SELECT value FROM meta WHERE key='check'").fetchone()
        if row is None:
            blob = self._encrypt("__meta__", _CHECK_FIELD, _CHECK_VALUE)
            with self._lock:
                self._conn.execute(
                    "INSERT INTO meta (key, value) VALUES ('check', ?)", (blob,)
                )
                self._conn.commit()
            return
        try:
            self._decrypt("__meta__", _CHECK_FIELD, row[0])
        except AgentError as err:
            raise AgentError(
                ErrorCategory.AUTH,
                "MASTER_KEY does not match the existing credential store "
                f"({self._path}); restore the original key or wipe the store",
            ) from err

    # ── crypto ──

    def _encrypt(self, namespace: str, field: str, value: str) -> bytes:
        nonce = os.urandom(12)
        aad = f"{namespace}/{field}".encode()
        ct = self._aes.encrypt(nonce, value.encode(), aad)
        return base64.b64encode(nonce + ct)

    def _decrypt(self, namespace: str, field: str, blob: bytes) -> str:
        raw = base64.b64decode(blob)
        nonce, ct = raw[:12], raw[12:]
        aad = f"{namespace}/{field}".encode()
        try:
            return self._aes.decrypt(nonce, ct, aad).decode()
        except InvalidTag as exc:
            raise AgentError(
                ErrorCategory.INTERNAL, "credential store decryption failed"
            ) from exc

    # ── CredentialStore ──

    def get(self, namespace: str, field: str) -> str | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM credentials WHERE namespace=? AND field=?",
                (namespace, field),
            ).fetchone()
        if row is None:
            return None
        return self._decrypt(namespace, field, row[0])

    def set(self, namespace: str, field: str, value: str) -> None:
        blob = self._encrypt(namespace, field, value)
        with self._lock:
            self._conn.execute(
                "INSERT INTO credentials (namespace, field, value, updated_at)"
                " VALUES (?, ?, ?, ?)"
                " ON CONFLICT(namespace, field) DO UPDATE SET value=excluded.value,"
                " updated_at=excluded.updated_at",
                (namespace, field, blob, time.time()),
            )
            self._conn.commit()

    def delete(self, namespace: str, field: str) -> None:
        with self._lock:
            self._conn.execute(
                "DELETE FROM credentials WHERE namespace=? AND field=?",
                (namespace, field),
            )
            self._conn.commit()

    def list_fields(self, namespace: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT field FROM credentials WHERE namespace=? ORDER BY field",
                (namespace,),
            ).fetchall()
        return [r[0] for r in rows]

    def close(self) -> None:
        with self._lock:
            self._conn.close()
