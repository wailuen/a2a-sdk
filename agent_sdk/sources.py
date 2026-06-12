"""SourceAdapter — base class for upstream data sources (DESIGN.md §4.2).

The SDK owns instantiation: one instance per registered class, constructed at
lifespan startup with ``(settings, credential_resolver)`` plus any
``init_kwargs`` passed to ``register_source``. Tools receive instances via
keyword-only parameters annotated with the adapter class (exact-class match).
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable
from urllib.parse import urlparse

import httpx

from .models.errors import AgentError, ErrorCategory

CredentialResolver = Callable[[str, str], str | None]  # (source_name, field) -> value


class SourceAdapter:
    source_name: str = ""
    allowed_hosts: list[str] = []
    # Redirect-following is disabled and pinned (SSRF bypass via allowed-host
    # redirect). Subclasses that opt in must set follow_redirects=True AND
    # every hop is re-checked by the event hook below.
    follow_redirects: bool = False
    timeout_seconds: float = 30.0

    def __init__(self, settings: Any, credential_resolver: CredentialResolver) -> None:
        if not self.source_name:
            raise ValueError(f"{type(self).__name__} must declare source_name")
        self.settings = settings
        self._resolve_credential = credential_resolver
        self._client: httpx.AsyncClient | None = None
        self._lock = asyncio.Lock()

    # ── credentials ──
    def credential(self, field: str) -> str:
        """Resolve from this source's namespace only ({source_name}/{field})."""
        value = self._resolve_credential(self.source_name, field)
        if value is None:
            raise AgentError(
                ErrorCategory.AUTH,
                f"credential '{field}' for source '{self.source_name}' is not configured",
                source=self.source_name,
            )
        return value

    def credential_or_none(self, field: str) -> str | None:
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

    # ── lifecycle ──
    async def health_check(self) -> bool:  # pragma: no cover - subclass hook
        return True

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
