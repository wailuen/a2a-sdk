"""Low-level crypto primitives for the credential store (DESIGN.md §6).

All symmetric helpers live here so that both EncryptedSqliteStore and
rotate.py share a single implementation without cross-importing.

Security invariants enforced here:
- SI-2: decryption failure never echoes the ciphertext blob in the error msg.
- SI-6: key material is never logged or included in exceptions.
"""

from __future__ import annotations

import base64
import os
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from ..models.errors import AgentError, ErrorCategory

#: PBKDF2-HMAC-SHA256 iteration count (NIST SP 800-132 recommended floor for
#: interactive credentials as of 2024).
PBKDF2_ITERATIONS: int = 600_000


def derive_key(master_key: str, salt: bytes) -> bytes:
    """Derive a 32-byte AES key from *master_key* and *salt* via PBKDF2-HMAC-SHA256.

    Args:
        master_key: The plaintext master key (must be caller-validated).
        salt: Random per-store salt (16 bytes recommended).

    Returns:
        32-byte raw key suitable for ``AESGCM(key)``.
    """
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=PBKDF2_ITERATIONS,
    )
    return kdf.derive(master_key.encode())


def encrypt(aes: Any, namespace: str, field: str, value: str) -> bytes:
    """Encrypt *value* with AES-256-GCM, binding ``namespace/field`` as AAD.

    Returns base64-encoded ``nonce (12 B) || ciphertext+tag``.

    Args:
        aes: An initialised ``AESGCM`` instance.
        namespace: Credential namespace used as part of the AAD.
        field: Credential field name used as part of the AAD.
        value: Plaintext string to encrypt.
    """
    nonce = os.urandom(12)
    aad = f"{namespace}/{field}".encode()
    ct = aes.encrypt(nonce, value.encode(), aad)
    return base64.b64encode(nonce + ct)


def decrypt(aes: Any, namespace: str, field: str, blob: bytes) -> str:
    """Decrypt a blob produced by :func:`encrypt`.

    Args:
        aes: An initialised ``AESGCM`` instance (must match the one used to
            encrypt, with the same key).
        namespace: Must match the value used during encryption.
        field: Must match the value used during encryption.
        blob: base64-encoded ``nonce || ciphertext+tag`` as returned by
            :func:`encrypt`.

    Returns:
        Decrypted plaintext string.

    Raises:
        AgentError(INTERNAL, ...): On any decryption failure — ``InvalidTag``
            (wrong key, corrupted data, AAD mismatch), ``binascii.Error``
            (invalid base64 padding), or ``ValueError`` (nonce too short).
            The blob is **never** included in the error message (SI-2).
    """
    try:
        raw = base64.b64decode(blob)
        nonce, ct = raw[:12], raw[12:]
        aad = f"{namespace}/{field}".encode()
        return aes.decrypt(nonce, ct, aad).decode()
    except (InvalidTag, ValueError) as exc:
        raise AgentError(
            ErrorCategory.INTERNAL, "credential store decryption failed"
        ) from exc


__all__ = ["PBKDF2_ITERATIONS", "derive_key", "encrypt", "decrypt"]
