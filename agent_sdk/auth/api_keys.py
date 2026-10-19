"""API keys + bootstrap token (DESIGN.md §6).

Keys are bearer tokens ``ak_{key_id}_{secret}``, sha256-hashed at rest in
the encrypted store's reserved namespace, constant-time compared,
prefix-only displayed. Last-admin-key revocation is refused (lockout is
impossible by that path).

Bootstrap: whenever the store holds zero keys at startup a single-use token
is generated in memory and printed to stderr; it expires after 15 minutes
and is consumed atomically by the first key mint. There is no window where
key-minting is open to the network.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
import sys
import threading
import time
from dataclasses import dataclass

from ..credentials.store import NS_API_KEYS, CredentialStore
from ..models.errors import AgentError, ErrorCategory
from .identity import Identity

BOOTSTRAP_TTL_SECONDS = 15 * 60
_LAST_USED_WRITE_INTERVAL = 60.0
_KEY_LOCK_STRIPES = 64
_API_KEY_RE = re.compile(r"^ak_([0-9a-f]{16})_[A-Za-z0-9_-]+$")


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass(slots=True)
class ApiKeyInfo:
    key_id: str
    prefix: str
    label: str
    admin: bool
    service: bool
    created_at: float
    last_used: float | None


class ApiKeyStore:
    def __init__(self, store: CredentialStore) -> None:
        self._store = store
        self._key_locks = tuple(threading.Lock() for _ in range(_KEY_LOCK_STRIPES))
        self._admin_lock = threading.Lock()

    def _lock_for(self, key_id: str) -> threading.Lock:
        return self._key_locks[hash(key_id) % _KEY_LOCK_STRIPES]

    # ── queries ──

    def count(self) -> int:
        return len(self._store.list_fields(NS_API_KEYS))

    def list_keys(self) -> list[ApiKeyInfo]:
        out = []
        for key_id, raw in self._store.list_items(NS_API_KEYS).items():
            record = json.loads(raw) if raw else None
            if record is not None:
                out.append(
                    ApiKeyInfo(
                        key_id=key_id,
                        prefix=record["prefix"],
                        label=record["label"],
                        admin=record["admin"],
                        service=bool(record.get("service", False)),
                        created_at=record["created_at"],
                        last_used=record.get("last_used"),
                    )
                )
        return out

    def _record(self, key_id: str) -> dict | None:
        raw = self._store.get(NS_API_KEYS, key_id)
        return json.loads(raw) if raw else None

    # ── mint / verify / revoke ──

    def mint(
        self, label: str, *, admin: bool = False, service: bool = False
    ) -> tuple[str, str]:
        """Returns (key_id, plaintext). Plaintext is shown exactly once."""
        if admin and service:
            raise AgentError(
                ErrorCategory.VALIDATION, "a key cannot be both admin and service"
            )
        key_id = secrets.token_hex(8)
        plaintext = f"ak_{key_id}_{secrets.token_urlsafe(32)}"
        record = {
            "hash": _hash(plaintext),
            "prefix": plaintext[:11],  # "ak_" + key_id[:8]
            "label": label,
            "admin": admin,
            "service": service,
            "created_at": time.time(),
            "last_used": None,
        }
        self._store.set(NS_API_KEYS, key_id, json.dumps(record))
        return key_id, plaintext

    def verify(self, presented: str) -> Identity | None:
        match = _API_KEY_RE.fullmatch(presented)
        if match is None:
            return None
        candidates = [match.group(1)]
        presented_hash = _hash(presented)
        for key_id in candidates:
            record = self._record(key_id)
            if record is None:
                continue
            if hmac.compare_digest(record["hash"], presented_hash):
                now = time.time()
                last_used = record.get("last_used")
                if last_used is None or now - last_used > _LAST_USED_WRITE_INTERVAL:
                    self._touch_last_used(key_id, record["hash"], now)
                return Identity(
                    kind="api_key",
                    subject=key_id,
                    admin=bool(record["admin"]),
                    service=bool(record.get("service", False)),
                    label=record["label"],
                )
        return None

    def _touch_last_used(self, key_id: str, expected_hash: str, now: float) -> None:
        # Best-effort: a skipped write only delays last_used. Store set() is an
        # upsert, so re-read under the per-key lock to never re-create a
        # concurrently revoked row.
        lock = self._lock_for(key_id)
        if not lock.acquire(blocking=False):
            return
        try:
            current = self._record(key_id)
            if current is None or current["hash"] != expected_hash:
                return
            current["last_used"] = now
            self._store.set(NS_API_KEYS, key_id, json.dumps(current))
        finally:
            lock.release()

    def revoke(self, key_id: str) -> None:
        with self._lock_for(key_id):
            record = self._record(key_id)
            if record is None:
                raise AgentError(ErrorCategory.NOT_FOUND, "unknown key id")
            if not record["admin"]:
                self._store.delete(NS_API_KEYS, key_id)
                return
            # Serialises the last-admin check + delete across admin revokes only.
            with self._admin_lock:
                other_admins = [
                    k
                    for k, raw in self._store.list_items(NS_API_KEYS).items()
                    if k != key_id and raw and json.loads(raw).get("admin")
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
            file=sys.stderr,
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
