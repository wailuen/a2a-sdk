"""SourceAdapter — base class for upstream data sources (DESIGN.md §4.2).

The SDK owns instantiation: one instance per registered class, constructed at
lifespan startup with ``(settings, credential_resolver)`` plus any
``init_kwargs`` passed to ``register_source``. Tools receive instances via
keyword-only parameters annotated with the adapter class (exact-class match).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from .models.errors import AgentError, ErrorCategory

CredentialResolver = Callable[[str, str], str | None]  # (source_name, field) -> value


class SourceAdapter:
    source_name: str = ""
    allowed_hosts: list[str] = []
    # Set _no_http = True on adapters that never make outbound HTTP requests
    # (e.g. CommitmentsSource). Exempts them from the build-time allowed_hosts
    # non-empty check while keeping the SSRF guard intact for HTTP adapters.
    _no_http: bool = False
    # Redirect-following is disabled and pinned (SSRF bypass via allowed-host
    # redirect). Subclasses that opt in must set follow_redirects=True AND
    # every hop is re-checked by the event hook below.
    follow_redirects: bool = False
    timeout_seconds: float = 30.0

    def __init__(self, settings: Any, credential_resolver: CredentialResolver) -> None:
        if not self.source_name:
            raise ValueError(f"{type(self).__name__} must declare source_name")
        if not self.allowed_hosts and not self._no_http:
            raise ValueError(
                f"{type(self).__name__} must declare non-empty allowed_hosts "
                f"or set _no_http = True for non-HTTP adapters (SI-7)"
            )
        self.settings = settings
        self._resolve_credential = credential_resolver
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()
        # Set by build_app() after __init__ via _bind_credential_store().
        # Adapters that need write access to the store (e.g. MsalTokenCache in
        # GraphSource) override _bind_credential_store to act on it.
        self._store: Any = None

    # ── credentials ──
    def credential(self, field: str) -> str:
        """Resolve an upstream credential from this adapter's encrypted namespace.

        Storage path: ``{source_name}/{field}`` in the AES-256-GCM SQLite store.
        Lifecycle:
          1. Admin enters the value once via the console at ``/admin → Credentials``.
          2. The store encrypts it with MASTER_KEY.
          3. Every call here decrypts and returns just this adapter's field.

        This is the ONLY correct way to access upstream/vendor API keys.
        Do NOT use ``os.environ``, ``os.getenv``, or ``self.settings.*`` —
        those are SI-4 violations caught by /redteam (fail-closed).
        """
        value = self._resolve_credential(self.source_name, field)
        if value is None:
            raise AgentError(
                ErrorCategory.AUTH,
                f"credential '{field}' for source '{self.source_name}' is not configured",
                source=self.source_name,
            )
        return value

    def credential_or_none(self, field: str) -> str | None:
        """Like credential() but returns None instead of raising when not configured."""
        return self._resolve_credential(self.source_name, field)

    # ── HTTP ──
    def _check_host(self, url: httpx.URL | str) -> None:
        host = urlparse(str(url)).hostname or ""
        if not any(host == h or host.endswith("." + h) for h in self.allowed_hosts):
            raise AgentError(
                ErrorCategory.VALIDATION,
                f"request to host '{host}' is outside allowed_hosts for "
                f"source '{self.source_name}'",
                source=self.source_name,
            )

    async def _on_request(self, request: httpx.Request) -> None:
        # Re-checks every hop, including opted-in redirects.
        self._check_host(request.url)
        # DNS-rebinding guard: re-verify the resolved IP is public at request
        # time. validate_credential_url does this at save time; this closes the
        # TOCTOU window where a hostname could be rebounded to a private IP.
        # Skipped in DEV_MODE (localhost targets are valid in development).
        if not getattr(self.settings, "dev_mode", False):
            host = urlparse(str(request.url)).hostname or ""
            try:
                loop = asyncio.get_running_loop()
                infos = await loop.getaddrinfo(host, None)
            except socket.gaierror:
                raise AgentError(
                    ErrorCategory.VALIDATION,
                    f"cannot resolve host for source '{self.source_name}'",
                    source=self.source_name,
                )
            for info in infos:
                ip = ipaddress.ip_address(info[4][0])
                if (
                    ip.is_private
                    or ip.is_loopback
                    or ip.is_link_local
                    or ip.is_reserved
                    or ip.is_multicast
                    or ip.is_unspecified
                ):
                    raise AgentError(
                        ErrorCategory.VALIDATION,
                        f"upstream '{self.source_name}' host resolves to a non-public address",
                        source=self.source_name,
                    )

    @property
    def client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                timeout=self.timeout_seconds,
                follow_redirects=self.follow_redirects,
                event_hooks={"request": [self._on_request]},
            )
        return self._client

    async def get(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._request("GET", url, **kwargs)

    async def post(self, url: str, **kwargs: Any) -> httpx.Response:
        return await self._request("POST", url, **kwargs)

    async def _request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        self._check_host(url)
        try:
            resp = await self.client.request(method, url, **kwargs)
        except httpx.TimeoutException as exc:
            raise AgentError(
                ErrorCategory.TIMEOUT,
                f"upstream '{self.source_name}' timed out",
                source=self.source_name,
            ) from exc
        except httpx.HTTPError as exc:
            raise AgentError(
                ErrorCategory.UPSTREAM,
                f"upstream '{self.source_name}' request failed",
                source=self.source_name,
            ) from exc
        if resp.status_code in (429, 503):
            # retry-once policy (adapters own retries — tools never do)
            await asyncio.sleep(1.0)
            resp = await self.client.request(method, url, **kwargs)
        if resp.status_code == 401 or resp.status_code == 403:
            raise AgentError(
                ErrorCategory.AUTH,
                f"upstream '{self.source_name}' rejected credentials",
                source=self.source_name,
            )
        if resp.status_code == 429:
            raise AgentError(
                ErrorCategory.RATE_LIMITED,
                f"upstream '{self.source_name}' rate limited",
                source=self.source_name,
            )
        if resp.status_code >= 400:
            raise AgentError(
                ErrorCategory.UPSTREAM,
                f"upstream '{self.source_name}' returned {resp.status_code}",
                source=self.source_name,
            )
        return resp

    # ── SDK-internal store hook ──
    def _bind_credential_store(self, store: Any) -> None:
        """SDK-internal: called by build_app() after __init__.

        Gives adapters that need write access to the credential store a chance
        to act (e.g. GraphSource creates MsalTokenCache here). Do not call from
        user code. Override in subclasses; always call super()."""
        self._store = store

    # ── lifecycle ──
    async def health_check(self) -> bool:  # pragma: no cover - subclass hook
        return True

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
