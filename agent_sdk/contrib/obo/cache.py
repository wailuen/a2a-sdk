"""MsalTokenCache — MSAL SerializableTokenCache backed by the SDK credential store.

Simpler than the m365 SqliteTokenCache: the SDK CredentialStore is fully
synchronous (EncryptedSqliteStore guards itself with threading.Lock), so
``_flush()`` calls ``store.set()`` directly from whatever thread invokes it.
MSAL dispatches its cache callbacks via ``asyncio.to_thread`` (worker threads),
so no ``run_coroutine_threadsafe`` / deadlock-guard machinery is needed.

Created automatically by GraphSource when ``build_app()`` calls
``_bind_credential_store``. Passed as ``token_cache=`` to OboExchanger, which
forwards it to ``msal.ConfidentialClientApplication``.
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ...credentials.store import CredentialStore

logger = logging.getLogger("agent_sdk.contrib.obo.cache")

_CACHE_KEY = "msal_token_cache"


def _make_msal_cache() -> Any:
    """Lazily create a fresh ``msal.SerializableTokenCache``.
    Separated so tests can patch it without the real ``msal`` package."""
    try:
        from msal import SerializableTokenCache  # type: ignore[import-not-found]
    except ImportError as exc:
        raise ImportError(
            "msal is required for MsalTokenCache — install agent-sdk[obo]"
        ) from exc
    return SerializableTokenCache()


def _msal_cache_class() -> Any:
    try:
        from msal import SerializableTokenCache  # type: ignore[import-not-found]
        return SerializableTokenCache
    except ImportError:
        return None


class MsalTokenCache:
    """MSAL-compatible token cache backed by the SDK encrypted credential store.

    Implements the ``msal.SerializableTokenCache`` duck-type so MSAL's
    ``ConfidentialClientApplication`` accepts it as ``token_cache=``.

    Pass ``store=None`` for an ephemeral (in-memory) cache — writes are silently
    dropped. Useful in tests and environments without a configured store.

    The cache is persisted under ``{namespace}/{_CACHE_KEY}`` in the store
    (default field name: ``"msal_token_cache"``). The ``namespace`` should match
    the adapter's ``source_name`` so a custom subclass with a different name gets
    its own isolated cache slot.
    """

    # Mirror MSAL class-level attributes that ConfidentialClientApplication
    # reads from the cache object (CredentialType, AuthorityType, key_makers).
    _msal_cls = _msal_cache_class()
    if _msal_cls is not None:
        CredentialType = getattr(_msal_cls, "CredentialType", None)
        AuthorityType = getattr(_msal_cls, "AuthorityType", None)
        key_makers = getattr(_msal_cls, "key_makers", None)
    del _msal_cls

    def __init__(
        self,
        store: "CredentialStore | None",
        namespace: str,
        _cache_factory=None,
    ) -> None:
        """Construct a MsalTokenCache.

        Parameters
        ----------
        store:
            SDK CredentialStore for persistence, or ``None`` for an ephemeral
            (in-memory) cache.
        namespace:
            Key prefix used when reading/writing the blob in *store*.
        _cache_factory:
            Optional zero-argument callable that returns a duck-typed
            ``msal.SerializableTokenCache``.  Intended for unit tests that want
            to inject a fake inner cache without patching module-level
            ``_make_msal_cache``.  Production code must not pass this argument.
        """
        self._store = store
        self._namespace = namespace
        self._lock = threading.Lock()
        factory = _cache_factory if _cache_factory is not None else _make_msal_cache
        self._cache = factory()

        if store is None:
            logger.debug("obo.cache: no store — cache is ephemeral")
            return

        blob = store.get(namespace, _CACHE_KEY)
        if blob:
            with self._lock:
                self._cache.deserialize(blob)
            logger.debug("obo.cache: loaded (namespace=%s)", namespace)

    # ── MSAL cache protocol ───────────────────────────────────────────────────

    @property
    def has_state_changed(self) -> bool:
        return self._cache.has_state_changed  # type: ignore[no-any-return]

    def serialize(self) -> str:
        with self._lock:
            return self._cache.serialize()  # type: ignore[no-any-return]

    def deserialize(self, state: str) -> None:
        with self._lock:
            self._cache.deserialize(state)

    def find(self, credential_type: str, **kwargs: Any) -> list[dict[str, Any]]:
        with self._lock:
            return self._cache.find(credential_type, **kwargs)  # type: ignore[no-any-return]

    def search(self, credential_type: str, **kwargs: Any) -> list[dict[str, Any]]:
        """MSAL 1.30+ renamed ``find`` → ``search``."""
        with self._lock:
            return self._cache.search(credential_type, **kwargs)  # type: ignore[no-any-return]

    def add(self, event: dict[str, Any], now: Any = None) -> None:
        with self._lock:
            self._cache.add(event, now=now)
        self._flush()

    def remove_rt(self, rt_item: dict[str, Any]) -> None:
        with self._lock:
            self._cache.remove_rt(rt_item)
        self._flush()

    def remove_at(self, at_item: dict[str, Any]) -> None:
        with self._lock:
            self._cache.remove_at(at_item)
        self._flush()

    def modify(self, credential_type: str, old: dict, new: dict) -> None:
        with self._lock:
            self._cache.modify(credential_type, old, new)
        self._flush()

    def update_rt(self, rt_item: dict[str, Any], new_rt: str) -> None:
        """MSAL 1.x: called on refresh-token rotation."""
        with self._lock:
            self._cache.update_rt(rt_item, new_rt)
        self._flush()

    def remove_account(self, account: dict[str, Any]) -> None:
        with self._lock:
            self._cache.remove_account(account)
        self._flush()

    def remove_idt(self, idt_item: dict[str, Any]) -> None:
        with self._lock:
            self._cache.remove_idt(idt_item)
        self._flush()

    # ── persistence ──────────────────────────────────────────────────────────

    def _flush(self) -> None:
        """Persist the cache if MSAL flagged a state change.

        Thread-safe: ``EncryptedSqliteStore.set()`` holds its own lock, so
        calling from MSAL worker-thread callbacks (dispatched via
        ``asyncio.to_thread``) is safe — no extra synchronisation needed.

        MSAL contract: ``serialize()`` resets ``has_state_changed`` to False,
        preventing a concurrent flush from double-writing even though
        ``store.set()`` runs outside the lock.
        """
        if self._store is None:
            return
        with self._lock:
            if not self._cache.has_state_changed:
                return
            blob = self._cache.serialize()
        try:
            self._store.set(self._namespace, _CACHE_KEY, blob)
            logger.debug("obo.cache: flushed (namespace=%s)", self._namespace)
        except Exception:
            logger.debug("obo.cache: flush failed (namespace=%s)", self._namespace)


__all__ = ["MsalTokenCache"]
