"""API keys + bootstrap token (DESIGN.md §6).

Keys are bearer tokens ``ak_{key_id}_{secret}``, sha256-hashed at rest in
the encrypted store's reserved namespace, constant-time compared,
prefix-only displayed. Last-admin-key revocation is refused (lockout is
impossible by that path).

Bootstrap: whenever the store holds zero keys at startup a single-use token
is generated in memory and printed to stdout; it expires after 15 minutes
and is consumed atomically by the first key mint. There is no window where
key-minting is open to the network.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sys
import time
from dataclasses import dataclass

from ..credentials.store import NS_API_KEYS, CredentialStore
from ..models.errors import AgentError, ErrorCategory
from .identity import Identity

BOOTSTRAP_TTL_SECONDS = 15 * 60


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(slots=True)
class ApiKeyInfo:
    key_id: str
    prefix: str
    label: str
    admin: bool
    created_at: float
    last_used: float | None


class ApiKeyStore:
    def __init__(self, store: CredentialStore) -> None:
        self._store = store

    # ── queries ──

    def count(self) -> int:
        return len(self._store.list_fields(NS_API_KEYS))

    def list_keys(self) -> list[ApiKeyInfo]:
        out = []
        for key_id in self._store.list_fields(NS_API_KEYS):
            record = self._record(key_id)
            if record is not None:
                out.append(
                    ApiKeyInfo(
                        key_id=key_id,
                        prefix=record["prefix"],
                        label=record["label"],
                        admin=record["admin"],
                        created_at=record["created_at"],
                        last_used=record.get("last_used"),
                    )
                )
        return out

    def _record(self, key_id: str) -> dict | None:
        raw = self._store.get(NS_API_KEYS, key_id)
        return json.loads(raw) if raw else None

    # ── mint / verify / revoke ──

    def mint(self, label: str, *, admin: bool = False) -> tuple[str, str]:
        """Returns (key_id, plaintext). Plaintext is shown exactly once."""
        key_id = secrets.token_hex(8)
        plaintext = f"ak_{key_id}_{secrets.token_urlsafe(32)}"
        record = {
            "hash": _hash(plaintext),
            "prefix": plaintext[:11],  # "ak_" + key_id[:8]
            "label": label,
            "admin": admin,
            "created_at": time.time(),
            "last_used": None,
        }
        self._store.set(NS_API_KEYS, key_id, json.dumps(record))
        return key_id, plaintext

    def verify(self, presented: str) -> Identity | None:
        parts = presented.split("_")
        candidates = (
            [parts[1]] if len(parts) == 3 and parts[0] == "ak" else self._store.list_fields(NS_API_KEYS)
        )
        presented_hash = _hash(presented)
        for key_id in candidates:
            record = self._record(key_id)
            if record is None:
                continue
            if hmac.compare_digest(record["hash"], presented_hash):
                record["last_used"] = time.time()
                self._store.set(NS_API_KEYS, key_id, json.dumps(record))
                return Identity(
                    kind="api_key",
                    subject=key_id,
                    admin=bool(record["admin"]),
                    label=record["label"],
                )
        return None

    def revoke(self, key_id: str) -> None:
        record = self._record(key_id)
        if record is None:
            raise AgentError(ErrorCategory.NOT_FOUND, "unknown key id")
        if record["admin"]:
            other_admins = [
                k
                for k in self._store.list_fields(NS_API_KEYS)
                if k != key_id and (self._record(k) or {}).get("admin")
            ]
            if not other_admins:
                raise AgentError(
                    ErrorCategory.VALIDATION,
                    "refusing to revoke the last admin key (mint another admin key first)",
                )
        self._store.delete(NS_API_KEYS, key_id)


class BootstrapManager:
    """Single-use first-run token; re-arms whenever the key store is empty."""

    def __init__(self, keys: ApiKeyStore) -> None:
        self._keys = keys
        self._token: str | None = None
        self._expires_at: float = 0.0

    def arm_if_needed(self) -> None:
        if self._keys.count() > 0:
            self._token = None
            return
        self._token = secrets.token_urlsafe(32)
        self._expires_at = time.time() + BOOTSTRAP_TTL_SECONDS
        print(
            "\n=== agent-sdk first-run bootstrap ===\n"
            f"Bootstrap token (valid {BOOTSTRAP_TTL_SECONDS // 60} min, single use):\n"
            f"  {self._token}\n"
            "Use it once to mint the first admin API key via the console or\n"
            "POST /admin/api/keys with header 'X-Bootstrap-Token'.\n"
            "=====================================\n",
            file=sys.stdout,
            flush=True,
        )

    @property
    def armed(self) -> bool:
        return self._token is not None and time.time() < self._expires_at

    def consume(self, presented: str) -> bool:
        """Atomic single-use check: success invalidates the token."""
        if not self.armed or self._token is None:
            return False
        ok = hmac.compare_digest(self._token, presented)
        if ok:
            self._token = None
        return ok
